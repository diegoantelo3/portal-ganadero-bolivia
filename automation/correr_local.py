#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Corre el chequeo del canal y, si el portal cambio, lo publica (git push ->
GitHub Pages republica solo) y VERIFICA que la web muestre lo publicado.

Pensado para el Programador de tareas de Windows: no pide nada por pantalla,
deja todo en data/registro.log y termina con codigo 0 aunque falle, para que
el Programador no lo marque como error y lo reintente en loop.
"""

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "data", "registro.log")
ACTUAL_PATH = os.path.join(ROOT, "data", "remate_actual.json")

sys.path.insert(0, ROOT)


def log(msg):
    linea = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linea)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def asegurar_identidad_git():
    """Sin identidad configurada, `git commit` falla. La fija solo en este repo."""
    code, salida = git("config", "user.email")
    if code != 0 or not salida.strip():
        git("config", "user.name", "Portal Ganadero Bot")
        git("config", "user.email", "diego.antelo3@gmail.com")
        log("Identidad de git configurada en este repositorio.")


URL_PORTAL = "https://diegoantelo3.github.io/portal-ganadero-bolivia/"


def verificar_publicado(fecha_esperada, intentos=6, espera=30):
    """Comprueba que la web sirva de verdad el remate que acabamos de generar.

    POR QUE HACE FALTA
    Del 3 al 7 de agosto de 2026 el portal genero todo bien y subio todo bien,
    pero Netlify se habia quedado sin creditos y descartaba cada deploy en
    silencio: la web mostro datos de cuatro dias atras y nos enteramos de
    casualidad. Publicar sin verificar es no saber si se publico.

    Devuelve True si la fecha aparece en la pagina, False si no. No levanta
    excepciones: un fallo de red aca no debe voltear la corrida, solo avisar.
    """
    import urllib.request

    ddmmyyyy = "/".join(reversed(fecha_esperada.split("-")))   # 2026-08-05 -> 05/08/2026
    for intento in range(1, intentos + 1):
        try:
            pedido = urllib.request.Request(
                URL_PORTAL, headers={"Cache-Control": "no-cache"})
            html = urllib.request.urlopen(pedido, timeout=45).read().decode("utf-8", "ignore")
            if ddmmyyyy in html:
                log(f"Verificado: la web ya muestra el remate del {ddmmyyyy}.")
                return True
        except Exception as e:
            log(f"  (intento {intento}: no se pudo leer la web: {str(e)[:80]})")
        if intento < intentos:
            time.sleep(espera)

    log(f"AVISO: se publico el remate del {ddmmyyyy} pero la web sigue sin mostrarlo "
        f"despues de {intentos * espera // 60} minutos.\n"
        f"  Los datos estan bien y ya subieron a GitHub: no hay que reprocesar nada.\n"
        f"  Lo que falla es el servidor que publica la pagina. Revise {URL_PORTAL}\n"
        f"  y la configuracion de GitHub Pages (Settings -> Pages) del repositorio.")
    return False


def publicar():
    """Si hay cambios en el portal, los sube y verifica que la web los muestre."""
    asegurar_identidad_git()
    code, salida = git("status", "--porcelain")
    if code != 0:
        log(f"ERROR git status: {salida}")
        return
    if not salida.strip():
        log("Sin cambios que publicar.")
        return

    git("add", "-A")
    fecha = datetime.now().strftime("%Y-%m-%d")
    code, salida = git("commit", "-m", f"Actualiza remate ({fecha})")
    if code != 0:
        log(f"ERROR git commit: {salida}")
        return
    code, salida = git("push")
    if code != 0:
        log(f"ERROR git push: {salida}")
        return
    log("Cambios subidos a GitHub. GitHub Pages republica en 1-3 minutos.")

    # Solo tiene sentido verificar si lo que se publico es un remate: cuando el
    # cambio es del registro interno, la pagina no cambia de fecha.
    try:
        with open(ACTUAL_PATH, encoding="utf-8") as f:
            fecha = json.load(f).get("fecha", "")
        if fecha:
            verificar_publicado(fecha)
    except Exception as e:
        log(f"  (no se pudo verificar la publicacion: {str(e)[:80]})")


def repasar_pendientes():
    """Reintenta los carteles que quedaron sin leer del remate publicado.

    Se auto-repara: si una corrida no pudo hacer el repaso (por ejemplo porque
    YouTube estaba limitando los pedidos), la del dia siguiente lo completa.
    Se intenta UNA sola vez por remate, para no gastar creditos releyendo
    lotes que son irrecuperables.
    """
    try:
        import repasar_dudosos
        recuperados = repasar_dudosos.main(solo_una_vez=True)
        if recuperados:
            log(f"Repaso: {recuperados} lotes recuperados con el modelo de respaldo.")
            return True
    except SystemExit as e:
        log(f"Repaso no realizado (se reintenta en la proxima corrida): {e}")
    except Exception:
        log("Repaso fallido (se reintenta en la proxima corrida):\n" + traceback.format_exc())
    return False


def main():
    log("--- Inicio ---")
    try:
        import check_and_update
        from motor_remate import SinCredito
        try:
            check_and_update.main()
        except SinCredito as e:
            # Sin saldo no se publica nada: mejor dejar el portal como estaba
            # que mostrar un remate leido a medias.
            log("SIN SALDO EN LA API — el portal NO se modifico.\n" + str(e))
            log("--- Fin ---")
            return
        repasar_pendientes()
        publicar()
    except SystemExit as e:            # el motor corta con SystemExit al fallar
        log(f"El motor se detuvo: {e}")
        # Aunque el chequeo del canal falle, vale la pena intentar el repaso
        # de lo que ya esta publicado.
        try:
            if repasar_pendientes():
                publicar()
        except Exception:
            log("Repaso fallido:\n" + traceback.format_exc())
    except Exception:
        log("ERROR inesperado:\n" + traceback.format_exc())
    log("--- Fin ---")


if __name__ == "__main__":
    main()
