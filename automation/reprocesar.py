#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Vuelve a procesar un remate ya publicado, sin esperar a que aparezca uno nuevo.

Sirve cuando se mejora el motor o el prompt y hay que recuperar el remate
actual con la logica nueva.

    python automation/reprocesar.py                      # el remate publicado
    python automation/reprocesar.py <url de YouTube>     # otro video
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import build_site                      # noqa: E402
import motor_remate as motor           # noqa: E402
from check_and_update import (ACTUAL_PATH, HISTORIAL_DIR,   # noqa: E402
                              fecha_desde_meta, guardar_last_processed)


def main():
    with open(ACTUAL_PATH, encoding="utf-8") as f:
        actual = json.load(f)

    url = sys.argv[1] if len(sys.argv) > 1 else actual.get("video_url")
    if not url:
        raise SystemExit("No hay video_url en data/remate_actual.json ni se paso uno por argumento.")

    print(f"· Reprocesando: {url}")
    filas, meta = motor.extraer_lotes_vendidos(url)
    if not filas:
        raise SystemExit("No se extrajo ningun lote. No se toca nada.")

    fecha = fecha_desde_meta(meta)
    os.makedirs(HISTORIAL_DIR, exist_ok=True)
    motor.escribir_csv(filas, os.path.join(HISTORIAL_DIR, f"remate_{fecha}.csv"))

    with open(ACTUAL_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": fecha,
            "video_url": url,
            "video_id": meta.get("id"),
            "titulo_video": meta.get("title", ""),
            "generado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lots": filas,
        }, f, ensure_ascii=False, indent=2)

    resultado = build_site.build()
    guardar_last_processed(meta.get("id"), fecha)
    print(f"· Reprocesado el remate del {fecha}: "
          f"{len(resultado.clasificados)} lotes publicados de {len(filas)} leidos.")


if __name__ == "__main__":
    main()
