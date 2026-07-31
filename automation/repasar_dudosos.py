#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Relee SOLO los lotes cuyo cartel no cierra su aritmetica, usando el modelo de
repaso configurado, y actualiza el remate publicado con los que se recuperen.

Sirve para aplicar una mejora del repaso sin volver a pagar la lectura completa
del video (~9% de los frames en vez del 100%).

    python automation/repasar_dudosos.py
"""

import json
import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import build_site                       # noqa: E402
import motor_remate as motor            # noqa: E402
from engine import cargar_config        # noqa: E402
from engine.pipeline import cartel_coherente  # noqa: E402

ACTUAL = os.path.join(ROOT, "data", "remate_actual.json")


def main():
    cfg = cargar_config()
    remate = json.load(open(ACTUAL, encoding="utf-8"))
    lots = remate["lots"]

    dudosos = [l for l in lots if cartel_coherente(l, cfg) is False]
    if not dudosos:
        print("· No hay carteles incoherentes. Nada que repasar.")
        return
    print(f"· {len(dudosos)} carteles no cierran; releyendo con {cfg.modelo_repaso}...")

    stream = motor.get_stream_url(remate["video_url"])
    cap = cv2.VideoCapture(stream)
    if not cap.isOpened():
        raise SystemExit("No se pudo abrir el stream del video.")
    client = motor.get_client()

    por_lote = {l["lote"]: l for l in lots}
    recuperados = 0
    for d in sorted(dudosos, key=lambda x: x["lote"] or 0):
        t = d.get("segundo_video")
        if not t:
            continue
        cap.set(cv2.CAP_PROP_POS_MSEC, int(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            print(f"    lote {d['lote']}: no se pudo leer el frame")
            continue
        h = frame.shape[0]
        crop = frame[int(h * 0.60):h, :]
        nuevo = motor.read_lot_with_claude(
            motor.crop_to_jpeg(crop, quality=95), client, cfg.modelo_repaso)

        if nuevo.get("vacio") or not nuevo.get("lote"):
            print(f"    lote {d['lote']}: el repaso no devolvio datos")
            continue
        if cartel_coherente(nuevo, cfg) is True:
            nuevo["segundo_video"] = t
            por_lote[d["lote"]] = nuevo
            recuperados += 1
            print(f"    lote {d['lote']}: RECUPERADO  "
                  f"(peso {d.get('peso_prom_kg')} -> {nuevo.get('peso_prom_kg')})")
        else:
            print(f"    lote {d['lote']}: sigue sin cerrar, se mantiene descartado")

    cap.release()
    print(f"· Recuperados {recuperados} de {len(dudosos)}.")

    if recuperados:
        remate["lots"] = sorted(por_lote.values(), key=lambda x: x["lote"] or 0)
        with open(ACTUAL, "w", encoding="utf-8") as f:
            json.dump(remate, f, ensure_ascii=False, indent=2)
        build_site.build()


if __name__ == "__main__":
    main()
