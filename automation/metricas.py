#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Reporte de metricas de CALIDAD DE DATOS del portal.

Responde: cuantos lotes se leen, cuantos se publican, por que se descarta el
resto, y como viene evolucionando eso remate a remate.

    python automation/metricas.py

(Esto NO son visitas al sitio; para eso hace falta un servicio de analitica.
Ver README, seccion "Metricas".)
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine import cargar_config, procesar_remate           # noqa: E402
from engine.historial import leer_csv, remates_disponibles  # noqa: E402

DIR_HIST = os.path.join(ROOT, "data", "historial")


def barra(pct, ancho=24):
    lleno = int(round(pct / 100 * ancho))
    return "█" * lleno + "·" * (ancho - lleno)


def main():
    cfg = cargar_config()
    fechas = remates_disponibles(DIR_HIST)
    if not fechas:
        print("Todavia no hay remates en data/historial/.")
        return

    print("=" * 68)
    print("  PORTAL GANADERO BOLIVIA — calidad de datos")
    print("=" * 68)
    print(f"\nRemates registrados: {len(fechas)}  ({fechas[0]} a {fechas[-1]})")
    print(f"Lectura: {cfg.modelo_lectura}")
    print(f"Repaso : {cfg.modelo_repaso}" + ("" if cfg.repaso_activo else "  (desactivado)"))

    tot_leidos = tot_pub = 0
    motivos_global = {}

    for fecha in fechas:
        lots = leer_csv(os.path.join(DIR_HIST, f"remate_{fecha}.csv"))
        r = procesar_remate(lots, titulo_video="", cfg=cfg)
        leidos = r.auditoria.total_entrada
        pub = len(r.clasificados)
        conf = len(r.auditoria.conflictos)
        pct = pub / leidos * 100 if leidos else 0
        tot_leidos += leidos
        tot_pub += pub
        for m, n in r.auditoria.resumen_por_motivo().items():
            motivos_global[m] = motivos_global.get(m, 0) + n

        print(f"\n── Remate {fecha} " + "─" * 44)
        print(f"   leidos {leidos:3d}  →  publicados {pub:3d}   {barra(pct)} {pct:.0f}%")
        print(f"   cabezas publicadas : {sum(l.cantidad for l in r.clasificados)}")
        print(f"   categorias con datos: {sum(1 for s in r.stats.values() if s)}"
              f" de {len(r.stats)}")
        print(f"   pesos corregidos    : {len(r.auditoria.correcciones_peso)}")
        print(f"   conflictos clase/peso: {conf}"
              f"   → publicados sin alarma: {pub - conf} de {pub}")
        if r.auditoria.descartes:
            print("   descartes:")
            for m, n in r.auditoria.resumen_por_motivo().items():
                print(f"      - {m}: {n}")

    print("\n" + "=" * 68)
    print("  ACUMULADO")
    print("=" * 68)
    pct = tot_pub / tot_leidos * 100 if tot_leidos else 0
    print(f"  Lotes leidos     : {tot_leidos}")
    print(f"  Lotes publicados : {tot_pub}   {barra(pct)} {pct:.0f}%")
    print("  Motivos de descarte:")
    for m, n in sorted(motivos_global.items(), key=lambda kv: -kv[1]):
        print(f"     - {m}: {n}")
    print("\n  Los descartes por raza NO son errores de lectura: son la regla")
    print("  de negocio (solo Nelore y Brahman). Los demas motivos si indican")
    print("  carteles que no se pudieron leer con garantia.")


if __name__ == "__main__":
    main()
