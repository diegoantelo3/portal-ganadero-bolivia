# -*- coding: utf-8 -*-
"""
Serie historica de precios por categoria.

Lee los CSV de `data/historial/` y los pasa por el MISMO pipeline que el
remate del dia, para que un precio historico y uno actual signifiquen
exactamente lo mismo (mismas validaciones, misma ponderacion por cabezas).

Se usa para responder la pregunta que mas le importa al ganadero:
"el precio de mi categoria, esta subiendo o bajando?"
"""

import csv
import glob
import os
import re
from typing import Dict, List, Optional

from .config import Config, cargar_config
from .pipeline import procesar_remate

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_HISTORIAL = os.path.join(RAIZ, "data", "historial")

_RE_FECHA = re.compile(r"remate_(\d{4}-\d{2}-\d{2})\.csv$")

NUMERICOS = ("cantidad", "peso_prom_kg", "precio_bs_kg", "subtotal_bs",
             "total_bs", "lote", "segundo_video")


def _a_valor(campo: str, texto: str):
    texto = (texto or "").strip()
    if not texto:
        return None if campo in NUMERICOS else ""
    if campo in NUMERICOS:
        try:
            v = float(texto)
            return int(v) if campo in ("lote", "cantidad", "segundo_video") else v
        except ValueError:
            return None
    return texto


def leer_csv(ruta: str) -> List[dict]:
    with open(ruta, encoding="utf-8-sig") as f:
        return [{c: _a_valor(c, v) for c, v in fila.items() if c} for fila in csv.DictReader(f)]


def remates_disponibles(dir_historial: str = DIR_HISTORIAL) -> List[str]:
    """Fechas (ISO) de los remates guardados, de mas viejo a mas nuevo."""
    fechas = []
    for ruta in glob.glob(os.path.join(dir_historial, "remate_*.csv")):
        m = _RE_FECHA.search(os.path.basename(ruta))
        if m:
            fechas.append(m.group(1))
    return sorted(fechas)


def serie_por_categoria(cfg: Optional[Config] = None,
                        dir_historial: str = DIR_HISTORIAL,
                        max_remates: int = 12) -> Dict[str, List[dict]]:
    """Devuelve {categoria_id: [{fecha, precio, n_lotes, n_cabezas}, ...]}.

    Solo incluye los puntos donde la categoria tuvo datos: una categoria que
    no aparecio en un remate no vale cero, simplemente no tiene punto.
    """
    cfg = cfg or cargar_config()
    fechas = remates_disponibles(dir_historial)[-max_remates:]

    serie: Dict[str, List[dict]] = {c.id: [] for c in cfg.categorias}
    for fecha in fechas:
        ruta = os.path.join(dir_historial, f"remate_{fecha}.csv")
        try:
            lots = leer_csv(ruta)
        except OSError:
            continue
        if not lots:
            continue
        r = procesar_remate(lots, titulo_video="", cfg=cfg)
        for cat_id, s in r.stats.items():
            if s:
                serie[cat_id].append({
                    "fecha": fecha,
                    "precio": s["precio_bs_kg"],
                    "n_lotes": s["n_lotes"],
                    "n_cabezas": s["n_cabezas"],
                })
    return serie


def variacion(serie_cat: List[dict]) -> Optional[dict]:
    """Compara el ultimo punto contra el anterior. None si no hay con que comparar."""
    if len(serie_cat) < 2:
        return None
    actual, previo = serie_cat[-1], serie_cat[-2]
    delta = round(actual["precio"] - previo["precio"], 2)
    pct = round(delta / previo["precio"] * 100, 1) if previo["precio"] else 0.0
    return {
        "delta": delta,
        "pct": pct,
        "sentido": "sube" if delta > 0.005 else ("baja" if delta < -0.005 else "igual"),
        "fecha_previa": previo["fecha"],
        "precio_previo": previo["precio"],
    }


def resumen_tendencia(cfg: Optional[Config] = None,
                      dir_historial: str = DIR_HISTORIAL) -> dict:
    """Todo lo que la capa de presentacion necesita para la seccion Tendencia."""
    cfg = cfg or cargar_config()
    serie = serie_por_categoria(cfg, dir_historial)
    fechas = remates_disponibles(dir_historial)
    filas = []
    for cat in cfg.categorias:
        puntos = serie.get(cat.id) or []
        if not puntos:
            continue
        filas.append({
            "categoria_id": cat.id,
            "nombre": cat.nombre,
            "sexo": cat.sexo,
            "precio": puntos[-1]["precio"],
            "puntos": puntos,
            "variacion": variacion(puntos),
        })
    return {
        "n_remates": len(fechas),
        "fechas": fechas,
        "hay_comparacion": any(f["variacion"] for f in filas),
        "filas": filas,
    }
