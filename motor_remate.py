#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=============================================================================
 MOTOR DE EXTRACCION FERCOGAN  ·  video de remate  ->  CSV de lotes
=============================================================================

Toma el link de un video de remate de YouTube, detecta cada lote,
lee el cartel con IA de vision (API de Claude) y produce un CSV limpio.

--- COMO SE USA (3 pasos) ---------------------------------------------------

1) Instalar las dependencias (una sola vez):
      python -m pip install yt-dlp opencv-python-headless numpy anthropic

2) Poner TU clave de la API de Claude como variable de entorno.
   (La clave la pones vos; este script solo la LEE del entorno, nunca la guarda.)
      Windows (PowerShell):   $env:ANTHROPIC_API_KEY = "sk-ant-..."
      Windows (CMD):          set ANTHROPIC_API_KEY=sk-ant-...

3) Correr el motor:
      python motor_remate.py "https://www.youtube.com/watch?v=XXXX" --out remate.csv

--- MODO PRUEBA (sin API, gratis) -------------------------------------------
   Solo detecta lotes y guarda los frames (no llama a la API, no cuesta nada):
      python motor_remate.py "<url>" --no-api --out frames/

   Ventana corta para probar rapido (ej. del minuto 40 al 45):
      python motor_remate.py "<url>" --start 2400 --end 2700 --no-api
=============================================================================
"""

import os, sys, io, csv, json, base64, argparse, subprocess, time
import numpy as np
import cv2


# --------------------------------------------------------------------------
# 1. Obtener la URL directa del stream (sin descargar el video entero)
# --------------------------------------------------------------------------
# YouTube bloquea seguido los pedidos que vienen de servidores en la nube
# (GitHub Actions, AWS, etc.) con un chequeo "Sign in to confirm you're not
# a bot". Cambiar el "cliente" no alcanza en esas IPs; hace falta una cookie
# de sesion real. Si existe un cookies.txt (lo escribe el workflow a partir
# del secreto YOUTUBE_COOKIES), se usa. Si no, sigue funcionando igual para
# uso local en una PC normal, donde ese bloqueo casi nunca aparece.
COOKIES_FILE = os.environ.get(
    "YTDLP_COOKIES_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt"),
)


def yt_args():
    # "android_vr" es el cliente que trae la lista completa de formatos
    # (incluido el "18" que usa el motor) para videos con reclamos de
    # copyright de fondo musical, que bloquean al cliente "web" normal.
    # Las cookies hacen falta aparte para pasar el chequeo de bot de
    # servidores en la nube (GitHub Actions, etc.).
    args = ["--extractor-args", "youtube:player_client=android_vr"]
    if os.path.exists(COOKIES_FILE):
        args += ["--cookies", COOKIES_FILE]
    return args


def get_stream_url(video_url: str) -> str:
    print("· Obteniendo stream del video...")
    out = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--no-warnings", *yt_args(), "-f", "18", "-g", video_url],
        capture_output=True, text=True,
    )
    lines = [l for l in out.stdout.strip().splitlines() if l.startswith("http")]
    if not lines:
        raise SystemExit("ERROR: no se pudo obtener el stream.\n" + out.stderr[-2000:])
    return lines[0]


def get_video_meta(video_url: str) -> dict:
    """Duracion, fecha de subida y titulo del video (sin descargarlo)."""
    out = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--no-warnings", *yt_args(), "-J", "--skip-download", video_url],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit("ERROR: no se pudo leer metadata del video.\n" + out.stderr[-2000:])
    info = json.loads(out.stdout)
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "duration": int(info.get("duration") or 0),
        "upload_date": info.get("upload_date") or "",  # YYYYMMDD
    }


def get_channel_latest_videos(channel_url: str, limit: int = 8) -> list:
    """Lista los ultimos videos de un canal (sin descargar nada), mas nuevo primero."""
    out = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--no-warnings", *yt_args(), "--flat-playlist",
         "--playlist-end", str(limit), "-J", channel_url],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit("ERROR: no se pudo listar el canal.\n" + out.stderr[-2000:])
    info = json.loads(out.stdout)
    entries = info.get("entries") or []
    videos = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": e.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return videos


# --------------------------------------------------------------------------
# 2. Detectar los lotes distintos y quedarse con el mejor frame de cada uno
#    (misma logica ya probada: muestreo + % de pixeles que cambian)
# --------------------------------------------------------------------------
def _signature(frame):
    h, w = frame.shape[:2]
    bar = frame[int(h * 0.80):int(h * 0.99), 0:w]
    g = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (200, 40)).astype(np.uint8)


def _fill(frame):
    h, w = frame.shape[:2]
    cell = frame[int(h * 0.82):int(h * 0.90), int(w * 0.02):int(w * 0.16)]
    return float(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY).var())


def detect_lot_frames(stream_url, start, end, step, change_frac=0.030, min_fill=120):
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise SystemExit("ERROR: no se pudo abrir el stream para leer frames.")
    prev, cur, lots, t = None, None, [], start
    while t <= end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            t += step; continue
        sig, fill = _signature(frame), _fill(frame)
        changed = prev is None or float(np.mean(cv2.absdiff(sig, prev) > 25)) > change_frac
        if changed and cur is not None:
            lots.append(cur); cur = None
        if cur is None:
            cur = {"t": t, "fill": fill, "frame": frame.copy()}
        elif fill > cur["fill"]:
            cur.update(t=t, fill=fill, frame=frame.copy())
        prev = sig; t += step
    if cur is not None:
        lots.append(cur)
    cap.release()
    # descartar plantillas vacias (poca info en la celda del nº de lote)
    good = [l for l in lots if l["fill"] >= min_fill]
    # recortar a la franja inferior (barra de datos + recuadro de precio)
    for l in good:
        h = l["frame"].shape[0]
        l["crop"] = l["frame"][int(h * 0.60):h, :]
    print(f"· Lotes-candidatos detectados: {len(good)}")
    return good


def crop_to_jpeg(bgr, quality=85):
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


# --------------------------------------------------------------------------
# 3. Leer UN lote con la IA de vision de Claude -> dict estructurado
# --------------------------------------------------------------------------
PROMPT = """Estas viendo el cartel de un remate de ganado (FERCOGAN, Bolivia).
Lee SOLO lo que aparece escrito en pantalla y devuelve un JSON valido, sin texto extra.

