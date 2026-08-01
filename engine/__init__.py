# -*- coding: utf-8 -*-
"""
Motor de clasificacion y estadistica del Portal Ganadero Bolivia.

Toda la logica de negocio vive aca y toda la configuracion vive en
`config/clasificacion.json`. Ni el extractor (motor_remate.py) ni la capa de
presentacion (build_site.py) deben contener rangos de peso, nombres de
categoria ni reglas de descarte.

Uso tipico:

    from engine import cargar_config, procesar_remate

    resultado = procesar_remate(lots, titulo_video="REMATE COMERCIAL ...")
    resultado.clasificados   # lotes con categoria asignada
    resultado.stats          # promedio ponderado por categoria
    resultado.auditoria      # descartes y conflictos, con motivo
"""

from .config import cargar_config, Config, Categoria           # noqa: F401
from .pipeline import procesar_remate, procesar_lote, Resultado, LoteClasificado  # noqa: F401
from .stats import estadisticas_por_categoria                  # noqa: F401
from .audit import Auditoria, Descarte, Conflicto              # noqa: F401
from .historial import resumen_tendencia, serie_por_categoria  # noqa: F401

__all__ = [
    "cargar_config", "Config", "Categoria",
    "procesar_remate", "procesar_lote", "Resultado", "LoteClasificado",
    "estadisticas_por_categoria",
    "Auditoria", "Descarte", "Conflicto",
    "resumen_tendencia", "serie_por_categoria",
]
