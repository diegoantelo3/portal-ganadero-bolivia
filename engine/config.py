# -*- coding: utf-8 -*-
"""
Carga y valida `config/clasificacion.json`.

El resto del motor NUNCA lee el JSON directamente ni asume nada sobre su
contenido: consume los objetos tipados que expone este modulo. Si el archivo
tiene un error (rangos solapados, huecos, sexo desconocido), se detecta aca y
se falla al arrancar, no en produccion con datos raros.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_CONFIG = os.path.join(RAIZ, "config", "clasificacion.json")

SEXOS_VALIDOS = ("macho", "hembra")


class ConfigInvalida(Exception):
    """El archivo de configuracion tiene un error que impide operar."""


@dataclass(frozen=True)
class Categoria:
    id: str
    nombre: str
    sexo: str
    desde_kg: float
    hasta_kg: Optional[float]      # None = "en adelante"
    remates: Tuple[str, ...]
    subtitulo: str
    etiqueta_corta: str
    etiqueta_estimador: str
    clases_esperadas: Tuple[str, ...]

    def cubre_peso(self, peso_kg: float) -> bool:
        """desde_kg inclusivo, hasta_kg exclusivo (tramos contiguos, sin huecos)."""
        if peso_kg < self.desde_kg:
            return False
        return self.hasta_kg is None or peso_kg < self.hasta_kg

    def disponible_en(self, tipo_remate: str) -> bool:
        return tipo_remate in self.remates


@dataclass(frozen=True)
class Raza:
    canonica: str
    patrones: Tuple[str, ...]


@dataclass(frozen=True)
class Config:
    version: int
    peso_min_kg: float
    peso_max_kg: float
    precio_min_bs_kg: float
    precio_max_bs_kg: float
    razas: Tuple[Raza, ...]
    sexo_sinonimos: Dict[str, Tuple[str, ...]]
    patrones_mixto: Tuple[str, ...]
    tipos_remate: Dict[str, dict]
    tipo_remate_por_defecto: str
    categorias: Tuple[Categoria, ...]
    estimador: Dict[str, float]
    motivos_descarte: Dict[str, str]

    # -- consultas ---------------------------------------------------------
    def categoria_por_id(self, cid: str) -> Optional[Categoria]:
        return next((c for c in self.categorias if c.id == cid), None)

    def categorias_de(self, sexo: str) -> List[Categoria]:
        return [c for c in self.categorias if c.sexo == sexo]

    def categorias_visibles(self, tipo_remate: str) -> List[Categoria]:
        """Las que corresponde mostrar para este tipo de remate, en orden."""
        return [c for c in self.categorias if c.disponible_en(tipo_remate)]

    def motivo(self, clave: str) -> str:
        return self.motivos_descarte.get(clave, clave)


def _validar(cfg: Config) -> None:
    if not cfg.categorias:
        raise ConfigInvalida("No hay categorias definidas.")

    ids = [c.id for c in cfg.categorias]
    if len(ids) != len(set(ids)):
        raise ConfigInvalida("Hay ids de categoria repetidos.")

    if cfg.tipo_remate_por_defecto not in cfg.tipos_remate:
        raise ConfigInvalida(
            f"tipo_remate_por_defecto={cfg.tipo_remate_por_defecto!r} no esta en tipos_remate.")

    for c in cfg.categorias:
        if c.sexo not in SEXOS_VALIDOS:
            raise ConfigInvalida(f"Categoria {c.id}: sexo {c.sexo!r} invalido.")
        if c.hasta_kg is not None and c.hasta_kg <= c.desde_kg:
            raise ConfigInvalida(f"Categoria {c.id}: hasta_kg <= desde_kg.")
        for r in c.remates:
            if r not in cfg.tipos_remate:
                raise ConfigInvalida(f"Categoria {c.id}: tipo de remate {r!r} desconocido.")

    # Por sexo: los tramos deben ser contiguos y no solaparse, para que todo
    # peso valido caiga en exactamente una categoria.
    for sexo in SEXOS_VALIDOS:
        tramos = sorted(cfg.categorias_de(sexo), key=lambda c: c.desde_kg)
        if not tramos:
            raise ConfigInvalida(f"No hay categorias para sexo {sexo!r}.")
        for anterior, siguiente in zip(tramos, tramos[1:]):
            if anterior.hasta_kg is None:
                raise ConfigInvalida(
                    f"Categoria {anterior.id} es abierta pero no es la ultima de {sexo}.")
            if anterior.hasta_kg != siguiente.desde_kg:
                raise ConfigInvalida(
                    f"{sexo}: hueco o solape entre {anterior.id} (hasta {anterior.hasta_kg}) "
                    f"y {siguiente.id} (desde {siguiente.desde_kg}).")
        if tramos[-1].hasta_kg is not None:
            raise ConfigInvalida(
                f"{sexo}: la ultima categoria ({tramos[-1].id}) debe ser abierta (hasta_kg: null).")

    if cfg.peso_min_kg >= cfg.peso_max_kg:
        raise ConfigInvalida("peso.min_kg >= peso.max_kg.")


def _construir(bruto: dict) -> Config:
    cats = tuple(
        Categoria(
            id=c["id"],
            nombre=c["nombre"],
            sexo=c["sexo"],
            desde_kg=float(c["desde_kg"]),
            hasta_kg=None if c.get("hasta_kg") is None else float(c["hasta_kg"]),
            remates=tuple(c["remates"]),
            subtitulo=c.get("subtitulo", ""),
            etiqueta_corta=c.get("etiqueta_corta", c["nombre"]),
            etiqueta_estimador=c.get("etiqueta_estimador", c["nombre"]),
            clases_esperadas=tuple(c.get("clases_esperadas", ())),
        )
        for c in bruto["categorias"]
    )
    sexo_cfg = {k: tuple(v) for k, v in bruto["sexo"].items() if not k.startswith("_")}
    return Config(
        version=int(bruto.get("version", 1)),
        peso_min_kg=float(bruto["peso"]["min_kg"]),
        peso_max_kg=float(bruto["peso"]["max_kg"]),
        precio_min_bs_kg=float(bruto["precio"]["min_bs_kg"]),
        precio_max_bs_kg=float(bruto["precio"]["max_bs_kg"]),
        razas=tuple(Raza(r["canonica"], tuple(r["patrones"])) for r in bruto["razas_aceptadas"]),
        sexo_sinonimos=sexo_cfg,
        patrones_mixto=tuple(bruto["mixto"]["patrones"]),
        tipos_remate={k: v for k, v in bruto["tipos_remate"].items()},
        tipo_remate_por_defecto=bruto["tipo_remate_por_defecto"],
        categorias=cats,
        estimador={k: float(v) for k, v in bruto.get("estimador", {}).items()},
        motivos_descarte=dict(bruto.get("motivos_descarte", {})),
    )


_cache: Dict[str, Config] = {}


def cargar_config(ruta: str = RUTA_CONFIG, recargar: bool = False) -> Config:
    """Carga (y cachea) la configuracion, validandola."""
    if not recargar and ruta in _cache:
        return _cache[ruta]
    if not os.path.exists(ruta):
        raise ConfigInvalida(f"No existe el archivo de configuracion: {ruta}")
    with open(ruta, encoding="utf-8") as f:
        bruto = json.load(f)
    cfg = _construir(bruto)
    _validar(cfg)
    _cache[ruta] = cfg
    return cfg