Campos:
- "lote": numero de lote (entero) o null
- "cantidad": cantidad de cabezas (entero) o null
- "clase": categoria TAL CUAL dice el cartel (ej. "Vaca","Vaquilla","Vaquillona","Torillo","Toro","Ternero","Ternera") o null
- "sexo": "macho" o "hembra". Deducilo de la clase: Ternero/Torillo/Toro/Novillo = macho; Ternera/Vaquilla/Vaquillona/Vaca = hembra.
- "edad": texto de edad (ej. "5 años","8 meses") o null
- "raza": raza (ej. "Nelore","Holando","Mestizo","Anelorado","Brahman","Criollo") o null
- "peso_prom_kg": peso promedio en kg (numero, tipicamente 100-500). NO es el subtotal en Bs.
- "precio_bs_kg": el PRECIO POR KILO en Bs. Es el numero CHICO del recuadro (tipicamente entre 8 y 30), el que multiplica al peso. Si marca 0, pon 0.
- "procedencia": lugar de procedencia o null

El recuadro de precio muestra:  PESO PROMEDIO  x  PRECIO  =  subtotal Bs  /  total Bs.
  -> "peso_prom_kg" = el PESO (100-500 kg).
  -> "precio_bs_kg" = el PRECIO (8-30 Bs/kg).
  -> NUNCA pongas el subtotal ni el total (numeros grandes, de miles) en esos campos.

