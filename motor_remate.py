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
    """Agrupa los frames por lote y devuelve UNO por lote: el ULTIMO legible.

    POR QUE EL ULTIMO Y NO EL MAS NITIDO
    ------------------------------------
    El precio del cartel es la puja EN VIVO: arranca en 0 y va subiendo hasta
    que cae el martillo. Verificado en el video (lote 461):

        t=11110 -> 0      t=11185 -> 28,50
        t=11160 -> 27,00  t=11210 -> 29,00   t=11235 -> 29,10

    La firma que detecta el cambio de lote mira la barra inferior (lote, clase,
    raza) y NO el recuadro del precio, asi que toda la puja de un lote cae en
    un mismo grupo. Quedarse con el frame mas nitido del grupo devolvia un
    precio del MEDIO de la puja (28,50 en vez de 29,10): el portal publicaba
    precios sistematicamente por debajo del cierre.

    Quedandose con el ultimo frame legible del grupo se obtiene el ultimo
    estado observado del lote, que es lo mas cerca del precio de cierre que
    permite el muestreo. Cuesta lo mismo: sigue siendo un frame por lote.
    """
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
        # De cada grupo se retiene el ULTIMO frame legible. Los frames que no
        # llegan al umbral son plantillas vacias, publicidad o el logo: si el
        # grupo entero es asi, `cur` queda en None y el grupo no existe.
        if fill >= min_fill:
            if cur is None:
                cur = {"t": t, "fill": fill, "frame": frame.copy()}
            else:
                cur.update(t=t, fill=fill, frame=frame.copy())
        prev = sig; t += step
    if cur is not None:
        lots.append(cur)
    cap.release()

    # recortar a la franja inferior (barra de datos + recuadro de precio)
    for l in lots:
        h = l["frame"].shape[0]
        l["crop"] = l["frame"][int(h * 0.60):h, :]

    print(f"· Lotes-candidatos detectados: {len(lots)}")
    return lots


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
- "sexo": "macho", "hembra" o "mixto". Deducilo de la clase: Ternero/Torillo/Toro/Novillo = macho; Ternera/Vaquilla/Vaquillona/Vaca = hembra. Si el cartel dice explicitamente que el lote lleva machos Y hembras, pon "mixto".
- "edad": texto de edad (ej. "5 años","8 meses") o null
- "raza": raza (ej. "Nelore","Holando","Mestizo","Anelorado","Brahman","Criollo") o null
- "peso_prom_kg": peso promedio en kg (numero, tipicamente 100-500). NO es el subtotal en Bs.
- "precio_bs_kg": el PRECIO POR KILO en Bs. Es el numero CHICO del recuadro (tipicamente entre 8 y 30), el que multiplica al peso. Si marca 0, pon 0.
- "subtotal_bs": el SUBTOTAL en Bs (el numero de miles que aparece debajo, a la izquierda de "Bs") o null.
- "total_bs": el TOTAL en Bs (el numero de la derecha, el mas grande) o null.
- "procedencia": lugar de procedencia o null

El recuadro arriba a la derecha muestra:

    PESO PROMEDIO   x   PRECIO Kg/Bs
        422.50              20.70
      8,833.21  Bs        52,999.24

  -> "peso_prom_kg" = el PESO PROMEDIO (arriba a la izquierda, 50-900 kg).
  -> "precio_bs_kg" = el PRECIO (arriba a la derecha, 8-30 Bs/kg).
  -> "subtotal_bs"  = el numero abajo a la izquierda, junto a "Bs" (8,833.21).
  -> "total_bs"     = el numero abajo a la derecha (52,999.24).

ATENCION con el PESO PROMEDIO: esta en tipografia digital roja y es facil
confundir el primer digito. Un '4' se parece a un '1'. Antes de responder,
comproba tu lectura con esta cuenta que el cartel siempre cumple:

    subtotal = peso_promedio x precio x 1.01

Si no cierra, volve a mirar el peso digito por digito. Ejemplo real: leer
122.50 donde dice 422.50 da 122.50 x 20.70 x 1.01 = 2560, muy lejos del
subtotal 8,833.21; con 422.50 da 8,833.2, que si cierra.

