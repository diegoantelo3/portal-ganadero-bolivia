# Portal Ganadero Bolivia — versión automática

Portal con los precios del remate comercial de FERCOGAN, actualizado solo todos los días.

## Cómo funciona

1. Todos los días a las 09:00 (hora Bolivia), un robot de GitHub Actions
   (`.github/workflows/actualizar-remate.yml`) revisa la pestaña **Streams** del
   canal de YouTube `@FERCOGANvirtual` buscando el video más nuevo cuyo título
   contenga **"REMATE COMERCIAL"**.
2. Si es un remate que todavía no se procesó (compara contra
   `data/last_processed.json`), corre `motor_remate.py` sobre ese video: lee
   cada cartel de lote con la IA de visión de Claude y arma la lista de lotes
   vendidos.
3. `build_site.py` toma esos datos (`data/remate_actual.json`) y regenera
   `index.html` a partir de `template.html`.
4. El robot hace commit y push de los cambios. Netlify, conectado a este
   repositorio, republica el sitio solo en cuanto detecta el push.

Si no hay remate nuevo ese día, el robot no cambia nada.

## Archivos

| Archivo | Qué hace |
|---|---|
| `template.html` | Diseño del portal con marcadores (`{{...}}`, `<!--...-->`) donde va cada dato. |
| `build_site.py` | Rellena el template con `data/remate_actual.json` y escribe `index.html`. |
| `motor_remate.py` | Lee un video de remate de YouTube y extrae los lotes vendidos (IA de visión). |
| `automation/check_and_update.py` | Orquesta todo: busca el video nuevo, corre el motor, regenera el sitio. |
| `data/remate_actual.json` | Datos del remate que se está mostrando ahora mismo. |
| `data/last_processed.json` | Qué video ya se procesó (para no repetirlo). |
| `data/historial/` | Copia en CSV de cada remate procesado. |
| `.github/workflows/actualizar-remate.yml` | El robot: cuándo corre y qué pasos ejecuta. |

## Correrlo a mano (para probar o forzar una actualización)

```
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
python automation/check_and_update.py
```

## Configuración necesaria en GitHub (una sola vez)

`Settings → Secrets and variables → Actions → New repository secret`

- Nombre: `ANTHROPIC_API_KEY`
- Valor: tu clave de `console.anthropic.com`

## Costo

Cada remate procesado hace ~30–130 llamadas chicas a la API de Claude
(una por lote candidato). Costo aproximado: centavos de dólar por remate.
Con el chequeo diario, en un mes normal esto es un par de dólares como mucho.

## Publicar en Netlify conectado a este repo

`Site settings → Build & deploy → Link site to Git` → elegir este repositorio.
No hace falta build command ni carpeta de publicación especial: el robot ya
deja `index.html` listo en la raíz.
