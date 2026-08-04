# -*- coding: utf-8 -*-
"""
Verifica que se reconozca un remate comercial entre los videos del canal.

    python tests/test_deteccion_canal.py

Los titulos son REALES, tomados del canal de FERCOGAN.
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "automation"))

from check_and_update import es_remate, fecha_desde_meta  # noqa: E402

fallos = []


def check(titulo, esperado):
    obtenido = es_remate(titulo)
    ok = obtenido == esperado
    print("  %s %-58s -> %s" % ("ok  " if ok else "FALLA", titulo[:58],
                                "remate" if obtenido else "se ignora"))
    if not ok:
        fallos.append(titulo)


print("\n== SI son remates comerciales (van al portal) ==")
for t in [
    "REMATE COMERCIAL FERCOGAN SRL 30/07/2026",
    "REMATE COMERCIAL FERCOGAN SRL 01/08/2026",
    # El MISMO remate, republicado en ingles dias despues. Este caso rompia
    # la deteccion vieja, que solo buscaba 'remate comercial'.
    "FERCOGAN SRL COMMERCIAL AUCTION 08/01/2026",
    "Fercogan Srl Commercial Auction 08/03/2026",
    "REMATE  COMERCIAL   FERCOGAN SRL 04/08/2026",
]:
    check(t, True)

print("\n== NO son remates comerciales (se ignoran) ==")
for t in [
    "XV REMATE GENETICA SIN FRONTERAS",
    "3ER. REMATE MATRICES PREMIUM",
    "7MO. REMATE PRODUCCIÓN PREMIUM REPRODCTORES",
    "VIRTUAL PRESENTATION OF THE 15TH GENETICS WITHOUT BORDERS AUCTION",
    "PRESENTATION OF THE 3RD PREMIUM DAM AUCTION",
    "1° REMATE REPRODUCTORES PREMIUM  NELORE FUTURO WEEKEND",
    "REMATE VIRTUAL NELORE FUTURO WEEKEND  HEMBRAS ELITE",
    "V Remate Girolando Nacional",
    "LOTE 26 TABARI",
    "8 DONADORAS KDO 5010",
    "",
]:
    check(t, False)

print("\n== La fecha del remate se lee bien en los dos idiomas ==")


def check_fecha(titulo, upload, esperado):
    obtenido = fecha_desde_meta({"title": titulo, "upload_date": upload})
    ok = obtenido == esperado
    print("  %s %-46s -> %s  (esperado %s)"
          % ("ok  " if ok else "FALLA", titulo[:46], obtenido, esperado))
    if not ok:
        fallos.append(titulo + " (fecha)")


# El MISMO remate, en los dos idiomas: 1 de agosto de 2026.
check_fecha("REMATE COMERCIAL FERCOGAN SRL 01/08/2026", "20260801", "2026-08-01")
check_fecha("FERCOGAN SRL COMMERCIAL AUCTION 08/01/2026", "20260801", "2026-08-01")
# Sin ambiguedad posible: 30 no puede ser un mes.
check_fecha("REMATE COMERCIAL FERCOGAN SRL 30/07/2026", "20260730", "2026-07-30")
check_fecha("FERCOGAN SRL COMMERCIAL AUCTION 07/30/2026", "20260730", "2026-07-30")
# Si el titulo no trae fecha, manda la de subida.
check_fecha("FERCOGAN SRL COMMERCIAL AUCTION", "20260803", "2026-08-03")
# Video subido un dia despues del remate: el titulo sigue mandando.
check_fecha("REMATE COMERCIAL FERCOGAN SRL 03/08/2026", "20260804", "2026-08-03")

print("\n" + "=" * 58)
if fallos:
    print("FALLARON %d:" % len(fallos))
    for f in fallos:
        print("   -", f)
    sys.exit(1)
print("TODAS LAS VERIFICACIONES PASARON")
