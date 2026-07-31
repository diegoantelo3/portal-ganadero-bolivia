# -*- coding: utf-8 -*-
"""
Normalizacion de texto proveniente de OCR / lectura con IA.

Los carteles de remate se leen de un video comprimido, asi que el texto llega
con acentos perdidos, mayusculas mezcladas, plurales, abreviaturas y confusiones
tipicas de OCR (I/l/1 y O/0). Estas funciones son PURAS: no leen archivos, no
imprimen y no dependen de la configuracion salvo por parametro.
"""

import re
import unicodedata
from typing import Iterable, Optional, Tuple

# Confusiones de OCR mas frecuentes en tipografias de cartel.
_CONFUSIONES = str.maketrans({
    "1": "l", "|": "l", "!": "l",
    "0": "o",
    "5": "s",
    "8": "b",
})


def normalizar(texto) -> str:
    """Baja a minusculas, saca acentos, saca todo lo que no sea letra.

    'Nelore SIN PREÑEZ' -> 'nelorensinprenez'... no: los espacios se eliminan,
    quedando 'neloresinprenez', que sigue conteniendo 'nelore'. Eso es lo que
    hace robusta la busqueda por subcadena.
    """
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = s.encode("ascii", "ignore").decode()
    s = s.lower().translate(_CONFUSIONES)
    return re.sub(r"[^a-z]", "", s)


def contiene_alguno(texto, patrones: Iterable[str]) -> bool:
    """True si el texto normalizado contiene alguno de los patrones."""
    n = normalizar(texto)
    if not n:
        return False
    return any(normalizar(p) in n for p in patrones)


def resolver_raza(texto, razas) -> Optional[str]:
    """Devuelve el nombre canonico de la raza aceptada, o None si no es aceptada.

    Acepta cruces: si el texto contiene mas de una raza aceptada, devuelve
    ambas unidas ('Nelore x Brahman'), respetando el orden de aparicion.
    """
    n = normalizar(texto)
    if not n:
        return None
    encontradas = []
    for raza in razas:
        pos = min(
            (n.find(normalizar(p)) for p in raza.patrones if normalizar(p) in n),
            default=-1,
        )
        if pos >= 0:
            encontradas.append((pos, raza.canonica))
    if not encontradas:
        return None
    encontradas.sort()
    vistos, orden = set(), []
    for _, canonica in encontradas:
        if canonica not in vistos:
            vistos.add(canonica)
            orden.append(canonica)
    return " x ".join(orden)


def resolver_sexo(valor, clase, sinonimos) -> Optional[str]:
    """Resuelve el sexo a 'macho' / 'hembra', o None si no se puede determinar.

    Primero mira el campo explicito; si no alcanza, deduce del texto de la clase
    por terminacion ('vaquilla' -> hembra, 'torillo' -> macho). Nunca adivina:
    ante ambiguedad devuelve None y el lote se descarta.
    """
    n = normalizar(valor)
    if n:
        for sexo, palabras in sinonimos.items():
            if any(normalizar(p) == n for p in palabras):
                return sexo

    # Deduccion por la clase: solo terminaciones inequivocas.
    c = normalizar(clase)
    if c:
        hembra = ("vaca", "vacas", "vaquilla", "vaquillas", "vaquillona",
                  "vaquillonas", "ternera", "terneras", "novilla", "novillas")
        macho = ("toro", "toros", "torillo", "torillos", "torete", "toretes",
                 "ternero", "terneros", "novillo", "novillos", "novillito", "novillitos")
        # 'ternera' contiene 'ternero'? no. Pero 'terneros' contiene 'ternero'.
        # Se prueba hembra primero porque 'vaquillona' contiene 'vaquilla' y
        # ninguna palabra de macho es subcadena de una de hembra.
        if any(p in c for p in hembra):
            return "hembra"
        if any(p in c for p in macho):
            return "macho"
    return None


def es_mixto(patrones_mixto: Iterable[str], *textos) -> bool:
    """True si alguno de los textos delata un lote con machos y hembras."""
    return any(contiene_alguno(t, patrones_mixto) for t in textos)


def a_numero(valor) -> Optional[float]:
    """Convierte a float tolerando '', None, coma decimal y separador de miles.

    Devuelve None si no hay un numero utilizable (NO devuelve 0: un peso
    ausente y un peso de 0 kg son cosas distintas para el pipeline).
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor == valor else None  # descarta NaN
    s = str(valor).strip()
    if not s:
        return None
    s = re.sub(r"[^0-9,.\-]", "", s)
    if not s:
        return None
    if "," in s and "." in s:                # 1.234,56 -> 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                           # 362,73 -> 362.73
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v else None


def clase_coincide(clase, esperadas: Iterable[str]) -> bool:
    """Validacion secundaria: la clase leida encaja con lo esperado para la categoria."""
    c = normalizar(clase)
    if not c or not esperadas:
        return True          # sin dato suficiente no se reporta conflicto
    return any(normalizar(e) in c for e in esperadas)


def detectar_tipo_remate(titulo, tipos_remate: dict, por_defecto: str) -> Tuple[str, bool]:
    """Detecta el tipo de remate por palabras clave del titulo.

    Devuelve (tipo, detectado). `detectado` es False cuando se cayo al valor por
    defecto, para que la auditoria lo deje asentado.
    """
    n = normalizar(titulo)
    if n:
        for tipo, datos in tipos_remate.items():
            for patron in datos.get("patrones_titulo", ()):
                if normalizar(patron) and normalizar(patron) in n:
                    return tipo, True
    return por_defecto, False
