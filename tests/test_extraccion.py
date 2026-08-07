# -*- coding: utf-8 -*-
"""
Verificacion del EXTRACTOR (seleccion de fotogramas).

    python tests/test_extraccion.py

No toca YouTube ni la API: simula la secuencia de fotogramas de un remate.
"""

import os
import sys
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import motor_remate as motor  # noqa: E402

ALTO, ANCHO = 360, 640
fallos = []


def check(nombre, condicion, extra=""):
    print(f"  {'ok  ' if condicion else 'FALLA'} {nombre} {extra}")
    if not condicion:
        fallos.append(nombre)


def frame_de(lote_id, nitidez):
    """Frame sintetico: la barra inferior identifica el lote, la celda da la nitidez."""
    f = np.zeros((ALTO, ANCHO, 3), dtype=np.uint8)
    f[int(ALTO * 0.80):int(ALTO * 0.99), :] = (lote_id % 7) * 30
    celda = f[int(ALTO * 0.82):int(ALTO * 0.90), int(ANCHO * 0.02):int(ANCHO * 0.16)]
    rng = np.random.default_rng(nitidez)
    celda[:] = rng.normal(128, np.sqrt(nitidez), celda.shape).clip(0, 255).astype(np.uint8)
    return f


def correr(secuencia, min_fill=120):
    """secuencia: [(segundo, lote_id, nitidez), ...] -> grupos detectados."""
    por_t = {t: frame_de(l, n) for t, l, n in secuencia}

    class CapFalso:
        def __init__(self):
            self.t = 0
        def isOpened(self):
            return True
        def set(self, _p, ms):
            self.t = int(round(ms / 1000))
        def read(self):
            f = por_t.get(self.t)
            return (f is not None), f
        def release(self):
            pass

    ini, fin = secuencia[0][0], secuencia[-1][0]
    paso = secuencia[1][0] - secuencia[0][0]
    with mock.patch.object(motor.cv2, "VideoCapture", lambda _u: CapFalso()):
        return motor.detect_lot_frames("x", ini, fin, paso, min_fill=min_fill)


print("\n== Se elige el ULTIMO fotograma de cada lote (precio de cierre) ==")
# Secuencia real medida en el video para el lote 461: el precio sube durante
# la puja (0 -> 27,00 -> 28,50 -> 29,00 -> 29,10) y el cartel no marca cuando
# cierra. Quedarse con el mas nitido (t=11135) daba un precio del MEDIO de la
# puja; hay que quedarse con el ultimo (t=11235).
SEC = [
    (11110, 461, 200), (11135, 461, 900), (11160, 461, 300),
    (11185, 461, 850), (11210, 461, 250), (11235, 461, 400),
    (11260, 469, 500), (11285, 469, 700),
]
grupos = correr(SEC)
elegidos = sorted(g["t"] for g in grupos)
check("un fotograma por lote", len(grupos) == 2, f"(dio {len(grupos)})")
check("lote 461 -> el ultimo (t=11235)", 11235 in elegidos, f"(dio {elegidos})")
check("lote 469 -> el ultimo (t=11285)", 11285 in elegidos, f"(dio {elegidos})")
check("ya NO se elige el mas nitido del medio de la puja (t=11135)",
      11135 not in elegidos)

print("\n== Los fotogramas ilegibles no arrastran al grupo ==")
# Si el ultimo fotograma del lote es ilegible (transicion, pantalla en negro),
# se retiene el ultimo que SI se podia leer, no se pierde el lote.
SEC2 = [(100, 501, 800), (125, 501, 900), (150, 501, 60)]
grupos2 = correr(SEC2, min_fill=200)
tiempos2 = sorted(g["t"] for g in grupos2)
check("se retiene el ultimo LEGIBLE (t=125), no el ilegible (t=150)",
      tiempos2 == [125], f"(dio {tiempos2})")

print("\n== Se descartan las pantallas sin lote (publicidad, logo) ==")
SEC3 = [(0, 601, 10), (25, 601, 12), (50, 602, 800), (75, 602, 900)]
grupos3 = correr(SEC3, min_fill=200)
check("solo queda el lote con contenido legible", len(grupos3) == 1,
      f"(dio {len(grupos3)})")

print("\n== Falta de saldo: se corta, no se publican datos a medias ==")
ERRORES_DE_SALDO = [
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API.'}}",
    "authentication_error: invalid x-api-key",
]
for e in ERRORES_DE_SALDO:
    check(f"detecta como falta de saldo: {e[:46]}...",
          motor._es_falta_de_credito(Exception(e)))

for e in ["Connection error", "overloaded_error", "la respuesta no trae JSON"]:
    check(f"NO confunde con falta de saldo: {e!r}",
          not motor._es_falta_de_credito(Exception(e)))


class ClienteSinSaldo:
    class messages:
        @staticmethod
        def create(**_kw):
            raise Exception(
                "Error code: 400 - {'error': {'message': "
                "'Your credit balance is too low to access the Anthropic API.'}}")


try:
    motor.read_lot_with_claude(b"x", ClienteSinSaldo(), "claude-opus-5")
    check("read_lot_with_claude corta con SinCredito", False, "(no lanzo nada)")
except motor.SinCredito:
    check("read_lot_with_claude corta con SinCredito", True)
except Exception as e:
    check("read_lot_with_claude corta con SinCredito", False, f"(lanzo {type(e).__name__})")


# --------------------------------------------------------------------------
# La clave se comprueba ANTES de bajar el video
# --------------------------------------------------------------------------
print("\n== verificar_clave() corta antes de tocar el video ==")


class ClienteClaveInvalida:
    """Lo que devolvio la API entre el 3 y el 7 de agosto."""
    class messages:
        @staticmethod
        def create(**_kw):
            raise Exception(
                "Error code: 401 - {'type': 'error', 'error': {'type': "
                "'authentication_error', 'message': 'API key is invalid.'}}")


class ClienteSano:
    class messages:
        @staticmethod
        def create(**_kw):
            return object()


try:
    motor.verificar_clave(ClienteClaveInvalida())
    check("clave invalida -> SinCredito", False, "(no lanzo nada)")
except motor.SinCredito:
    check("clave invalida -> SinCredito", True)
except Exception as e:
    check("clave invalida -> SinCredito", False, f"(lanzo {type(e).__name__})")

try:
    motor.verificar_clave(ClienteSinSaldo())
    check("sin saldo -> SinCredito", False, "(no lanzo nada)")
except motor.SinCredito:
    check("sin saldo -> SinCredito", True)
except Exception as e:
    check("sin saldo -> SinCredito", False, f"(lanzo {type(e).__name__})")

check("clave valida -> devuelve el cliente",
      motor.verificar_clave(ClienteSano()) is not None)


class ClienteCaido:
    """Un error que NO es de credencial no debe disfrazarse de SinCredito."""
    class messages:
        @staticmethod
        def create(**_kw):
            raise Exception("Error code: 529 - overloaded_error")


try:
    motor.verificar_clave(ClienteCaido())
    check("error ajeno no se confunde con SinCredito", False, "(no lanzo nada)")
except motor.SinCredito:
    check("error ajeno no se confunde con SinCredito", False, "(lanzo SinCredito)")
except Exception:
    check("error ajeno no se confunde con SinCredito", True)

print("\n" + "=" * 58)
if fallos:
    print(f"FALLARON {len(fallos)} verificaciones:")
    for f in fallos:
        print("   -", f)
    sys.exit(1)
print("TODAS LAS VERIFICACIONES PASARON")
