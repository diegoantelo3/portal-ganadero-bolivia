#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Vuelve a leer un remate YA GUARDADO en el historial, con la configuracion
actual, y reescribe su CSV.

Sirve cuando se mejora el motor y hay que dejar los remates viejos leidos con
el mismo criterio que los nuevos: si no, la seccion Tendencia compara lecturas
de distinta calidad y muestra variaciones que no son del mercado.

    python automation/reprocesar_historial.py 2026-07-30
    python automation/reprocesar_historial.py --todos
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import build_site                                  # noqa: E402
import motor_remate as motor                       # noqa: E402
from engine import cargar_config                   # noqa: E402
from engine.historial import remates_disponibles   # noqa: E402

DIR_HIST = os.path.join(ROOT, "data", "historial")
ACTUAL = os.path.join(ROOT, "data", "remate_actual.json")


def url_de(fecha):
    """Busca el link del video de ese remate en el canal de FERCOGAN."""
    cfg = cargar_config()
    d, m, a = fecha[8:10], fecha[5:7], fecha[0:4]
    patron = f"{d}/{m}/{a}"
    videos = motor.get_channel_latest_videos(
        "https://www.youtube.com/@FERCOGANvirtual/streams", limit=40)
    for v in videos:
        if patron in v["title"] and "remate comercial" in v["title"].lower():
            return v["url"], v["title"]
    return None, None


def reprocesar(fecha):
    cfg = cargar_config()
    print(f"\n=== Remate {fecha} ===")
    url, titulo = url_de(fecha)
    if not url:
        print(f"  No se encontro el video de {fecha} en el canal. Se omite.")
        return False
    print(f"  {titulo}")
    print(f"  Lectura con {cfg.modelo_lectura}, muestreo cada {cfg.paso_muestreo_seg} s")

    filas, meta = motor.extraer_lotes_vendidos(url)
    if not filas:
        print("  No se extrajo ningun lote. No se toca el historial.")
        return False

    destino = os.path.join(DIR_HIST, f"remate_{fecha}.csv")
    motor.escribir_csv(filas, destino)
    print(f"  Historial reescrito: {len(filas)} lotes -> {os.path.basename(destino)}")

    # Si es el remate que esta publicado, se actualiza tambien el portal.
    with open(ACTUAL, encoding="utf-8") as f:
        actual = json.load(f)
    if actual.get("fecha") == fecha:
        actual["lots"] = filas
        actual["titulo_video"] = titulo
        actual.pop("repaso_intentado", None)
        with open(ACTUAL, "w", encoding="utf-8") as f:
            json.dump(actual, f, ensure_ascii=False, indent=2)
        print("  Es el remate publicado: se actualiza el portal.")
    return True


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print(__doc__)
        print("Remates disponibles:", ", ".join(remates_disponibles(DIR_HIST)))
        return
    fechas = remates_disponibles(DIR_HIST) if args[0] == "--todos" else args

    hechos = sum(1 for f in fechas if reprocesar(f))
    if hechos:
        print("\n· Regenerando el portal con el historial actualizado...")
        build_site.build()


if __name__ == "__main__":
    main()
