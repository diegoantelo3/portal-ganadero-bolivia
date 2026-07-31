# -*- coding: utf-8 -*-
"""
Verificacion del motor de clasificacion.

Corre sin dependencias externas:   python tests/test_engine.py
Cada bloque comprueba una regla del pliego.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import cargar_config, procesar_remate                      # noqa: E402
from engine.normalize import (a_numero, detectar_tipo_remate,          # noqa: E402
                              resolver_raza, resolver_sexo)
from engine.pipeline import clasificar_por_peso                        # noqa: E402
from engine.stats import promedio_ponderado                            # noqa: E402

CFG = cargar_config()
fallos = []


def check(nombre, condicion, extra=""):
    if condicion:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLA {nombre} {extra}")
        fallos.append(nombre)


def lote(**kw):
    base = {"lote": 1, "cantidad": 5, "clase": "Vaquilla", "sexo": "hembra",
            "raza": "Nelore", "peso_prom_kg": 300, "precio_bs_kg": 20}
    base.update(kw)
    return base


print("\n== Configuracion ==")
check("carga y valida sin errores", CFG.version >= 2)
check("12 categorias definidas", len(CFG.categorias) == 12, f"({len(CFG.categorias)})")
check("6 machos / 6 hembras",
      len(CFG.categorias_de("macho")) == 6 and len(CFG.categorias_de("hembra")) == 6)

print("\n== Normalizacion de raza (tolerancia OCR) ==")
for texto, esperado in [
    ("NELORE", "Nelore"), ("Nelor", "Nelore"), ("NeIore", "Nelore"),
    ("Nellore", "Nelore"), ("Nelore SIN PRENEZ", "Nelore"),
    ("Nelore H. DE . T. REG.", "Nelore"), ("Anelorado", "Nelore"),
    ("BRAHMAN", "Brahman"), ("Braman", "Brahman"),
    ("Nelore x Brahman", "Nelore x Brahman"), ("Brahman x Nelore", "Brahman x Nelore"),
    ("Gyr", None), ("Mestizo", None), ("Holando", None), ("Mediterranea", None), ("", None),
]:
    check(f"raza {texto!r} -> {esperado!r}", resolver_raza(texto, CFG.razas) == esperado,
          f"(dio {resolver_raza(texto, CFG.razas)!r})")

print("\n== Sexo ==")
check("explicito macho", resolver_sexo("macho", "", CFG.sexo_sinonimos) == "macho")
check("deduce hembra de 'Vaquillona'", resolver_sexo("", "Vaquillona", CFG.sexo_sinonimos) == "hembra")
check("deduce macho de 'Torillo'", resolver_sexo("", "Torillo", CFG.sexo_sinonimos) == "macho")
# Tolerancia OCR: 'Butorete' es una mala lectura de 'Torete' y contiene esa
# subcadena, asi que resolverlo como macho es correcto (mismo criterio que
# hace 'Anelorado' -> Nelore). Adivinar seria inventar un sexo sin evidencia.
check("tolera OCR: 'Butorete' -> macho", resolver_sexo("", "Butorete", CFG.sexo_sinonimos) == "macho")
check("sin evidencia -> None", resolver_sexo("", "Lote especial", CFG.sexo_sinonimos) is None)
check("vacio -> None", resolver_sexo("", "", CFG.sexo_sinonimos) is None)

print("\n== Numeros toleantes a formato ==")
check("coma decimal", a_numero("362,73") == 362.73)
check("separador de miles", a_numero("1.234,56") == 1234.56)
check("vacio -> None (no 0)", a_numero("") is None)
check("None -> None", a_numero(None) is None)

print("\n== Clasificacion POR PESO (COMPLEMENTARIOS) ==")
casos_macho = [(0, "Ternero"), (130, "Ternero"), (130.9, "Ternero"), (131, "Destete Machos"),
               (220, "Destete Machos"), (221, "Torillos Recría"), (300, "Torillos Recría"),
               (301, "Torillos para Engorde"), (400, "Torillos para Engorde"),
               (401, "Torillos"), (520, "Torillos"), (521, "Toros Gordos"), (900, "Toros Gordos")]
for peso, esperado in casos_macho:
    c = clasificar_por_peso("macho", peso, "COMPLEMENTARIOS", CFG)
    check(f"macho {peso} kg -> {esperado}", c is not None and c.nombre == esperado,
          f"(dio {c.nombre if c else None})")

casos_hembra = [(0, "Ternera"), (130, "Ternera"), (131, "Destete Hembras"),
                (210, "Destete Hembras"), (211, "Vaquillas Recría"), (270, "Vaquillas Recría"),
                (271, "Vaquillas Reposición"), (320, "Vaquillas Reposición"),
                (321, "Vaquillas"), (430, "Vaquillas"), (431, "Vacas"), (900, "Vacas")]
for peso, esperado in casos_hembra:
    c = clasificar_por_peso("hembra", peso, "COMPLEMENTARIOS", CFG)
    check(f"hembra {peso} kg -> {esperado}", c is not None and c.nombre == esperado,
          f"(dio {c.nombre if c else None})")

print("\n== Sin huecos: todo peso valido cae en exactamente una categoria ==")
huecos = []
p = CFG.peso_min_kg
while p <= CFG.peso_max_kg:
    for sexo in ("macho", "hembra"):
        n = sum(1 for c in CFG.categorias_de(sexo) if c.cubre_peso(p))
        if n != 1:
            huecos.append((sexo, p, n))
    p += 0.5
check("ningun hueco ni solape en 50-900 kg", not huecos, f"({huecos[:3]})")

print("\n== Gate por tipo de remate ==")
check("INVERNO no habilita Toros Gordos (600 kg)",
      clasificar_por_peso("macho", 600, "INVERNO", CFG) is None)
check("CONSUMO no habilita Ternero (100 kg)",
      clasificar_por_peso("macho", 100, "CONSUMO", CFG) is None)
check("COMPLEMENTARIOS habilita ambos extremos",
      clasificar_por_peso("macho", 600, "COMPLEMENTARIOS", CFG) is not None and
      clasificar_por_peso("macho", 100, "COMPLEMENTARIOS", CFG) is not None)

print("\n== Deteccion de tipo de remate ==")
check("titulo FERCOGAN -> COMPLEMENTARIOS",
      detectar_tipo_remate("REMATE COMERCIAL FERCOGAN SRL 30/07/2026",
                           CFG.tipos_remate, CFG.tipo_remate_por_defecto) == ("COMPLEMENTARIOS", True))
check("titulo con 'inverno' -> INVERNO",
      detectar_tipo_remate("REMATE INVERNO", CFG.tipos_remate,
                           CFG.tipo_remate_por_defecto)[0] == "INVERNO")
check("titulo vacio -> default sin detectar",
      detectar_tipo_remate("", CFG.tipos_remate,
                           CFG.tipo_remate_por_defecto) == ("COMPLEMENTARIOS", False))

print("\n== EL PESO GANA SOBRE LA CLASE ==")
r = procesar_remate([lote(lote=99, clase="Toro", sexo="macho", peso_prom_kg=122.5)],
                    titulo_video="REMATE COMERCIAL")
check("'Toro' de 122 kg se clasifica como Ternero",
      r.clasificados and r.clasificados[0].categoria == "Ternero",
      f"(dio {r.clasificados[0].categoria if r.clasificados else 'descartado'})")
check("y el conflicto queda auditado", len(r.auditoria.conflictos) == 1)
check("pero el lote NO se descarta", len(r.auditoria.descartes) == 0)

print("\n== Descartes ==")
casos_descarte = [
    ("peso inexistente", lote(peso_prom_kg=""), "peso_inexistente"),
    ("peso 0", lote(peso_prom_kg=0), "peso_inexistente"),
    ("peso fuera de rango", lote(peso_prom_kg=1200), "peso_fuera_de_rango"),
    ("peso bajo minimo", lote(peso_prom_kg=30), "peso_fuera_de_rango"),
    ("raza invalida", lote(raza="Holando"), "raza_invalida"),
    ("sexo indeterminado", lote(sexo="", clase="XYZ"), "sexo_inexistente"),
    ("lote mixto por clase", lote(clase="Mixto machos y hembras"), "lote_mixto"),
    ("lote mixto por sexo", lote(sexo="mixto"), "lote_mixto"),
    ("lote mixto 'ambos sexos'", lote(clase="Ambos sexos"), "lote_mixto"),
    ("sin precio (en puja)", lote(precio_bs_kg=0), "precio_invalido"),
    ("precio absurdo", lote(precio_bs_kg=9999), "precio_invalido"),
]
for nombre, l, motivo_esperado in casos_descarte:
    r = procesar_remate([l], titulo_video="REMATE COMERCIAL")
    ok = (not r.clasificados and r.auditoria.descartes
          and r.auditoria.descartes[0].motivo == motivo_esperado)
    dio = r.auditoria.descartes[0].motivo if r.auditoria.descartes else "clasificado"
    check(f"descarta {nombre} -> {motivo_esperado}", ok, f"(dio {dio})")

print("\n== Promedio PONDERADO por cabezas ==")
check("ponderado simple", abs(promedio_ponderado([(10, 1), (20, 3)]) - 17.5) < 1e-9)
check("sin cabezas -> None", promedio_ponderado([]) is None)

r = procesar_remate([
    lote(lote=1, cantidad=1, peso_prom_kg=350, precio_bs_kg=10),
    lote(lote=2, cantidad=19, peso_prom_kg=350, precio_bs_kg=20),
], titulo_video="REMATE COMERCIAL")
precio = r.stats["vaquillas"]["precio_bs_kg"]
check("1 lote de 1 cabeza + 1 de 19 -> 19.50 (no 15.00 del promedio simple)",
      abs(precio - 19.50) < 0.01, f"(dio {precio})")
check("cuenta las cabezas", r.stats["vaquillas"]["n_cabezas"] == 20)

print("\n== Reconciliacion del peso con la aritmetica del cartel ==")
# Datos tomados de fotogramas verificados del remate 30/07/2026.
# (lote, peso que leyo la IA, precio, subtotal real, peso REAL del cartel)
CARTELES_REALES = [
    (437, 122.50, 20.70, 8833.21, 422.50),
    (470, 127.50, 20.90, 9024.10, 427.50),
    (422, 194.00, 21.30, 10627.42, 494.00),
    (418, 115.71, 17.00, 7137.74, 415.71),
    (468, 107.50, 17.00, 6996.78, 407.50),
]
for lote_id, leido, precio, subtotal, real in CARTELES_REALES:
    r = procesar_remate([lote(lote=lote_id, clase="Toro", sexo="macho",
                             peso_prom_kg=leido, precio_bs_kg=precio,
                             subtotal_bs=subtotal)],
                        titulo_video="REMATE COMERCIAL")
    obtenido = r.clasificados[0].peso_kg if r.clasificados else None
    check(f"lote {lote_id}: corrige {leido} -> {real} kg",
          obtenido is not None and abs(obtenido - real) < 0.05, f"(dio {obtenido})")
    check(f"lote {lote_id}: la correccion queda auditada",
          len(r.auditoria.correcciones_peso) == 1)

r = procesar_remate([lote(peso_prom_kg=350, precio_bs_kg=20, subtotal_bs=350 * 20 * 1.01)],
                    titulo_video="REMATE COMERCIAL")
check("peso correcto NO se toca ni se audita",
      abs(r.clasificados[0].peso_kg - 350) < 0.05 and not r.auditoria.correcciones_peso)

r = procesar_remate([lote(peso_prom_kg=350, precio_bs_kg=20, subtotal_bs=None)],
                    titulo_video="REMATE COMERCIAL")
check("sin subtotal se usa el peso leido (compatibilidad hacia atras)",
      r.clasificados and abs(r.clasificados[0].peso_kg - 350) < 0.05)

r = procesar_remate([lote(peso_prom_kg="", precio_bs_kg=20, subtotal_bs=420 * 20 * 1.01)],
                    titulo_video="REMATE COMERCIAL")
check("sin peso legible se recupera del subtotal",
      r.clasificados and abs(r.clasificados[0].peso_kg - 420) < 0.05,
      f"(dio {r.clasificados[0].peso_kg if r.clasificados else 'descartado'})")

r = procesar_remate([lote(lote=437, clase="Toro", sexo="macho", peso_prom_kg=122.50,
                          precio_bs_kg=20.70, subtotal_bs=8833.21)],
                    titulo_video="REMATE COMERCIAL")
check("corregido el peso, 'Toro' ya NO entra en conflicto con la categoria",
      r.clasificados[0].categoria == "Torillos" and not r.auditoria.conflictos,
      f"(cat={r.clasificados[0].categoria}, conflictos={len(r.auditoria.conflictos)})")

print("\n== Categorias sin datos quedan declaradas ==")
r = procesar_remate([lote(peso_prom_kg=350)], titulo_video="REMATE COMERCIAL")
check("las 12 categorias aparecen en stats", len(r.stats) == 12, f"({len(r.stats)})")
check("las vacias valen None", r.stats["ternero"] is None)

print("\n" + "=" * 58)
if fallos:
    print(f"FALLARON {len(fallos)} verificaciones:")
    for f in fallos:
        print("   -", f)
    sys.exit(1)
print("TODAS LAS VERIFICACIONES PASARON")
