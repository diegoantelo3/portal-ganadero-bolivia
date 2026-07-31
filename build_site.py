#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Capa de PRESENTACION: arma index.html a partir de template.html.

Esta capa no decide nada de negocio. No conoce categorias, ni rangos de peso,
ni razas, ni reglas de descarte: todo eso lo resuelve `engine/` leyendo
`config/clasificacion.json`. Aca solo se formatea y se inyecta en el HTML.

Uso:
    python build_site.py
"""

import json
import os

from engine import cargar_config, procesar_remate
from engine.stats import resumen_general

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

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


def esc(texto):
    """Escape minimo para inyectar texto en HTML."""
    return (str(texto or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Render (todo se deriva de la configuracion, nada esta hardcodeado aca)
# ---------------------------------------------------------------------------

def render_cat_cards(stats, categorias):
    out = []
    for cat in categorias:
        s = stats.get(cat.id)
        if s is None:
            out.append(
                f'      <div class="catcard nodata">\n'
                f'        <div class="cn">{esc(cat.nombre)}</div>\n'
                f'        <div class="cw">{esc(cat.subtitulo)}</div>\n'
                f'        <div class="cp">Sin datos aún</div>\n'
                f'        <div class="cm" style="color:var(--ink-mut)">No apareció en este remate</div>\n'
                f'      </div>'
            )
        else:
            plural = "lotes" if s["n_lotes"] != 1 else "lote"
            out.append(
                f'      <div class="catcard">\n'
                f'        <div class="cn">{esc(cat.nombre)}</div>\n'
                f'        <div class="cw">{esc(cat.subtitulo)}</div>\n'
                f'        <div class="cp">Bs {fmt_bs(s["precio_bs_kg"])}<small> /kg</small></div>\n'
                f'        <div class="cm">{s["n_lotes"]} {plural} · {s["n_cabezas"]} cabezas</div>\n'
                f'      </div>'
            )
    return "\n".join(out)


def render_estimator_options(stats, categorias):
    out = []
    primero = next((c.id for c in categorias if stats.get(c.id)), None)
    for cat in categorias:
        s = stats.get(cat.id)
        etiqueta = esc(cat.etiqueta_estimador)
        if s is None:
            out.append(f'            <option value="">{etiqueta} (sin datos aún)</option>')
        else:
            sel = " selected" if cat.id == primero else ""
            out.append(
                f'            <option value="{s["precio_bs_kg"]:.2f}"{sel}>{etiqueta}</option>')
    return "\n".join(out)


def render_bars(stats, categorias):
    con_datos = [(c, stats[c.id]) for c in categorias if stats.get(c.id)]
    con_datos.sort(key=lambda t: -t[1]["precio_bs_kg"])
    out = []
    for cat, s in con_datos:
        precio = s["precio_bs_kg"]
        out.append(
            f'          <div class="bar-col"><div class="bar-val">{fmt_bs(precio)}</div>'
            f'<div class="bar" data-v="{precio:.2f}"></div><div class="bar-base"></div>'
            f'<div class="bar-lote">{esc(cat.etiqueta_corta)}</div></div>'
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(guardar_auditoria=True):
    cfg = cargar_config()

    with open(os.path.join(HERE, "data", "remate_actual.json"), encoding="utf-8") as f:
        remate = json.load(f)

    fecha_iso = remate["fecha"]
    video_url = remate.get("video_url", "")
    generado_el = remate.get("generado_el", fecha_iso)
    titulo = remate.get("titulo_video", "")

    # --- El motor hace TODO el trabajo de negocio ---
    resultado = procesar_remate(
        remate["lots"],
        titulo_video=titulo,
        tipo_remate=remate.get("tipo_remate"),   # permite forzarlo desde los datos
        cfg=cfg,
    )
    stats = resultado.stats
    clasificados = resultado.clasificados
    resumen = resumen_general(clasificados)

    if guardar_auditoria:
        ruta = os.path.join(HERE, "data", "auditoria", f"auditoria_{fecha_iso}.json")
        resultado.auditoria.guardar(ruta)

    if not clasificados:
        raise SystemExit(
            "No quedo ningun lote publicable tras aplicar las reglas. "
            "Revisa data/auditoria/ para ver los motivos. No se toca index.html.")

    # Categorias que corresponde mostrar para este tipo de remate
    cats_visibles = cfg.categorias_visibles(resultado.tipo_remate)
    cats_machos = [c for c in cats_visibles if c.sexo == "macho"]
    cats_hembras = [c for c in cats_visibles if c.sexo == "hembra"]

    con_datos = [c for c in cats_visibles if stats.get(c.id)]
    precios_cat = [stats[c.id]["precio_bs_kg"] for c in con_datos]
    spread = round(max(precios_cat) - min(precios_cat), 2) if precios_cat else 0
    bar_max = round(max(precios_cat) * 1.15, 2) if precios_cat else 30

    top = resumen["lote_precio_max"]
    precio_max_desc = f"{top.categoria} {top.raza} · Lote {top.lote}"

    # Tabla de detalle: se muestran los lotes YA CLASIFICADOS
    lots_js = [{
        "lote": lc.lote,
        "cat": lc.categoria,
        "raza": lc.raza,
        "edad": lc.crudo.get("edad") or "",
        "cab": lc.cantidad,
        "peso": lc.peso_kg,
        "pk": lc.precio_bs_kg,
        "url": video_url_con_tiempo(video_url, lc.crudo.get("segundo_video")),
    } for lc in sorted(clasificados, key=lambda l: l.lote or 0)]

    est = cfg.estimador
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read()

    reemplazos = {
        "{{FECHA_SLASH}}": fecha_slash(fecha_iso),
        "{{FECHA_CORTA}}": fecha_corta(fecha_iso),
        "{{FECHA_GENERACION}}": fecha_corta(generado_el[:10]) if generado_el else fecha_corta(fecha_iso),
        "{{PRECIO_MAX}}": fmt_bs(resumen["precio_max"]),
        "{{PRECIO_MAX_DESC}}": esc(precio_max_desc),
        "{{LOTES_VENDIDOS}}": str(resumen["n_lotes"]),
        "{{CATEGORIAS_CON_DATOS}}": str(len(con_datos)),
        "{{CABEZAS_TOTAL}}": str(resumen["n_cabezas"]),
        "{{SPREAD_BS}}": fmt_bs(spread),
        "{{VIDEO_URL}}": esc(video_url or "https://www.youtube.com/@FERCOGANvirtual"),
        "{{BAR_MAX}}": f"{bar_max:.2f}",
        "{{LOTS_JSON}}": json.dumps(lots_js, ensure_ascii=False),
        "{{EST_PESO_MIN}}": f"{est.get('peso_min_kg', 50):.0f}",
        "{{EST_PESO_MAX}}": f"{est.get('peso_max_kg', 900):.0f}",
        "{{EST_PESO_PASO}}": f"{est.get('peso_paso_kg', 10):.0f}",
        "{{EST_PESO_INICIAL}}": f"{est.get('peso_inicial_kg', 300):.0f}",
        "<!--CATS_MACHOS-->": render_cat_cards(stats, cats_machos),
        "<!--CATS_HEMBRAS-->": render_cat_cards(stats, cats_hembras),
        "<!--EST_OPTIONS-->": render_estimator_options(stats, cats_visibles),
        "<!--BARS-->": render_bars(stats, cats_visibles),
    }

    for token, valor in reemplazos.items():
        html = html.replace(token, valor)

    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"· index.html generado — remate del {fecha_slash(fecha_iso)} "
          f"({resumen['n_lotes']} lotes, {resumen['n_cabezas']} cabezas, "
          f"{len(con_datos)}/{len(cats_visibles)} categorias con datos).")
    resultado.auditoria.imprimir(prefijo="  ")
    return resultado


if __name__ == "__main__":
    build()
