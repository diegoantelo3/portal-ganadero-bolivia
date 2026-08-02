#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Corre el chequeo del canal y, si el portal cambio, lo publica (git push ->
Netlify republica solo).

Pensado para el Programador de tareas de Windows: no pide nada por pantalla,
deja todo en data/registro.log y termina con codigo 0 aunque falle, para que
el Programador no lo marque como error y lo reintente en loop.
"""

import os
import subprocess
import sys
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "data", "registro.log")

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


def publicar():
    """Si hay cambios en el portal, los sube. Netlify republica solo."""
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
    log("Cambios publicados. Netlify republica en ~1 minuto.")


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
