#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Revisa el canal de FERCOGAN y procesa TODOS los remates que falten, del mas
viejo al mas nuevo. El ultimo queda publicado en el portal; todos quedan en el
historial.

Se corre solo (cada hora, ver ACTUALIZAR-PORTAL.bat) o a mano:
    python automation/check_and_update.py

POR QUE "TODOS LOS QUE FALTEN" Y NO "EL ULTIMO"
Antes solo se miraba el remate mas nuevo. Si un dia fallaba (video bloqueado,
sin saldo, YouTube caido) y al dia siguiente aparecia otro, el que fallo
quedaba atras para siempre: nunca volvia a ser "el mas nuevo". Ahora se lleva
la lista de los ya procesados y se completa lo que falte, asi el historial no
queda con agujeros.

CHEQUEAR ES GRATIS
Listar el canal tarda ~3 s y no llama a la API de Claude. Por eso conviene
chequear seguido: solo se gasta cuando hay un remate nuevo de verdad.
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
PROCESADOS_PATH = os.path.join(ROOT, "data", "procesados.json")
ACTUAL_PATH = os.path.join(ROOT, "data", "remate_actual.json")
HISTORIAL_DIR = os.path.join(ROOT, "data", "historial")

# Cuantas veces se reintenta un video que falla antes de darlo por perdido.
# Un video bloqueado por derechos de autor no se va a poder leer nunca, y no
# tiene que trabar la cola de los que si se pueden.
MAX_INTENTOS = 3


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


# --------------------------------------------------------------------------
# Registro de lo ya procesado (y de lo que fallo)
# --------------------------------------------------------------------------

def cargar_procesados():
    """{video_id: {estado, fecha, titulo, intentos, motivo}}.

    Migra automaticamente desde el last_processed.json viejo la primera vez.
    """
    if os.path.exists(PROCESADOS_PATH):
        with open(PROCESADOS_PATH, encoding="utf-8") as f:
            return json.load(f).get("videos", {})

    registro = {}
    previo = cargar_last_processed()
    if previo.get("video_id"):
        registro[previo["video_id"]] = {
            "estado": "ok",
            "fecha": previo.get("fecha", ""),
            "titulo": "",
            "intentos": 1,
        }
    # Los remates que ya estan en el historial tampoco hay que rehacerlos,
    # aunque no se sepa de que video salieron.
    return registro


def guardar_procesados(registro):
    os.makedirs(os.path.dirname(PROCESADOS_PATH), exist_ok=True)
    with open(PROCESADOS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "actualizado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "videos": registro,
        }, f, ensure_ascii=False, indent=2)


def fechas_posibles_del_titulo(titulo):
    """Las lecturas validas de la fecha del titulo, sin consultar YouTube.

    FERCOGAN publica en dos idiomas y el orden cambia, asi que "08/07/2026"
    puede ser el 8 de julio (dia/mes) o el 7 de agosto (mes/dia). Devuelve las
    dos cuando ambas existen; una sola cuando no hay ambigüedad posible (un 30
    no puede ser mes); vacia si el titulo no trae fecha.
    """
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", titulo or "")
    if not m:
        return []
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    fechas = []
    for dia, mes in ((a, b), (b, a)):
        try:
            f = datetime(y, mes, dia)
        except ValueError:
            continue
        if f not in fechas:
            fechas.append(f)
    return fechas


def es_reciente(titulo, dias, si_ambiguo=False):
    """True si el remate entra en la ventana de dias que se procesa sola.

    Cuando las dos lecturas de la fecha caen del mismo lado de la ventana no
    importa cual sea la buena: la respuesta es la misma. Solo hace falta
    desempatar cuando discrepan -- el caso "08/07" mirado un 07/08, que haria
    pasar por nuevo un remate de hace un mes -- y ahi decide `si_ambiguo`, que
    el llamador resuelve por la posicion en el canal (ver separar_por_fecha).

    Deliberadamente NO consulta YouTube: la primera version pedia la fecha de
    subida y una verificacion anti-bot volteaba la corrida entera.
    """
    fechas = fechas_posibles_del_titulo(titulo)
    if not fechas:
        return True          # sin fecha en el titulo, mejor mirarlo que perderlo

    hoy = datetime.now()
    dentro = {(hoy - f).days <= dias for f in fechas}
    return dentro.pop() if len(dentro) == 1 else si_ambiguo


def separar_por_fecha(faltantes, remates, registro, dias):
    """Divide los remates sin procesar en (recientes, viejos).

    El desempate de las fechas ambiguas sale del ORDEN del canal, que YouTube
    ya devuelve del mas nuevo al mas viejo y no cuesta ni una consulta extra:
    si el video esta por encima del ultimo que procesamos, es mas nuevo que
    ese, asi que es de los que hay que mirar. Si esta por debajo, es historial.
    """
    pos = {v["id"]: i for i, v in enumerate(remates)}
    # El procesado mas nuevo: primero de la lista con estado ok.
    corte = next((i for i, v in enumerate(remates)
                  if registro.get(v["id"], {}).get("estado") == "ok"), None)

    recientes, viejos = [], []
    for v in faltantes:
        if corte is None:
            # Arranque en frio: no hay con que comparar. Que decida la fecha
            # mas cercana a hoy, que es lo mas probable en un canal activo.
            ambiguo = min(fechas_posibles_del_titulo(v["title"]) or [datetime.now()],
                          key=lambda f: abs((f - datetime.now()).days))
            si_ambiguo = (datetime.now() - ambiguo).days <= dias
        else:
            si_ambiguo = pos[v["id"]] < corte
        (recientes if es_reciente(v["title"], dias, si_ambiguo) else viejos).append(v)
    return recientes, viejos


