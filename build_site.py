#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Arma el portal (index.html) a partir de template.html + data/remate_actual.json.

Uso:
    python build_site.py
"""

import json
import os

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Las 6 categorias del portal, en el orden en que se muestran (Machos / Hembras)
CATS = [
    ("Ternero",           "macho de destete · 150–230 kg"),
    ("Macho de recría",   "torillo / novillo · 220–350 kg"),
    ("Toro / novillo gordo", "terminado · 380+ kg"),
    ("Ternera",           "hembra de destete · 150–230 kg"),
    ("Hembra de recría",  "vaquilla / vaquillona · 240–440 kg"),
    ("Vaca gorda",        "terminada · 330–465 kg"),
]
MACHOS = {"Ternero", "Macho de recría", "Toro / novillo gordo"}
LABEL_CORTO = {
    "Ternero": "Ternero", "Macho de recría": "M. recría",
    "Toro / novillo gordo": "Toro", "Ternera": "Ternera",
    "Hembra de recría": "H. recría", "Vaca gorda": "Vaca gorda",
}

HERE = os.path.dirname(os.path.abspath(__file__))


def fmt_bs(v):
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def fecha_slash(iso):
    y, m, d = iso.split("-")
    return f"{int(d):02d}/{m}/{y}"


def fecha_corta(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MESES[int(m) - 1]} {y}"


def video_url_con_tiempo(base_url, segundos):
    if not base_url:
        return ""
    if segundos in (None, ""):
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}t={int(segundos)}s"


def categoria_stats(lots):
    """Agrupa lotes por categoria_portal y calcula promedio/cantidad."""
    stats = {}
    for nombre, _ in CATS:
        en_cat = [l for l in lots if l.get("categoria_portal") == nombre]
        if en_cat:
            precios = [float(l["precio_bs_kg"]) for l in en_cat]
            stats[nombre] = {
                "precio": round(sum(precios) / len(precios), 2),
                "n_lotes": len(en_cat),
            }
        else:
            stats[nombre] = None
    return stats


def render_cat_cards(stats, grupo_machos):
    out = []
    for nombre, subt in CATS:
        es_macho = nombre in MACHOS
        if es_macho != grupo_machos:
            continue
        s = stats[nombre]
        if s is None:
            out.append(
                f'      <div class="catcard nodata">\n'
                f'        <div class="cn">{nombre}</div>\n'
                f'        <div class="cw">{subt}</div>\n'
                f'        <div class="cp">Sin datos aún</div>\n'
                f'        <div class="cm" style="color:var(--ink-mut)">No apareció en este remate</div>\n'
                f'      </div>'
            )
        else:
            plural = "lotes" if s["n_lotes"] != 1 else "lote"
            out.append(
                f'      <div class="catcard">\n'
                f'        <div class="cn">{nombre}</div>\n'
                f'        <div class="cw">{subt}</div>\n'
                f'        <div class="cp">Bs {fmt_bs(s["precio"])}<small> /kg</small></div>\n'
                f'        <div class="cm">{s["n_lotes"]} {plural} en el remate</div>\n'
                f'      </div>'
            )
    return "\n".join(out)


def render_estimator_options(stats):
    labels = {
        "Ternero": "Ternero (macho)",
        "Macho de recría": "Macho de recría",
        "Toro / novillo gordo": "Toro / novillo gordo",
        "Ternera": "Ternera (hembra)",
        "Hembra de recría": "Hembra de recría (vaquilla)",
        "Vaca gorda": "Vaca gorda",
    }
    out = []
    primero_con_datos = next((n for n, _ in CATS if stats[n]), None)
    for nombre, _ in CATS:
        s = stats[nombre]
        if s is None:
            out.append(f'            <option value="">{labels[nombre]} (sin datos aún)</option>')
        else:
            sel = " selected" if nombre == primero_con_datos else ""
            out.append(f'            <option value="{s["precio"]:.2f}"{sel}>{labels[nombre]}</option>')
    return "\n".join(out)


def render_bars(stats):
    con_datos = [(n, stats[n]["precio"]) for n, _ in CATS if stats[n]]
    con_datos.sort(key=lambda t: -t[1])
    out = []
    for nombre, precio in con_datos:
        out.append(
            f'          <div class="bar-col"><div class="bar-val">{fmt_bs(precio)}</div>'
            f'<div class="bar" data-v="{precio:.2f}"></div><div class="bar-base"></div>'
            f'<div class="bar-lote">{LABEL_CORTO[nombre]}</div></div>'
        )
    return "\n".join(out)


def build():
    with open(os.path.join(HERE, "data", "remate_actual.json"), encoding="utf-8") as f:
        remate = json.load(f)

    lots = remate["lots"]
    fecha_iso = remate["fecha"]
    video_url = remate.get("video_url", "")
    generado_el = remate.get("generado_el", fecha_iso)

    stats = categoria_stats(lots)
    con_datos = [n for n, _ in CATS if stats[n]]
    precios_cat = [stats[n]["precio"] for n in con_datos]

    total_lotes = len(lots)
    total_cabezas = sum(int(l.get("cantidad") or 0) for l in lots)
    lote_max = max(lots, key=lambda l: float(l["precio_bs_kg"]))
    precio_max_desc = f'{lote_max.get("clase", "")} {lote_max.get("raza", "")} · Lote {lote_max.get("lote")}'.strip()

    spread = round(max(precios_cat) - min(precios_cat), 2) if precios_cat else 0
    bar_max = round(max(precios_cat) * 1.15, 2) if precios_cat else 30

    lots_js = []
    for l in lots:
        lots_js.append({
            "lote": l.get("lote"),
            "cat": l.get("clase") or "",
            "raza": l.get("raza") or "",
            "edad": l.get("edad") or "",
            "cab": int(l.get("cantidad") or 0),
            "peso": float(l.get("peso_prom_kg") or 0),
            "pk": float(l.get("precio_bs_kg") or 0),
            "url": video_url_con_tiempo(video_url, l.get("segundo_video")),
        })
    lots_js.sort(key=lambda d: d["lote"] or 0)

    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read()

    reemplazos = {
        "{{FECHA_SLASH}}": fecha_slash(fecha_iso),
        "{{FECHA_CORTA}}": fecha_corta(fecha_iso),
        "{{FECHA_GENERACION}}": fecha_corta(generado_el[:10]) if generado_el else fecha_corta(fecha_iso),
        "{{PRECIO_MAX}}": fmt_bs(float(lote_max["precio_bs_kg"])),
        "{{PRECIO_MAX_DESC}}": precio_max_desc,
        "{{LOTES_VENDIDOS}}": str(total_lotes),
        "{{CATEGORIAS_CON_DATOS}}": str(len(con_datos)),
        "{{CABEZAS_TOTAL}}": str(total_cabezas),
        "{{SPREAD_BS}}": fmt_bs(spread),
        "{{VIDEO_URL}}": video_url or "https://www.youtube.com/@FERCOGANvirtual",
        "{{BAR_MAX}}": f"{bar_max:.2f}",
        "{{LOTS_JSON}}": json.dumps(lots_js, ensure_ascii=False),
        "<!--CATS_MACHOS-->": render_cat_cards(stats, True),
        "<!--CATS_HEMBRAS-->": render_cat_cards(stats, False),
        "<!--EST_OPTIONS-->": render_estimator_options(stats),
        "<!--BARS-->": render_bars(stats),
    }

    for token, valor in reemplazos.items():
        html = html.replace(token, valor)

    out_path = os.path.join(HERE, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"· index.html generado a partir del remate del {fecha_slash(fecha_iso)} "
          f"({total_lotes} lotes, {total_cabezas} cabezas).")


if __name__ == "__main__":
    build()
