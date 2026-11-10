# Croft Watch — El Archivo Croft

Sistema de vigilancia editorial especializado en Tomb Raider, preparado para ejecutarse en GitHub Actions y alimentar la pestaña **ÚLTIMAS NOTICIAS** de la enciclopedia.

> **Estado honesto de esta entrega:** la integración local, los archivos de datos, el motor, el workflow y las pruebas están incluidos. La selección inicial de 14 entradas fue una revisión editorial manual de publicaciones oficiales. **No se ha podido ejecutar aquí el primer rastreo automático de 90 días ni hacer push a GitHub**: el entorno de ejecución no pudo resolver los dominios externos y no hay una conexión de escritura al repositorio disponible en esta sesión. La primera ejecución real del workflow deberá confirmar accesibilidad, `robots.txt`, feeds/sitemaps y candidatos desde el runner de GitHub.

## 1. Qué incluye

```text
index.html
El_Archivo_Croft_V26.2_ENCICLOPEDIA_AMPLIADA.html
ORIGINAL_REFERENCE.html
scripts/
  __init__.py
  croft_watch.py
data/
  sources.json
  latest_news.json
  croft_watch_state.json
  detection_history.jsonl
  archivo_croft_index.json
  initial_scan_report.json
  review_queue.json
  logs/.gitkeep
  backups/.gitkeep
.github/workflows/croft-watch.yml
requirements.txt
tests/test_croft_watch.py
README_CROFT_WATCH.md
INFORME_EXPLORACION_INICIAL.md
```

- `index.html` y el HTML versionado son copias idénticas de la enciclopedia integrada.
- `ORIGINAL_REFERENCE.html` es la referencia íntegra anterior a la integración y se usa en una prueba que verifica la restauración byte por byte.
- `scripts/croft_watch.py` contiene normalización de URL, consulta respetuosa, bloqueo de redirecciones fuera del host oficial, lectura de HTML/feeds/sitemaps (incluidos sitemaps hijos), extracción, clasificación, deduplicación, comparación con el índice, cola de revisión y publicación atómica y rechazo de redirecciones fuera del host oficial.
- `data/sources.json` contiene el registro de las fuentes y sus pruebas de oficialidad.
- `data/latest_news.json` es el registro estructurado que alimenta la interfaz.
- `data/croft_watch_state.json` guarda el punto de control y caché HTTP. `initial_scan_completed` permanece en `false` hasta que una primera pasada automática termine con las fuentes verificadas accesibles.
- `data/detection_history.jsonl` contiene las 14 entradas iniciales, más exclusiones y la incidencia de fecha de Raider Records.
- `data/archivo_croft_index.json` indexa el HTML original sin incluir el panel de Croft Watch.
- `data/review_queue.json` registra material oficial que no debe publicarse automáticamente por falta de resumen fiel o por su carácter especulativo.

## 2. Estado real de la enciclopedia de referencia

Los dos HTML extraídos de los archivos RAR suministrados son idénticos. El nombre externo dice V26.2, pero el título interno de la página suministrada se identifica como **El Archivo Croft V26.1 · 30.º aniversario**. Se conserva el contenido y el título interno de la fuente; no se renombra editorialmente ni se reconstruye la enciclopedia.

El índice se generó desde el HTML real y obtuvo:

| Medición | Resultado |
|---|---:|
| Paneles de pestaña indexados | 20 |
| Elementos `details` indexados | 49 |
| Documentos de índice (paneles + fichas) | 69 |
| Encabezados | 320 |
| Entidades del vocabulario detectadas | 21 |
| Caracteres visibles en texto de paneles | 146.806 |

El texto de cada panel y el texto de las fichas `details` se conservan como documentos del índice. Los documentos de fichas están contenidos también en su panel principal; por eso no deben sumarse como texto único adicional.

La integración añade cinco bloques delimitados por comentarios `CROFT_WATCH_*`: estilos, botón de pestaña, panel, JSON de noticias y renderizador. La prueba de restauración quita exclusivamente esos bloques y compara el resultado con `ORIGINAL_REFERENCE.html`; el contenido base debe coincidir byte por byte.

