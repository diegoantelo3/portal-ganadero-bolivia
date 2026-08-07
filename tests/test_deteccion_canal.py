# -*- coding: utf-8 -*-
"""
Verifica que se reconozca un remate comercial entre los videos del canal.

    python tests/test_deteccion_canal.py

Los titulos son REALES, tomados del canal de FERCOGAN.
"""

import os
import sys
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "automation"))

from check_and_update import (es_remate, es_reciente, fecha_desde_meta,  # noqa: E402
                              fechas_posibles_del_titulo, separar_por_fecha)

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

print("\n== Ventana: que remates se procesan solos y cuales no ==")


def check_ventana(dias_atras, dias_ventana, esperado):
    """Verifica la ventana para un remate de hace N dias.

    Segun que dia sea hoy, el titulo generado puede ser ambiguo (ej.: "08/07"
    es 8 de julio o 7 de agosto). En ese caso la respuesta correcta NO es fija:
    la decide el desempate por orden de canal. Se verifica entonces que el
    desempate se respete en los dos sentidos, que es el contrato real.
    """
    f = datetime.now() - timedelta(days=dias_atras)
    titulo = "REMATE COMERCIAL FERCOGAN SRL " + f.strftime("%d/%m/%Y")
    hoy = datetime.now()
    lados = {(hoy - x).days <= dias_ventana
             for x in fechas_posibles_del_titulo(titulo)}

    if len(lados) > 1:      # las dos lecturas discrepan: manda el desempate
        ok = (es_reciente(titulo, dias_ventana, True) is True and
              es_reciente(titulo, dias_ventana, False) is False)
        estado = "lo decide el orden del canal"
    else:
        obtenido = es_reciente(titulo, dias_ventana, si_ambiguo=True)
        ok = obtenido == esperado
        estado = "se procesa" if obtenido else "se omite"

    print("  %s remate de hace %3d dia(s), ventana %d -> %s"
          % ("ok  " if ok else "FALLA", dias_atras, dias_ventana, estado))
    if not ok:
        fallos.append("ventana %d/%d" % (dias_atras, dias_ventana))


check_ventana(0, 4, True)      # el de hoy
check_ventana(1, 4, True)      # el de ayer que no se alcanzo a procesar
check_ventana(3, 4, True)      # fin de semana con la maquina apagada
check_ventana(4, 4, True)      # justo en el borde: entra
check_ventana(5, 4, False)     # ya es historial, se trae a mano
check_ventana(30, 4, False)    # el mes pasado
check_ventana(200, 4, False)   # el ano pasado

# Sin fecha en el titulo no se puede decidir: mejor mirarlo que perderlo.
if es_reciente("FERCOGAN SRL COMMERCIAL AUCTION", 4):
    print("  ok   sin fecha en el titulo -> se procesa igual")
else:
    print("  FALLA sin fecha en el titulo -> se omitio")
    fallos.append("sin fecha")

print("\n== Fechas ambiguas: desempata el orden del canal ==")

# El caso que rompia el filtro: mirado un 07/08, un remate del 08/07 leido como
# mes/dia da "07/08" = hoy, y un remate de hace un mes se colaba como nuevo.
# Ahora manda la posicion en el canal, que YouTube ya devuelve ordenada.
NUEVO_AMB = "REMATE COMERCIAL FERCOGAN SRL 05/08/2026"    # 5 ago o 8 may
VIEJO_AMB = "REMATE COMERCIAL FERCOGAN SRL 08/07/2026"    # 8 jul o 7 ago

remates_canal = [
    {"id": "nuevo",     "title": NUEVO_AMB},                 # 0  arriba del ok
    {"id": "procesado", "title": "REMATE COMERCIAL FERCOGAN SRL 30/07/2026"},
    {"id": "viejo",     "title": VIEJO_AMB},                 # 2  abajo del ok
]
registro_canal = {"procesado": {"estado": "ok"}}
faltantes = [v for v in remates_canal if v["id"] != "procesado"]

rec, vie = separar_por_fecha(faltantes, remates_canal, registro_canal, 4)
ids_rec = [v["id"] for v in rec]
ids_vie = [v["id"] for v in vie]


def check_sep(nombre, cond, extra=""):
    print("  %s %s %s" % ("ok  " if cond else "FALLA", nombre, extra))
    if not cond:
        fallos.append(nombre)


check_sep("el ambiguo por ENCIMA del ya procesado -> se procesa",
          ids_rec == ["nuevo"], f"(recientes={ids_rec})")
check_sep("el ambiguo por DEBAJO del ya procesado -> es historial",
          ids_vie == ["viejo"], f"(viejos={ids_vie})")

# Arranque en frio: sin nada procesado no hay con que comparar, pero un remate
# claramente viejo tiene que quedar afuera igual.
rec2, vie2 = separar_por_fecha(
    [{"id": "julio", "title": "REMATE COMERCIAL FERCOGAN SRL 23/07/2026"}],
    [{"id": "julio", "title": "REMATE COMERCIAL FERCOGAN SRL 23/07/2026"}], {}, 4)
check_sep("sin nada procesado, un remate de julio no entra",
          [v["id"] for v in vie2] == ["julio"])

# Y no debe romperse si el titulo no trae fecha.
rec3, _ = separar_por_fecha(
    [{"id": "x", "title": "FERCOGAN SRL COMMERCIAL AUCTION"}],
    [{"id": "x", "title": "FERCOGAN SRL COMMERCIAL AUCTION"}], {}, 4)
check_sep("titulo sin fecha no rompe y se mira", [v["id"] for v in rec3] == ["x"])

print("\n" + "=" * 58)
if fallos:
    print("FALLARON %d:" % len(fallos))
    for f in fallos:
        print("   -", f)
    sys.exit(1)
print("TODAS LAS VERIFICACIONES PASARON")