def hay_que_procesar(video_id, registro):
    r = registro.get(video_id)
    if r is None:
        return True
    if r.get("estado") == "ok":
        return False
    # fallado: se reintenta hasta MAX_INTENTOS
    return int(r.get("intentos", 0)) < MAX_INTENTOS


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


def procesar_video(video, registro):
    """Lee un remate y lo guarda en el historial. Devuelve la fecha o None.

    Deja constancia en `registro` tanto si sale bien como si falla, para que
    un video que no se puede leer (bloqueado por derechos, por ejemplo) no
    trabe la cola en cada corrida.
    """
    vid = video["id"]
    intentos = int(registro.get(vid, {}).get("intentos", 0)) + 1

    def marcar(estado, fecha="", motivo=""):
        registro[vid] = {
            "estado": estado, "fecha": fecha, "titulo": video["title"],
            "intentos": intentos, "motivo": motivo[:200],
            "visto_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    print(f"\n  → {video['title']}")
    try:
        filas, meta = motor.extraer_lotes_vendidos(video["url"])
    except motor.RemateEnCurso as e:
        # El remate se esta transmitiendo AHORA. No se marca nada en el
        # registro: no es un intento fallido, es un "todavia no". Si contara
        # como intento, tres chequeos por hora bastarian para descartar el
        # remate del dia antes de que termine.
        print(f"    todavia en vivo ({e}). Se lee cuando termine.")
        return None
    except motor.SinCredito:
        raise                       # sin saldo se corta todo, no es culpa del video
    except SystemExit as e:
        # video bloqueado, borrado, o YouTube rechazando el pedido
        print(f"    no se pudo leer: {str(e)[:120]}")
        marcar("fallado", motivo=str(e))
        return None

    if not filas:
        print("    el video no tenia lotes con precio de cierre.")
        marcar("fallado", motivo="sin lotes con precio de cierre")
        return None

    fecha = fecha_desde_meta(meta)
    os.makedirs(HISTORIAL_DIR, exist_ok=True)
    motor.escribir_csv(filas, os.path.join(HISTORIAL_DIR, f"remate_{fecha}.csv"))

    with open(ACTUAL_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": fecha,
            "video_url": video["url"],
            "video_id": vid,
            # El titulo se guarda porque el motor detecta de ahi el tipo de
            # remate (INVERNO / CONSUMO / COMPLEMENTARIOS).
            "titulo_video": video["title"],
            "generado_el": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lots": filas,
        }, f, ensure_ascii=False, indent=2)

    marcar("ok", fecha=fecha)
    guardar_last_processed(vid, fecha)
    print(f"    remate del {fecha}: {len(filas)} lotes leidos.")
    return fecha


def main():
    print("· Revisando el canal de FERCOGAN...")
    videos = motor.get_channel_latest_videos(CANAL, limit=15)
    remates = [v for v in videos if es_remate(v["title"])]
    if not remates:
        print("  No hay remates comerciales entre los ultimos 15 videos.")
        return

    from engine import cargar_config
    dias = cargar_config().dias_hacia_atras

    registro = cargar_procesados()
    faltantes = [v for v in remates if hay_que_procesar(v["id"], registro)]

    # Solo los recientes: sin este limite la primera corrida se pondria a leer
    # todo el canal. Los mas viejos se traen a mano con reprocesar_historial.py.
    recientes, viejos = separar_por_fecha(faltantes, remates, registro, dias)

    # El canal devuelve el mas nuevo primero; se procesa del mas VIEJO al mas
    # nuevo para que el ultimo que quede publicado sea el mas reciente.
    pendientes = recientes[::-1]

    if viejos:
        print(f"  ({len(viejos)} remate(s) de mas de {dias} dias se omiten; "
              f"para traerlos: python automation/reprocesar_historial.py)")

    if not pendientes:
        print(f"  Al dia: no hay remates nuevos de los ultimos {dias} dias.")
        return

    print(f"  {len(pendientes)} remate(s) por procesar.")

    # Recien aca se toca la API: si no habia nada pendiente, la corrida no
    # gasta ni un centavo. Y si la clave no sirve, se corta ANTES de bajar
    # horas de video en vano.
    motor.verificar_clave()

    procesados_ok = []
    try:
        for v in pendientes:
            fecha = procesar_video(v, registro)
            if fecha:
                procesados_ok.append(fecha)
    finally:
        # se guarda el registro aunque algo falle a mitad de camino
        guardar_procesados(registro)

    if not procesados_ok:
        print("\n· Ningun remate se pudo procesar. El portal queda como estaba.")
        return

    resultado = build_site.build()
    print(f"\n· Portal actualizado. Remates procesados: {', '.join(procesados_ok)}.")
    print(f"  Publicado el del {procesados_ok[-1]}: "
          f"{len(resultado.clasificados)} lotes de {resultado.auditoria.total_entrada} leidos.")


if __name__ == "__main__":
    main()
