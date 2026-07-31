# -*- coding: utf-8 -*-
"""
Pipeline de clasificacion. Un lote pasa exactamente por estos pasos, en orden:

     1. Leer lote
     2. Validar OCR
     3. Validar peso
     4. Validar sexo
     5. Validar raza
     6. Detectar tipo de remate      (se resuelve una vez por remate)
     7. Clasificar segun PESO
     8. Comparar con la clase SOLO como validacion secundaria
     9. Guardar categoria
    10. Actualizar estadisticas      (engine/stats.py)
    11. Registrar auditoria          (engine/audit.py)

REGLA CENTRAL: el peso siempre decide. La clase nunca elige categoria; si
discrepa del peso, se anota como conflicto y se sigue con lo que dice el peso.

Prioridad: peso > tipo de remate > sexo > clase (solo validacion).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .audit import Auditoria
from .config import Categoria, Config, cargar_config
from .normalize import (
    a_numero, clase_coincide, detectar_tipo_remate, es_mixto,
    normalizar, resolver_raza, resolver_sexo,
)
from .stats import estadisticas_por_categoria


@dataclass
class LoteClasificado:
    """Un lote que paso todas las validaciones y tiene categoria asignada."""
    lote: Any
    categoria_id: str
    categoria: str
    sexo: str
    raza: str
    peso_kg: float
    precio_bs_kg: float
    cantidad: int
    clase_leida: str = ""
    conflicto_clase: bool = False
    crudo: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Resultado:
    tipo_remate: str
    clasificados: List[LoteClasificado]
    stats: Dict[str, dict]
    auditoria: Auditoria


# ---------------------------------------------------------------------------
# Pasos 2-5: validaciones. Funciones puras -> (ok, valor, motivo, detalle)
# ---------------------------------------------------------------------------

def validar_ocr(bruto: dict) -> Tuple[bool, Optional[str], str]:
    """Paso 2. El lote tiene que tener al menos identificador y algun contenido."""
    if bruto.get("vacio"):
        return False, "ocr_critico", "la pantalla no mostraba un lote"
    if bruto.get("lote") in (None, ""):
        return False, "ocr_critico", "sin numero de lote"
    if not any(bruto.get(c) for c in ("clase", "raza", "peso_prom_kg", "precio_bs_kg")):
        return False, "ocr_critico", "el cartel no arrojo ningun campo legible"
    return True, None, ""


def validar_precio(bruto: dict, cfg: Config) -> Tuple[bool, Optional[float], str, str]:
    """Guarda de sanidad previa: sin precio valido el lote no aporta nada."""
    precio = a_numero(bruto.get("precio_bs_kg"))
    if precio is None or precio <= 0:
        return False, None, "precio_invalido", "sin precio de cierre (lote en puja)"
    if not (cfg.precio_min_bs_kg <= precio <= cfg.precio_max_bs_kg):
        return False, None, "precio_invalido", f"precio {precio} Bs/kg fuera de rango"
    return True, precio, "", ""


def cartel_coherente(bruto: dict, cfg: Config) -> Optional[bool]:
    """El cartel debe cumplir  TOTAL = SUBTOTAL x CANTIDAD.

    Es un chequeo de integridad sobre tres lecturas independientes. Si no
    cierra, al menos una esta mal leida y NINGUN peso derivado de ellas es
    confiable. Devuelve None si faltan datos para poder chequear.

    Por que hace falta: verificando contra fotogramas se vio que cuando la IA
    lee mal el peso, con frecuencia devuelve un subtotal *consistente con su
    propio error* (lote 418: leyo peso 115,71 y subtotal 1.972,74, que cierran
    entre si, pero el cartel decia 415,71 y 7.137,74). Por eso el acuerdo entre
    peso y subtotal no prueba nada; la coherencia con el total, si.
    """
    subtotal = a_numero(bruto.get("subtotal_bs"))
    total = a_numero(bruto.get("total_bs"))
    cantidad = a_numero(bruto.get("cantidad"))
    if not (subtotal and subtotal > 0 and total and total > 0 and cantidad and cantidad >= 1):
        return None
    esperado = total / cantidad
    return abs(esperado - subtotal) / subtotal * 100.0 <= cfg.tolerancia_peso_pct


def peso_desde_cartel(bruto: dict, precio: float, cfg: Config) -> Tuple[Optional[float], str]:
    """Recalcula el peso con la aritmetica del cartel.

        SUBTOTAL = PESO x PRECIO x (1 + comision)
        =>  PESO = SUBTOTAL / (PRECIO x (1+c))

    Solo tiene sentido llamarla cuando `cartel_coherente` dio True.
    Devuelve (peso, fuente).
    """
    if precio <= 0:
        return None, ""
    factor = precio * (1.0 + cfg.comision_cartel)
    if factor <= 0:
        return None, ""
    subtotal = a_numero(bruto.get("subtotal_bs"))
    if subtotal and subtotal > 0:
        return subtotal / factor, "subtotal"
    total = a_numero(bruto.get("total_bs"))
    cantidad = a_numero(bruto.get("cantidad"))
    if total and total > 0 and cantidad and cantidad >= 1:
        return total / (cantidad * factor), "total"
    return None, ""


def validar_peso(bruto: dict, precio: float, cfg: Config,
                 auditoria: Optional[Auditoria] = None,
                 lote_id=None) -> Tuple[bool, Optional[float], str, str]:
    """Paso 3. El peso es OBLIGATORIO; sin el, no hay clasificacion posible.

    Antes de validar rangos, se reconcilia el peso leido contra el que se
    deduce del subtotal. Si discrepan mas de la tolerancia, gana el deducido
    y la correccion queda auditada.
    """
    peso = a_numero(bruto.get("peso_prom_kg"))
    coherente = cartel_coherente(bruto, cfg)

    if coherente is False:
        # El cartel no cierra consigo mismo: alguna cifra esta mal leida y no
        # se puede saber cual. No se adivina — se descarta.
        sub = a_numero(bruto.get("subtotal_bs"))
        tot = a_numero(bruto.get("total_bs"))
        cant = a_numero(bruto.get("cantidad"))
        return False, None, "cartel_inconsistente", (
            f"total/cantidad ({tot:.2f}/{cant:.0f} = {tot / cant:.2f}) no coincide "
            f"con el subtotal leido ({sub:.2f}); alguna cifra del cartel esta mal leida")

    if coherente is True:
        derivado, fuente = peso_desde_cartel(bruto, precio, cfg)
        base = a_numero(bruto.get("subtotal_bs")) if fuente == "subtotal" else a_numero(bruto.get("total_bs"))
        if derivado is not None and derivado > 0:
            if peso is None or peso <= 0:
                if auditoria is not None:
                    auditoria.corregir_peso(lote_id, 0.0, derivado, base, precio, fuente)
                peso = derivado
            elif abs(peso - derivado) / derivado * 100.0 > cfg.tolerancia_peso_pct:
                if auditoria is not None:
                    auditoria.corregir_peso(lote_id, peso, derivado, base, precio, fuente)
                peso = derivado

    # coherente is None -> el cartel no aporto las cifras para chequear; se usa
    # el peso leido tal cual (compatibilidad con datos extraidos antes).
    if peso is None or peso <= 0:
        return False, None, "peso_inexistente", "el cartel no arrojo peso promedio"

    if not (cfg.peso_min_kg <= peso <= cfg.peso_max_kg):
        return False, None, "peso_fuera_de_rango", (
            f"{peso:.2f} kg fuera de {cfg.peso_min_kg:.0f}-{cfg.peso_max_kg:.0f} kg")
    return True, peso, "", ""


def validar_sexo(bruto: dict, cfg: Config) -> Tuple[bool, Optional[str], str, str]:
    """Paso 4. Sin sexo determinable se descarta: no se adivina."""
    if es_mixto(cfg.patrones_mixto, bruto.get("clase"), bruto.get("sexo"), bruto.get("raza")):
        return False, None, "lote_mixto", "el cartel indica machos y hembras"
    sexo = resolver_sexo(bruto.get("sexo"), bruto.get("clase"), cfg.sexo_sinonimos)
    if sexo is None:
        return False, None, "sexo_inexistente", (
            f"no se pudo determinar el sexo (sexo={bruto.get('sexo')!r}, "
            f"clase={bruto.get('clase')!r})")
    return True, sexo, "", ""


def validar_raza(bruto: dict, cfg: Config) -> Tuple[bool, Optional[str], str, str]:
    """Paso 5. Solo se aceptan las razas configuradas (y sus cruces)."""
    raza = resolver_raza(bruto.get("raza"), cfg.razas)
    if raza is None:
        aceptadas = ", ".join(r.canonica for r in cfg.razas)
        return False, None, "raza_invalida", (
            f"raza {bruto.get('raza')!r} no esta entre las aceptadas ({aceptadas})")
    return True, raza, "", ""


# ---------------------------------------------------------------------------
# Paso 7: clasificacion POR PESO
# ---------------------------------------------------------------------------

def clasificar_por_peso(sexo: str, peso_kg: float, tipo_remate: str,
                        cfg: Config) -> Optional[Categoria]:
    """Devuelve la unica categoria cuyo tramo de peso cubre el valor.

    La clase no interviene. Si la categoria que corresponde por peso no esta
    habilitada para este tipo de remate, devuelve None (el lote se descarta con
    motivo 'sin_categoria') en vez de forzarlo a una categoria vecina.
    """
    for cat in cfg.categorias_de(sexo):
        if cat.cubre_peso(peso_kg):
            return cat if cat.disponible_en(tipo_remate) else None
    return None


# ---------------------------------------------------------------------------
# Pipeline por lote (pasos 1-9 + registro)
# ---------------------------------------------------------------------------

def procesar_lote(bruto: dict, tipo_remate: str, cfg: Config,
                  auditoria: Auditoria) -> Optional[LoteClasificado]:
    """Aplica el pipeline a un lote. Devuelve None si se descarta."""
    lote_id = bruto.get("lote")

    def descartar(motivo, detalle):
        auditoria.descartar(
            lote=lote_id, motivo=motivo, motivo_texto=cfg.motivo(motivo), detalle=detalle,
            datos={k: bruto.get(k) for k in
                   ("clase", "sexo", "raza", "peso_prom_kg", "precio_bs_kg", "cantidad")},
        )
        return None

    # 2. OCR
    ok, motivo, detalle = validar_ocr(bruto)
    if not ok:
        return descartar(motivo, detalle)

    # 2b. Precio (guarda de sanidad: sin precio el lote no aporta al promedio)
    ok, precio, motivo, detalle = validar_precio(bruto, cfg)
    if not ok:
        return descartar(motivo, detalle)

    # 3. Peso (reconciliado contra la aritmetica del cartel)
    ok, peso, motivo, detalle = validar_peso(bruto, precio, cfg, auditoria, lote_id)
    if not ok:
        return descartar(motivo, detalle)

    # 4. Sexo (incluye deteccion de lote mixto)
    ok, sexo, motivo, detalle = validar_sexo(bruto, cfg)
    if not ok:
        return descartar(motivo, detalle)

    # 5. Raza
    ok, raza, motivo, detalle = validar_raza(bruto, cfg)
    if not ok:
        return descartar(motivo, detalle)

    # 7. Clasificar POR PESO (6 ya se resolvio para todo el remate)
    cat = clasificar_por_peso(sexo, peso, tipo_remate, cfg)
    if cat is None:
        return descartar("sin_categoria", (
            f"{peso:.0f} kg ({sexo}) no corresponde a ninguna categoria "
            f"habilitada en remate {tipo_remate}"))

    # 8. Comparar con la clase SOLO como validacion secundaria (nunca decide)
    clase_leida = str(bruto.get("clase") or "")
    hay_conflicto = not clase_coincide(clase_leida, cat.clases_esperadas)
    if hay_conflicto:
        auditoria.conflicto(lote_id, clase_leida, cat.nombre, peso)

    # 9. Guardar categoria
    return LoteClasificado(
        lote=lote_id,
        categoria_id=cat.id,
        categoria=cat.nombre,
        sexo=sexo,
        raza=raza,
        peso_kg=peso,
        precio_bs_kg=precio,
        cantidad=max(int(a_numero(bruto.get("cantidad")) or 1), 1),
        clase_leida=clase_leida,
        conflicto_clase=hay_conflicto,
        crudo=bruto,
    )


# ---------------------------------------------------------------------------
# Pipeline por remate (pasos 6, 10, 11)
# ---------------------------------------------------------------------------

def procesar_remate(lotes: List[dict], titulo_video: str = "",
                    tipo_remate: Optional[str] = None,
                    cfg: Optional[Config] = None) -> Resultado:
    """Procesa todos los lotes de un remate y devuelve datos + stats + auditoria.

    `tipo_remate` fuerza el tipo; si no se pasa, se detecta del titulo y, si el
    titulo no lo dice, se usa el valor por defecto de la configuracion.
    """
    cfg = cfg or cargar_config()

    # 6. Detectar tipo de remate (una vez por remate)
    if tipo_remate:
        detectado = True
    else:
        tipo_remate, detectado = detectar_tipo_remate(
            titulo_video, cfg.tipos_remate, cfg.tipo_remate_por_defecto)

    auditoria = Auditoria(
        tipo_remate=tipo_remate,
        tipo_remate_detectado=detectado,
        total_entrada=len(lotes),
    )

    # 1-9 por lote
    clasificados = []
    for bruto in lotes:
        resultado = procesar_lote(bruto, tipo_remate, cfg, auditoria)
        if resultado is not None:
            clasificados.append(resultado)

    auditoria.total_clasificados = len(clasificados)

    # 10. Estadisticas (promedio PONDERADO por cantidad de animales)
    stats = estadisticas_por_categoria(clasificados, tipo_remate, cfg)

    # 11. La auditoria ya quedo registrada; el llamador decide donde guardarla.
    return Resultado(
        tipo_remate=tipo_remate,
        clasificados=clasificados,
        stats=stats,
        auditoria=auditoria,
    )
