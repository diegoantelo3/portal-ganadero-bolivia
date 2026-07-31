# Portal Ganadero Bolivia — versión automática

Portal con los precios del remate comercial de FERCOGAN, actualizado solo todos los días.

## Cómo funciona

1. Todos los días a las 21:00, el **Programador de tareas de Windows** ejecuta
   `ACTUALIZAR-PORTAL.bat` en la PC de Cindy.
2. El script revisa la pestaña **Streams** del canal `@FERCOGANvirtual` buscando
   el video más nuevo cuyo título contenga **"REMATE COMERCIAL"**.
3. Si es un remate que todavía no se procesó (compara contra
   `data/last_processed.json`), corre `motor_remate.py` sobre ese video: lee
   cada cartel de lote con la IA de visión de Claude y arma la lista de lotes
   vendidos.
4. `build_site.py` toma esos datos (`data/remate_actual.json`) y regenera
   `index.html` a partir de `template.html`.
5. El script hace commit y push a GitHub. Netlify, conectado a este
   repositorio, republica el sitio solo en cuanto detecta el push.

Si no hay remate nuevo ese día, no cambia nada. Todo queda registrado en
`data/registro.log`.

### ¿Por qué corre en la PC y no en la nube?

Se intentó con GitHub Actions y **no funciona**: YouTube le entrega a las IPs de
servidores en la nube una versión recortada del video, sin ningún formato
reproducible (solo miniaturas). Pasa igual con cookies de una cuenta logueada y
con cualquier cliente forzado — es un bloqueo de infraestructura, no algo que el
código pueda esquivar. Desde una conexión hogareña normal el video se descarga
sin problema. El workflow quedó en `.github/workflows/` desactivado, por si
algún día se contrata un proxy residencial (~US$3-15/mes).

**Requisito:** la computadora tiene que estar prendida y con internet a la hora
programada. Si estuvo apagada, la tarea corre en cuanto se enciende.

## Archivos

| Archivo | Qué hace |
|---|---|
| `ACTUALIZAR-PORTAL.bat` | Lo que ejecuta el Programador de tareas. Doble clic para forzar una actualización. |
| `automation/correr_local.py` | Corre el chequeo y publica los cambios (git push). Escribe `data/registro.log`. |
| `automation/check_and_update.py` | Busca el remate nuevo en el canal y dispara el motor. |
| `motor_remate.py` | Lee un video de remate de YouTube y extrae los lotes vendidos (IA de visión). |
| `build_site.py` | Rellena `template.html` con `data/remate_actual.json` y escribe `index.html`. |
| `template.html` | Diseño del portal con marcadores (`{{...}}`, `<!--...-->`) donde va cada dato. |
| `data/remate_actual.json` | Datos del remate que se está mostrando ahora mismo. |
| `data/last_processed.json` | Qué video ya se procesó (para no repetirlo). |
| `data/historial/` | Copia en CSV de cada remate procesado. |
| `data/registro.log` | Qué pasó en cada corrida (no se sube a GitHub). |

## Configuración (una sola vez)

**1. La clave de la API de Claude.** Crear el archivo `Descargas\clave.txt` con
la clave (`sk-ant-...`) adentro. El motor la lee de ahí. Alternativamente, la
variable de entorno `ANTHROPIC_API_KEY`.

**2. La tarea programada.** Ya está creada con el nombre
`Portal Ganadero - Actualizar remate`. Para verla, cambiarla o eliminarla:
abrir **Programador de tareas** (buscarlo en el menú Inicio) → Biblioteca del
Programador de tareas.

## Costo

Cada remate procesado hace ~30-130 llamadas chicas a la API de Claude
(modelo Haiku 4.5: US$1 por millón de tokens de entrada, US$5 de salida).
Costo aproximado: **15-20 centavos de dólar por remate**, o sea unos
**US$4 al mes** si hay remate todos los días hábiles.

## Correrlo a mano

Doble clic en `ACTUALIZAR-PORTAL.bat`, o desde la terminal:

```
python automation/correr_local.py
```

Para procesar un video específico sin pasar por el chequeo del canal:

```
python motor_remate.py "https://www.youtube.com/watch?v=XXXX" --out remate.csv
```

Para probar la detección de lotes sin gastar crédito de la API:

```
python motor_remate.py "<url>" --no-api --out frames/
```