## 3. Fuentes registradas

| Fuente | Responsable / relación | Verificación |
|---|---|---|
| `tombraider.com` | Portal oficial de Tomb Raider; atribución legal a Crystal Dynamics group of companies | Verificada |
| `crystaldynamics.com/news-community` | Sitio corporativo oficial del desarrollador | Verificada |
| `playtombraider.com` | Sitio oficial del proyecto; su aviso legal atribuye el desarrollo a Crystal Dynamics y la publicación bajo licencia a Amazon Game Studios | Verificada |
| `support.aspyr.com` | Centro de soporte oficial de Aspyr | Verificada |

Las fuentes no se consideran oficiales por usar el nombre de Tomb Raider: el registro guarda organización, host permitido, URL de evidencia, tipo, método de consulta y patrones de ruta de artículos.

**Foros:** no se ha verificado un foro público administrado por los responsables de la franquicia. *Society of Raiders* se trata como newsletter/programa comunitario, no como foro oficial.

## 4. Selección editorial inicial

El archivo `data/latest_news.json` contiene 14 publicaciones seleccionadas manualmente en la ventana del 12 de agosto al 10 de noviembre de 2026. Es una precarga editorial revisada, no el resultado de una ejecución integral del crawler.

Se rechazó *Astonishing Travels: Greece* como noticia confirmada porque el propio artículo admite un estándar editorial más laxo y especulación. *Puzzles Reimagined* queda fuera de la ventana porque es del 3 de agosto de 2026. Las páginas de categoría no se consideran artículos.

### Incidencia de fecha: Raider Records

La página individual de **Raider Records – Exploring the Tomb Door Puzzle** muestra `Oct 16, 2026`, mientras que el índice oficial `/news/all` muestra `Oct 23, 2026`. La tarjeta conserva la fecha de la página individual (**16 de octubre**) y la incidencia guarda ambos valores. El motor no debe fingir que la discrepancia está resuelta ni cambiar esa fecha silenciosamente.

Los parches de Aspyr se marcan como **Actualizado**, porque el centro de soporte muestra esa etiqueta en vez de una fecha de publicación original. No se convierten las fechas de actualización en fechas de publicación.

El detalle de cada entrada, las URL, las exclusiones y las limitaciones está en `INFORME_EXPLORACION_INICIAL.md` y `data/initial_scan_report.json`.

## 5. Cómo decide publicar

1. Consulta solo fuentes con `official_status: verified` y host incluido en el registro.
2. Revisa `robots.txt`; aplica una pausa de una petición por host por segundo y un límite de tamaño/tiempo.
3. Descubre artículos desde los listados oficiales y, si existen, RSS/Atom/sitemaps.
4. Ignora páginas de categoría y URLs que no encajen con patrones de artículo de la fuente.
5. Extrae fecha, título, autor, descripción, imagen, texto y enlaces relacionados.
6. Exige una referencia inequívoca a Tomb Raider / Lara Croft o a un título de franquicia reconocido; topónimos aislados no bastan.
7. Compara URL canónica, título, huellas SHA-256 y grupos de palabras hasheadas, y contrasta el texto con el índice de la enciclopedia. La primera revisión de una URL seed registra su huella sin republicarla; las siguientes pueden detectar una actualización material.
8. Distingue las versiones de parches: Patch 3 no se confunde con Patch 4.
9. Solo publica cuando existe una regla de resumen en español que el programa puede aplicar sin inventar. Los demás artículos oficiales pasan a `review_queue.json`.
10. Solo modifica el JSON de noticias embebido y las tarjetas si hay una entrada nueva aceptada. Hace copia de seguridad del HTML y escribe mediante reemplazo atómico.

El sistema conserva los artículos históricos. Un cambio pequeño de publicidad/formato no debería generar una nueva tarjeta. Una modificación sustancial del mismo artículo puede volver a pasar por los filtros como versión nueva; el identificador resultante depende de URL, fecha y huella del contenido.

## 6. Límite editorial importante

