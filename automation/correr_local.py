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


def main():
    log("--- Inicio ---")
    try:
        import check_and_update
        check_and_update.main()
        publicar()
    except SystemExit as e:            # el motor corta con SystemExit al fallar
        log(f"El motor se detuvo: {e}")
    except Exception:
        log("ERROR inesperado:\n" + traceback.format_exc())
    log("--- Fin ---")


if __name__ == "__main__":
    main()
