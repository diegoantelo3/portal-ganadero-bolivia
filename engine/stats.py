# -*- coding: utf-8 -*-
"""
Estadistica por categoria.

El precio de referencia de una categoria es el promedio PONDERADO POR CANTIDAD
DE ANIMALES, no el promedio simple de los lotes:

    precio = SUMA(precio_lote * cabezas_lote) / SUMA(cabezas_lote)

Un lote de 20 animales debe pesar 20 veces mas que uno de 1 en la referencia
que mira un ganadero. El promedio simple los trata igual y distorsiona el dato.
"""

from typing import Dict, List, Optional


def promedio_ponderado(valores_y_pesos) -> Optional[float]:
    """Promedio ponderado. Devuelve None si no hay peso total (no divide por cero)."""
    numerador = 0.0
    denominador = 0.0
    for valor, peso in valores_y_pesos:
        numerador += float(valor) * float(peso)
        denominador += float(peso)
    if denominador <= 0:
        return None
    return numerador / denominador


def estadisticas_por_categoria(clasificados: List, tipo_remate: str, cfg) -> Dict[str, dict]:
    """Agrega los lotes clasificados en estadisticas por categoria.

    Devuelve un dict indexado por `categoria_id`, con una entrada por cada
    categoria VISIBLE en este tipo de remate (las que no tienen datos quedan en
    None, para que la capa de presentacion pueda mostrarlas como "sin datos").
    """
    por_cat: Dict[str, list] = {}
    for lc in clasificados:
        por_cat.setdefault(lc.categoria_id, []).append(lc)

    stats: Dict[str, dict] = {}
    for cat in cfg.categorias_visibles(tipo_remate):
        lotes = por_cat.get(cat.id, [])
        if not lotes:
            stats[cat.id] = None
            continue

        cabezas = sum(l.cantidad for l in lotes)
        precio = promedio_ponderado((l.precio_bs_kg, l.cantidad) for l in lotes)
        peso_prom = promedio_ponderado((l.peso_kg, l.cantidad) for l in lotes)
        precios = [l.precio_bs_kg for l in lotes]

        stats[cat.id] = {
            "categoria_id": cat.id,
            "nombre": cat.nombre,
            "sexo": cat.sexo,
            "precio_bs_kg": round(precio, 2) if precio is not None else None,
            "precio_min": round(min(precios), 2),
            "precio_max": round(max(precios), 2),
            "peso_promedio_kg": round(peso_prom, 1) if peso_prom is not None else None,
            "n_lotes": len(lotes),
            "n_cabezas": cabezas,
            "lotes": [l.lote for l in lotes],
        }
    return stats


def resumen_general(clasificados: List) -> dict:
    """Totales del remate, para los indicadores de cabecera."""
    if not clasificados:
        return {"n_lotes": 0, "n_cabezas": 0, "precio_max": None,
                "precio_min": None, "lote_precio_max": None}
    top = max(clasificados, key=lambda l: l.precio_bs_kg)
    return {
        "n_lotes": len(clasificados),
        "n_cabezas": sum(l.cantidad for l in clasificados),
        "precio_max": top.precio_bs_kg,
        "precio_min": min(l.precio_bs_kg for l in clasificados),
        "lote_precio_max": top,
    }
