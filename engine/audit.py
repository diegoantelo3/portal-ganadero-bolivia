# -*- coding: utf-8 -*-
"""
Registro de auditoria del motor.

Todo lote que se descarta queda asentado con su motivo, y todo conflicto entre
la clase leida y la categoria decidida por peso queda asentado como advertencia
(el lote NO se descarta: manda el peso). La auditoria se serializa a JSON para
poder revisarla despues sin volver a correr el motor.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Descarte:
    """Un lote que no entra al portal, y por que."""
    lote: Any
    motivo: str                 # clave estable, p.ej. "raza_invalida"
    motivo_texto: str           # texto legible para el reporte
    detalle: str = ""
    datos: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Conflicto:
    """La clase leida no coincide con la categoria que dicta el peso.

    Es solo una advertencia: el peso siempre gana. Sirve para detectar lecturas
    dudosas del cartel sin bloquear la publicacion.
    """
    lote: Any
    clase_leida: str
    categoria_asignada: str
    peso_kg: float


@dataclass
class CorreccionPeso:
    """El peso leido no cerraba con la aritmetica del cartel y se recalculo.

    El cartel cumple SUBTOTAL = PESO x PRECIO x (1 + comision), asi que el peso
    puede derivarse de dos lecturas independientes. Cuando el peso leido
    discrepa, gana el derivado y queda constancia de la correccion.
    """
    lote: Any
    peso_leido: float
    peso_corregido: float
    diferencia_kg: float
    subtotal_bs: float
    precio_bs_kg: float


@dataclass
class Auditoria:
    tipo_remate: str = ""
    tipo_remate_detectado: bool = False
    total_entrada: int = 0
    total_clasificados: int = 0
    descartes: List[Descarte] = field(default_factory=list)
    conflictos: List[Conflicto] = field(default_factory=list)
    correcciones_peso: List[CorreccionPeso] = field(default_factory=list)

    # -- registro ----------------------------------------------------------
    def descartar(self, lote, motivo, motivo_texto, detalle="", datos=None) -> None:
        self.descartes.append(Descarte(
            lote=lote, motivo=motivo, motivo_texto=motivo_texto,
            detalle=detalle, datos=datos or {},
        ))

    def conflicto(self, lote, clase_leida, categoria_asignada, peso_kg) -> None:
        self.conflictos.append(Conflicto(
            lote=lote, clase_leida=clase_leida or "",
            categoria_asignada=categoria_asignada, peso_kg=peso_kg,
        ))

    def corregir_peso(self, lote, peso_leido, peso_corregido, subtotal_bs, precio_bs_kg) -> None:
        self.correcciones_peso.append(CorreccionPeso(
            lote=lote, peso_leido=round(peso_leido, 2),
            peso_corregido=round(peso_corregido, 2),
            diferencia_kg=round(peso_corregido - peso_leido, 2),
            subtotal_bs=subtotal_bs, precio_bs_kg=precio_bs_kg,
        ))

    # -- consultas ---------------------------------------------------------
    def resumen_por_motivo(self) -> Dict[str, int]:
        conteo: Dict[str, int] = {}
        for d in self.descartes:
            conteo[d.motivo_texto] = conteo.get(d.motivo_texto, 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: -kv[1]))

    def a_dict(self) -> dict:
        return {
            "tipo_remate": self.tipo_remate,
            "tipo_remate_detectado": self.tipo_remate_detectado,
            "total_entrada": self.total_entrada,
            "total_clasificados": self.total_clasificados,
            "total_descartados": len(self.descartes),
            "resumen_por_motivo": self.resumen_por_motivo(),
            "descartes": [asdict(d) for d in self.descartes],
            "conflictos_clase_vs_peso": [asdict(c) for c in self.conflictos],
            "correcciones_de_peso": [asdict(c) for c in self.correcciones_peso],
        }

    def guardar(self, ruta: str) -> None:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(self.a_dict(), f, ensure_ascii=False, indent=2)

    def imprimir(self, prefijo: str = "  ") -> None:
        etiqueta = "detectado" if self.tipo_remate_detectado else "por defecto"
        print(f"{prefijo}Tipo de remate: {self.tipo_remate} ({etiqueta})")
        print(f"{prefijo}Lotes: {self.total_entrada} leidos -> "
              f"{self.total_clasificados} clasificados, {len(self.descartes)} descartados")
        for motivo, n in self.resumen_por_motivo().items():
            print(f"{prefijo}  - {motivo}: {n}")
        if self.correcciones_peso:
            print(f"{prefijo}  ~ pesos corregidos con la aritmetica del cartel: "
                  f"{len(self.correcciones_peso)} lotes")
        if self.conflictos:
            print(f"{prefijo}  ! clase vs peso en conflicto (gana el peso): "
                  f"{len(self.conflictos)} lotes")