El motor **no usa una API de IA ni una traducción generativa**. Tiene reglas de síntesis deterministas para formatos conocidos (por ejemplo, notas de parches y reservas de *Legacy of Atlantis*) y reglas explícitas para dos publicaciones precargadas. Los nuevos diarios de desarrollo, entrevistas o artículos no reconocidos se guardan en revisión en vez de recibir un resumen inventado o una traducción atribuida de manera opaca.

La comparación con el índice es léxica y conservadora (n-gramas y umbrales de similitud), no una comprensión semántica perfecta de cada hecho. Puede detectar duplicados textuales y contenido muy parecido; no puede garantizar por sí sola que cada dato factual esté ya documentado en una ficha. Esta limitación se deja visible deliberadamente para no presentar el sistema como más inteligente de lo que es.

Si una web bloquea la extracción, requiere JavaScript no disponible o no permite comprobar `robots.txt`, queda registrada como inaccesible. Croft Watch no intenta saltarse autenticación ni protecciones anti-bot.

## 7. Instalación en tu repositorio

Repositorio indicado: `https://github.com/misterproductions2004-ctrl/-el-archivo-croft`  
Rama indicada: `main`

1. Descarga y descomprime el paquete ZIP.
2. En tu clon local del repositorio, copia el contenido del paquete a la raíz, manteniendo las rutas `scripts/`, `data/`, `tests/` y `.github/workflows/`. No reemplaces carpetas o archivos ajenos al paquete que ya existan en tu repositorio.
3. Comprueba que `index.html` y `El_Archivo_Croft_V26.2_ENCICLOPEDIA_AMPLIADA.html` están presentes.
4. Sube los cambios a `main` con GitHub Desktop o Git.
5. En GitHub, abre **Actions → Croft Watch** y ejecuta **Run workflow**. En la primera ejecución deja `initial_scan` sin marcar: el motor detecta que el escaneo inicial sigue pendiente y solicita la ventana de 90 días. Marca esa opción solo para forzar otra exploración histórica.
6. En **Settings → Actions → General**, comprueba que las acciones pueden escribir en el repositorio. El workflow declara `permissions: contents: write`.

### Instalación y pruebas locales en Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\croft_watch.py --index-only
python -m unittest discover -s tests -v
```

Para probar una exploración con red sin publicar archivos ni cambiar el estado:

```powershell
python scripts\croft_watch.py --initial --dry-run
```

## 8. Programación y publicación

- El workflow se programa diariamente a las **05:17 UTC**. GitHub Actions usa UTC, por lo que no se debe interpretar como una hora local fija durante todo el año.
- También se puede ejecutar manualmente.
- No es detección instantánea: son revisiones periódicas.
- El workflow solo crea un commit si el motor comunica que hay noticias nuevas y los archivos preparados tienen cambios reales. Una ejecución sin novedades no crea commit vacío.
- El estado incremental, historial operativo y cola de revisión se conservan mediante caché de Actions. Las tarjetas ya publicadas permanecen registradas en `latest_news.json`.

## 9. Pruebas

Ejecutar desde la raíz del paquete:

```bash
python -m py_compile scripts/croft_watch.py
python -m unittest discover -s tests -v
```

La ejecución final local completó **47 pruebas y todas pasaron**. Comprueban normalización de URL, versiones de parches, pertinencia Tomb Raider, categorías, fuentes verificadas, deduplicación, actualización material de URL seed, comparación con el índice, fechas, reglas de resumen, RSS/Atom, sitemaps anidados, `robots.txt`, redirecciones de dominio, exclusión del panel propio, 14 registros, historial seed, sincronización idempotente, escritura atómica, restauración exacta del HTML, igualdad de las dos copias, protección contra commits vacíos y una prueba de integración de dos ejecuciones: primera publicación y descarte idempotente en la segunda.

También se ejecutó `python scripts/croft_watch.py --initial --dry-run`: fue un intento real sin escritura. Las cuatro fuentes dieron error DNS al consultar `robots.txt`, no se descubrieron candidatos y el HTML no cambió. El informe registra el error exacto. **No se afirma que el primer rastreo real de GitHub Actions haya terminado.**