Reglas:
- OJO con el sexo del ternero: si el cartel dice "Ternera" es HEMBRA, si dice "Ternero" es MACHO. Leelo con cuidado.
- Si la pantalla NO muestra un lote (esta vacia, es publicidad o el logo), devuelve {"vacio": true}.
- Si el precio marca 0, el lote esta EN PUJA: incluye igual los datos con "precio_bs_kg": 0.
Devuelve unicamente el JSON."""


def categoria_portal(clase, sexo=None):
    """Mapea la clase del cartel a una de las 6 categorias del portal."""
    c = (clase or "").lower()
    if "ternera" in c:
        return "Ternera"
    if "ternero" in c:
        return "Ternero"
    if "torillo" in c or "novillito" in c:
        return "Macho de recría"
    if "toro" in c or "novillo" in c:
        return "Toro / novillo gordo"
    if "vaquilla" in c or "vaquillona" in c:
        return "Hembra de recría"
    if "vaca" in c:
        return "Vaca gorda"
    return clase or ""


def read_lot_with_claude(jpeg_bytes, client, model):
    b64 = base64.b64encode(jpeg_bytes).decode()
    for intento in range(3):
        try:
            msg = client.messages.create(
                model=model, max_tokens=400,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": PROMPT},
                ]}],
            )
            txt = msg.content[0].text.strip()
            # aislar el JSON aunque venga con texto alrededor
            i, j = txt.find("{"), txt.rfind("}")
            return json.loads(txt[i:j + 1])
        except Exception as e:
            if intento == 2:
                print(f"  ! no se pudo leer un lote: {e}")
                return {"vacio": True, "error": str(e)[:80]}
            time.sleep(2)


def get_client(key: str = ""):
    import anthropic
    key = key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:  # si no esta en el entorno, la lee de clave.txt en Descargas
        p = os.path.join(os.path.expanduser("~"), "Downloads", "clave.txt")
        if os.path.exists(p):
            import re
            raw = open(p, encoding="utf-8-sig").read()
            m = re.search(r"sk-ant-[A-Za-z0-9_\-]{30,}", raw)
            key = m.group(0) if m else ""
    if not key:
        raise SystemExit("Falta tu clave: pone clave.txt en Descargas o set ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key)


# --------------------------------------------------------------------------
# 4. Extraer los lotes vendidos de un video (reusable, sin CLI ni CSV)
# --------------------------------------------------------------------------
def extraer_lotes_vendidos(video_url, start=60, end=11700, step=25,
                            model="claude-haiku-4-5-20251001", client=None,
                            peso_min=60, peso_max=900):
    meta = get_video_meta(video_url)
    if meta["duration"]:
        end = min(end, max(start + 60, meta["duration"] - 20))

    stream = get_stream_url(video_url)
    lots = detect_lot_frames(stream, start, end, step)

    client = client or get_client()
    print(f"· Leyendo {len(lots)} lotes con IA ({model})...")
    vendidos = {}   # dedupe por numero de lote, se queda con el precio mas alto
    for k, l in enumerate(lots):
        d = read_lot_with_claude(crop_to_jpeg(l["crop"]), client, model)
        if d.get("vacio") or not d.get("lote"):
            continue
        try:
            precio = float(d.get("precio_bs_kg") or 0)
        except (TypeError, ValueError):
            precio = 0
        if precio <= 0:                       # en puja: se descarta
            continue
        if not (5 <= precio <= 45):           # fuera de rango = lectura dudosa
            print(f"  ~ lote {d.get('lote')}: precio dudoso ({precio}) -> a revisar, se omite")
            continue
        try:
            peso = float(d.get("peso_prom_kg") or 0)
        except (TypeError, ValueError):
            peso = 0
        # el peso a veces se confunde con el subtotal del cartel (mucho mas grande) -> se omite el dato dudoso, se conserva el precio
        d["peso_prom_kg"] = peso if (peso_min <= peso <= peso_max) else ""
        d["categoria_portal"] = categoria_portal(d.get("clase"), d.get("sexo"))
        d["segundo_video"] = l["t"]
        prev = vendidos.get(d["lote"])
        if prev is None or precio > (prev.get("precio_bs_kg") or 0):
            vendidos[d["lote"]] = d
        if (k + 1) % 20 == 0:
            print(f"  ... {k+1}/{len(lots)} frames procesados")

    filas = sorted(vendidos.values(), key=lambda x: x["lote"])
    print(f"· Lotes VENDIDOS extraidos: {len(filas)}")
    return filas, meta


CAMPOS_CSV = ["lote", "cantidad", "clase", "sexo", "categoria_portal", "edad",
              "raza", "peso_prom_kg", "precio_bs_kg", "procedencia", "segundo_video"]


def escribir_csv(filas, out_path):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(CAMPOS_CSV)
        for d in filas:
            w.writerow([d.get(c, "") for c in CAMPOS_CSV])


# --------------------------------------------------------------------------
# 5. Programa principal (uso manual desde la terminal)
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Motor de extraccion FERCOGAN")
    ap.add_argument("video_url", help="Link del video de remate en YouTube")
    ap.add_argument("--out", default="remate.csv", help="Archivo CSV de salida (o carpeta en modo --no-api)")
    ap.add_argument("--start", type=int, default=60, help="Segundo inicial")
    ap.add_argument("--end", type=int, default=11700, help="Segundo final")
    ap.add_argument("--step", type=int, default=25, help="Segundos entre muestras")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001", help="Modelo de Claude para la vision")
    ap.add_argument("--no-api", action="store_true", help="Solo detecta y guarda frames (no llama a la API)")
    args = ap.parse_args()

    # ---- Modo prueba: guardar frames y salir (gratis) ----
    if args.no_api:
        stream = get_stream_url(args.video_url)
        lots = detect_lot_frames(stream, args.start, args.end, args.step)
        outdir = args.out if args.out.endswith(("/", "\\")) or "." not in os.path.basename(args.out) else "frames"
        os.makedirs(outdir, exist_ok=True)
        for k, l in enumerate(lots):
            cv2.imwrite(os.path.join(outdir, f"lote_{k:03d}_t{l['t']}s.jpg"), l["crop"])
        print(f"· MODO PRUEBA: {len(lots)} frames guardados en '{outdir}/' (no se llamo a la API).")
        return

    filas, meta = extraer_lotes_vendidos(args.video_url, args.start, args.end, args.step, args.model)
    escribir_csv(filas, args.out)
    print(f"· LISTO -> {args.out}")

    # ---- Resumen por categoria (para el reporte) ----
    from collections import defaultdict
    g = defaultdict(list)
    for d in filas:
        if d.get("precio_bs_kg"):
            g[d.get("clase") or "?"].append(d["precio_bs_kg"])
    print("\n  Promedio Bs/kg por categoria:")
    for cat, v in sorted(g.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"    {cat:12} {sum(v)/len(v):6.2f}   ({len(v)} lotes)")


if __name__ == "__main__":
    main()
