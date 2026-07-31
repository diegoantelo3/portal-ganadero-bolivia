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

## Arquitectura

Tres capas, con una sola dirección de dependencia. La lógica de negocio está
aislada: ni el extractor ni la interfaz conocen categorías, pesos ni razas.

```
config/clasificacion.json      ← ÚNICA fuente de verdad
          │
          ▼
    engine/  ────────────────  LÓGICA DE NEGOCIO (sin I/O, testeable)
          │
    ┌─────┴─────┐
    ▼           ▼
motor_remate  build_site  ───  EXTRACCIÓN y PRESENTACIÓN
                  │
                  ▼
            template.html  ──  INTERFAZ (sin reglas adentro)
```

### Para cambiar reglas de negocio, editá SOLO `config/clasificacion.json`

| Querés cambiar… | Editás |
|---|---|
| Categorías, rangos de peso, etiquetas | `categorias[]` |
| Razas aceptadas y tolerancia OCR | `razas_aceptadas[]` |
| Rango de peso válido | `peso` |
| Tipos de remate y su detección | `tipos_remate` |
| Rango del estimador | `estimador` |

No hace falta tocar una sola línea de Python. La configuración se **valida al
arrancar**: si dejás un hueco o un solape entre rangos de peso, el sistema
falla ahí mismo en vez de clasificar mal en silencio.

### Pipeline de clasificación (`engine/pipeline.py`)

Cada lote pasa por: OCR → precio → **peso** → sexo (y lote mixto) → raza →
tipo de remate → **clasificación por peso** → clase como validación secundaria
→ estadística ponderada → auditoría.

**El peso siempre decide.** La clase que viene del cartel no es confiable y
nunca elige categoría: si discrepa del peso, se registra como conflicto en la
auditoría y se publica lo que dice el peso.

### Control de integridad del cartel

El cartel cumple dos identidades exactas:

```
SUBTOTAL = PESO × PRECIO × 1,01        (comisión del 1%)
TOTAL    = SUBTOTAL × CANTIDAD
```

Antes de clasificar, el motor **verifica que el cartel cierre consigo mismo**.
Si no cierra, alguna cifra está mal leída y el lote se descarta con motivo
"Cartel mal leído" — no se intenta adivinar cuál de las tres cifras falló.

Esto es necesario porque la IA confunde dígitos en la tipografía digital roja
del cartel: en el remate del 30/07/2026 leyó **122,50 donde decía 422,50**
(un "4" como "1", −300 kg exactos) en varios lotes. Peor aún, cuando erraba el
peso a veces devolvía un subtotal *consistente con su propio error*, así que el
acuerdo entre peso y subtotal no prueba nada — sólo la coherencia con el total.

Cuando el cartel sí cierra, el peso se **recalcula** desde el subtotal y la
corrección queda registrada. Señal de que el criterio funciona: aplicándolo,
los conflictos clase-vs-peso pasaron de 8 a **0** — cuando el cartel es
coherente, la clase y el peso coinciden solos.

**El precio promedio es ponderado por cabezas**, no simple: un lote de 20
animales pesa 20 veces más que uno de 1 en la referencia.

## Archivos

| Archivo | Qué hace |
|---|---|
| `config/clasificacion.json` | **Única fuente de verdad**: categorías, pesos, razas, remates, etiquetas. |
| `engine/config.py` | Carga y **valida** la configuración (huecos, solapes, sexos). |
| `engine/normalize.py` | Normalización OCR: razas, sexo, números, tipo de remate. |
| `engine/pipeline.py` | Los 11 pasos del pipeline. Clasifica **por peso**. |
| `engine/stats.py` | Promedio **ponderado por cabezas**. |
| `engine/audit.py` | Registro de descartes y conflictos, con motivo. |
| `tests/test_engine.py` | ~90 verificaciones. Correr con `python tests/test_engine.py`. |
| `ACTUALIZAR-PORTAL.bat` | Lo que ejecuta el Programador de tareas. Doble clic para forzar una actualización. |
| `automation/correr_local.py` | Corre el chequeo y publica los cambios (git push). Escribe `data/registro.log`. |
| `automation/check_and_update.py` | Busca el remate nuevo en el canal y dispara el motor. |
| `motor_remate.py` | **Solo extrae**: video → filas crudas. No clasifica ni valida. |
| `build_site.py` | **Solo presenta**: delega en `engine/` y rellena `template.html`. |
| `template.html` | Diseño del portal con marcadores. Sin rangos ni categorías adentro. |
| `data/remate_actual.json` | Datos crudos del remate que se está mostrando. |
| `data/last_processed.json` | Qué video ya se procesó (para no repetirlo). |
| `data/historial/` | Copia en CSV de cada remate procesado. |
| `data/auditoria/` | Por remate: qué se descartó y por qué. |
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
