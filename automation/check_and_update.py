#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Revisa el canal de FERCOGAN. Si hay un remate nuevo que todavia no se proceso,
lo lee con el motor, actualiza data/remate_actual.json y regenera index.html.

Se corre solo (GitHub Actions, una vez al dia) o a mano:
    python automation/check_and_update.py
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import motor_remate as motor  # noqa: E402
import build_site  # noqa: E402

CANAL = "https://www.youtube.com/@FERCOGANvirtual/streams"
LAST_PATH = os.path.join(ROOT, "data", "last_processed.json")
ACTUAL_PATH = os.path.join(ROOT, "data", "remate_actual.json")
HISTORIAL_DIR = os.path.join(ROOT, "data", "historial")


def es_remate(titulo: str) -> bool:
    """Reconoce un remate COMERCIAL (precio en Bs/kg por categoria).

    FERCOGAN publica el mismo remate con el titulo en espanol o en ingles
    ('REMATE COMERCIAL ...' / '... COMMERCIAL AUCTION ...'), asi que los
    patrones salen de config/clasificacion.json en vez de estar fijos aca.
    Se excluyen los remates de genetica, matrices y reproductores: esos se
    venden por animal y no por kilo.
    """
    from engine import cargar_config
    from engine.normalize import contiene_alguno

    cfg = cargar_config()
    if not contiene_alguno(titulo, cfg.patrones_remate):
        return False
    return not contiene_alguno(titulo, cfg.excluir_remate)


def cargar_last_processed():
    if os.path.exists(LAST_PATH):
        with open(LAST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"video_id": None}


def guardar_last_processed(video_id, fecha):
    os.makedirs(os.path.dirname(LAST_PATH), exist_ok=True)
    with open(LAST_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "video_id": video_id,
            "fecha": fecha,
            "actualizado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, ensure_ascii=False, indent=2)


def fecha_desde_meta(meta):
    """Fecha del remate (ISO) a partir del titulo y la fecha de subida.

    El titulo trae la fecha del remate en si, que es mas fiel que la de subida
    (esta ultima puede correrse un dia por el huso horario). El problema es que
    FERCOGAN publica el titulo en dos idiomas y el orden cambia:

        "REMATE COMERCIAL FERCOGAN SRL 01/08/2026"    -> dia/mes  = 1 de agosto
        "FERCOGAN SRL COMMERCIAL AUCTION 08/01/2026"  -> mes/dia  = 1 de agosto

    Es el MISMO remate. Leer siempre dia/mes fecharia el segundo como 8 de
    enero. Por eso se prueban las dos lecturas y se elige la que cae mas cerca
    de la fecha de subida del video, que no es ambigua.
    """
    subida = None
    ymd = meta.get("upload_date") or ""
    if len(ymd) == 8:
        try:
            subida = datetime(int(ymd[0:4]), int(ymd[4:6]), int(ymd[6:8]))
        except ValueError:
            subida = None

    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", meta.get("title") or "")
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        candidatos = []
        for dia, mes in ((a, b), (b, a)):          # dia/mes y mes/dia
            try:
                candidatos.append(datetime(y, mes, dia))
            except ValueError:
                pass                                # p.ej. mes 30 no existe
        if candidatos:
            if subida and len(candidatos) > 1:
                # la interpretacion mas cercana a la fecha de subida
                elegida = min(candidatos, key=lambda f: abs((f - subida).days))
            else:
                elegida = candidatos[0]
            return elegida.strftime("%Y-%m-%d")

    if subida:
        return subida.strftime("%Y-%m-%d")
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main():
    print("· Buscando el ultimo remate en el canal de FERCOGAN...")
    videos = motor.get_channel_latest_videos(CANAL, limit=10)
    candidatos = [v for v in videos if es_remate(v["title"])]
    if not candidatos:
        print("  No se encontro ningun video con 'remate' en el titulo entre los ultimos 10. Nada que hacer.")
        return

    ultimo = candidatos[0]
    previo = cargar_last_processed()
    if ultimo["id"] == previo.get("video_id"):
        print(f"  Ya esta procesado el ultimo remate ({ultimo['title']}). Nada nuevo.")
        return

    print(f"  Remate nuevo encontrado: {ultimo['title']} ({ultimo['url']})")
    filas, meta = motor.extraer_lotes_vendidos(ultimo["url"])
    if not filas:
        print("  El motor no encontro lotes vendidos validos en el video. No se actualiza el portal.")
        return

    fecha = fecha_desde_meta(meta)

    os.makedirs(HISTORIAL_DIR, exist_ok=True)
    motor.escribir_csv(filas, os.path.join(HISTORIAL_DIR, f"remate_{fecha}.csv"))

    remate_actual = {
        "fecha": fecha,
        "video_url": ultimo["url"],
        "video_id": ultimo["id"],
        # El titulo se guarda porque el motor detecta de ahi el tipo de remate
        # (INVERNO / CONSUMO / COMPLEMENTARIOS).
        "titulo_video": ultimo["title"],
        "generado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lots": filas,
    }
    with open(ACTUAL_PATH, "w", encoding="utf-8") as f:
        json.dump(remate_actual, f, ensure_ascii=False, indent=2)

    # build_site delega en engine/: valida, clasifica por peso, pondera por
    # cabezas y deja la auditoria en data/auditoria/.
    resultado = build_site.build()
    guardar_last_processed(ultimo["id"], fecha)
    print(f"· Portal actualizado con el remate del {fecha} "
          f"({len(resultado.clasificados)} lotes publicados de {len(filas)} leidos).")


if __name__ == "__main__":
    main()