Reglas:
- OJO con el sexo del ternero: si el cartel dice "Ternera" es HEMBRA, si dice "Ternero" es MACHO. Leelo con cuidado.
- No inventes el sexo: si el cartel no permite deducirlo, pon null. Es preferible null a una suposicion.
- Si la pantalla NO muestra un lote (esta vacia, es publicidad o el logo), devuelve {"vacio": true}.
- Si el precio marca 0, el lote esta EN PUJA: incluye igual los datos con "precio_bs_kg": 0.
Devuelve unicamente el JSON."""


# NOTA DE ARQUITECTURA
# --------------------
# Este archivo es SOLO el extractor: convierte un video en filas crudas.
# NO clasifica, NO valida reglas de negocio y NO conoce las categorias del
# portal. Toda esa logica vive en `engine/` y se configura en
# `config/clasificacion.json`. Si necesitas cambiar categorias, rangos de peso
# o razas aceptadas, no toques este archivo.


def read_lot_with_claude(jpeg_bytes, client, model):
    b64 = base64.b64encode(jpeg_bytes).decode()
    for intento in range(3):
        try:
            msg = client.messages.create(
                model=model, max_tokens=2000,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": PROMPT},
                ]}],
            )
            # OJO: no se puede tomar content[0] a ciegas. Los modelos con
            # razonamiento activo (Opus 5 lo trae por defecto) devuelven un
            # bloque "thinking" ANTES del texto, y ese bloque no tiene .text.
            txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
            if not txt:
                raise ValueError("la respuesta no trajo texto")
            # aislar el JSON aunque venga con texto alrededor
            i, j = txt.find("{"), txt.rfind("}")
            if i < 0 or j < 0:
                raise ValueError(f"la respuesta no trae JSON: {txt[:80]!r}")
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
def extraer_lotes_vendidos(video_url, start=60, end=11700, step=None,
                            model=None, client=None):
    """Lee el video en DOS pasadas.

    1a pasada: todos los carteles con un modelo rapido y barato.
    2a pasada: solo los lotes cuyo cartel no cierra su propia aritmetica se
               releen con un modelo mas capaz.

    El disparador de la segunda pasada es el mismo control de integridad que
    usa engine/ para decidir si publica el lote, asi que no hay dos criterios
    distintos de calidad dando vueltas. Que modelos se usan y si el repaso
    esta activo se define en config/clasificacion.json.
    """
    from engine import cargar_config
    from engine.pipeline import cartel_coherente

    cfg = cargar_config()
    model = model or cfg.modelo_lectura
    step = step or cfg.paso_muestreo_seg

    # Se recorre el video ENTERO. Antes habia un tope fijo de 11700 s (3,25 h)
    # que dejaba sin revisar las ultimas 2 horas del remate del 30/07, que dura
    # 5,3 h. Los remates de FERCOGAN van de 1 a 6 horas.
    meta = get_video_meta(video_url)
    if meta["duration"]:
        end = max(start + 60, meta["duration"] - 20)

    print(f"· Recorriendo el video cada {step} s "
          f"(~{max(0, (end - start) // step)} fotogramas a revisar)...")
    stream = get_stream_url(video_url)
    lots = detect_lot_frames(stream, start, end, step)

    client = client or get_client()
    print(f"· Pasada 1: leyendo {len(lots)} carteles con {model}...")

    # El unico filtro que aplica el EXTRACTOR es el de deduplicacion: el mismo
    # lote aparece en varios frames y hay que quedarse con el precio de cierre
    # (el mas alto). El rango de precio sale de la misma configuracion que usa
    # el motor -> no hay numeros duplicados entre este archivo y engine/.
    vendidos, frames = {}, {}
    for k, l in enumerate(lots):
        d = read_lot_with_claude(crop_to_jpeg(l["crop"]), client, model)
        if d.get("vacio") or not d.get("lote"):
            continue
        try:
            precio = float(d.get("precio_bs_kg") or 0)
        except (TypeError, ValueError):
            precio = 0
        # precio 0 = lote en puja, todavia sin cierre: no sirve para dedupe.
        if not (cfg.precio_min_bs_kg <= precio <= cfg.precio_max_bs_kg):
            continue

        # Se guarda TODO tal cual lo leyo la IA. Validar y clasificar es
        # responsabilidad de engine/, no de este archivo.
        d["segundo_video"] = l["t"]
        prev = vendidos.get(d["lote"])
        if prev is None or precio > (prev.get("precio_bs_kg") or 0):
            vendidos[d["lote"]] = d
            frames[d["lote"]] = l["crop"]
        if (k + 1) % 20 == 0:
            print(f"  ... {k+1}/{len(lots)} frames procesados")

    # ---- Pasada 2: releer solo los carteles que no cierran ----
    if cfg.repaso_activo and cfg.modelo_repaso and cfg.modelo_repaso != model:
        dudosos = [n for n, d in vendidos.items() if cartel_coherente(d, cfg) is False]
        if dudosos:
            print(f"· Pasada 2: {len(dudosos)} carteles no cierran su aritmetica; "
                  f"releyendo con {cfg.modelo_repaso}...")
            recuperados = 0
            for n in sorted(dudosos):
                crop = frames.get(n)
                if crop is None:
                    continue
                d2 = read_lot_with_claude(crop_to_jpeg(crop, quality=95),
                                          client, cfg.modelo_repaso)
                if d2.get("vacio") or not d2.get("lote"):
                    continue
                if cartel_coherente(d2, cfg) is True:
                    d2["segundo_video"] = vendidos[n]["segundo_video"]
                    vendidos[n] = d2
                    recuperados += 1
                    print(f"    lote {n}: recuperado")
            print(f"· Pasada 2: {recuperados} de {len(dudosos)} lotes recuperados.")

    filas = sorted(vendidos.values(), key=lambda x: x["lote"])
    print(f"· Lotes con precio de cierre extraidos: {len(filas)}")
    return filas, meta


CAMPOS_CSV = ["lote", "cantidad", "clase", "sexo", "edad", "raza",
              "peso_prom_kg", "precio_bs_kg", "subtotal_bs", "total_bs",
              "procedencia", "segundo_video"]


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
    ap.add_argument("--model", default=None,
                    help="Modelo de vision para la 1a pasada (por defecto, el de config/clasificacion.json)")
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

    # ---- Resumen usando el motor de clasificacion (no reglas propias) ----
    from engine import procesar_remate
    r = procesar_remate(filas, titulo_video=meta.get("title", ""))
    print("\n  Precio promedio ponderado por categoria:")
    for cat_id, s in r.stats.items():
        if s:
            print(f"    {s['nombre']:24} {s['precio_bs_kg']:6.2f} Bs/kg "
                  f"({s['n_lotes']} lotes / {s['n_cabezas']} cabezas)")
    print("\n  Auditoria:")
    r.auditoria.imprimir(prefijo="    ")


if __name__ == "__main__":
    main()
