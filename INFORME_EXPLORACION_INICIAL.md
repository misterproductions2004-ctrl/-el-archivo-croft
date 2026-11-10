# Informe de exploración inicial — Croft Watch

**Fecha de revisión:** 10 de noviembre de 2026  
**Ventana solicitada:** 12 de agosto – 10 de noviembre de 2026 (90 días)

## 1. Qué se hizo realmente

Se inspeccionó el HTML real extraído de los dos archivos RAR. Los dos documentos HTML suministrados son idénticos: SHA-256 `5f8e2e8fd1ed6229dd56f1efad6785a32bbcd92b5934716f083c561044b30298`, tamaño 2.222.321 bytes. Aunque el nombre del fichero dice V26.2, el título interno visible es **El Archivo Croft V26.1 · 30.º aniversario**. Se conservó esa identidad y no se reemplazó la enciclopedia por una plantilla.

Se abrió y cotejó manualmente una selección de páginas oficiales y artículos individuales. El resultado editorial inicial es de **14 entradas precargadas**. Esta selección es una revisión manual con fuentes oficiales; **no es una primera pasada automática del crawler**. El cliente HTTP del entorno no pudo resolver los dominios externos, y no hubo conexión de escritura al repositorio GitHub desde esta sesión. Por ello, `initial_scan_completed` sigue en `false` y el primer rastreo automático de los últimos 90 días queda pendiente de ejecutarse desde GitHub Actions.

## 2. Fuentes oficiales revisadas

| Fuente | Comprobación | Resultado editorial |
|---|---|---|
| Tomb Raider — `tombraider.com` | El portal y su listado individualizan publicaciones de la franquicia y atribuyen las marcas a Crystal Dynamics group of companies. | 3 entradas precargadas; una incidencia de fecha en Raider Records. |
| Crystal Dynamics — `crystaldynamics.com/news-community` | Sección corporativa del desarrollador. | Se revisó; los elementos de Tomb Raider examinados repetían acontecimientos o no aportaban otra publicación reciente independiente. |
| Tomb Raider — `playtombraider.com` | Su página legal dice que Tomb Raider está desarrollado por Crystal Dynamics y publicado por Amazon Game Studios bajo licencia. | 8 entradas precargadas. |
| Aspyr Support — `support.aspyr.com` | Centro de soporte oficial con sección Updates y artículos de notas de versión. | 3 notas de actualización precargadas. |

No se verificó un foro público administrado por los responsables de la franquicia. *Society of Raiders* se clasifica como newsletter/programa comunitario, no como foro.

## 3. Publicaciones precargadas

| Fecha conservada | Publicación | Fuente | Categoría / tipo de fecha |
|---|---|---|---|
| 2026-10-24 | [Tomb Raider Turns 30! Celebrate with Lo-fi Album & Exclusive Art](https://www.tombraider.com/news/community/tomb-raider-turns-30-celebrate-with-lo-fi-album-and-exclusive-art) | Tomb Raider oficial | Otros anuncios · Publicado |
| 2026-10-16 | [Raider Records – Exploring the Tomb Door Puzzle](https://www.tombraider.com/news/community/raider-records-exploring-the-tomb-door-puzzle) | Tomb Raider oficial | Otros anuncios · Publicado; incidencia frente al listado |
| 2026-10-06 | [Tomb Raider I-III Remastered: Challenge Mode Patch 4](https://support.aspyr.com/hc/en-us/articles/49416285853325-Tomb-Raider-I-III-Remastered-Challenge-Mode-Patch-4) | Aspyr Support | Actualizaciones y parches · Actualizado |
| 2026-10-05 | [Meet Larson](https://www.playtombraider.com/en-us/news/articles/meet-larson) | Amazon Game Studios | Personajes y universo · Publicado |
| 2026-09-28 | [Enemies of Egypt](https://www.playtombraider.com/en-us/news/articles/enemies-of-egypt) | Amazon Game Studios | Desarrollo · Publicado |
| 2026-09-21 | [Reimagining Egypt](https://www.playtombraider.com/en-us/news/articles/reimagining-egypt) | Amazon Game Studios | Desarrollo · Publicado |
| 2026-09-14 | [Creatures of Greece](https://www.playtombraider.com/en-us/news/articles/creatures-of-greece) | Amazon Game Studios | Desarrollo · Publicado |
| 2026-09-09 | [Tomb Raider: Legacy of Atlantis Pre-Orders Are Live on Nintendo Switch 2](https://www.playtombraider.com/en-gb/news/articles/switch2-preorders) | Amazon Game Studios | Próximos proyectos · Publicado |
| 2026-09-08 | [Rise of the Tomb Raider - Patch 3 Notes](https://support.aspyr.com/hc/en-us/articles/48743849217165-Rise-of-the-Tomb-Raider-Patch-3-Notes) | Aspyr Support | Actualizaciones y parches · Actualizado |
| 2026-09-07 | [Reimagining Greece](https://www.playtombraider.com/en-gb/news/articles/reimagining-greece) | Amazon Game Studios | Desarrollo · Publicado |
| 2026-09-02 | [Tomb Raider: Legacy of Atlantis at Gamescom 2026](https://www.tombraider.com/news/video-games/tomb-raider-legacy-of-atlantis-at-gamescom-2026) | Tomb Raider oficial | Eventos oficiales · Publicado |
| 2026-08-31 | [Meet Natla](https://www.playtombraider.com/en-us/news/articles/meet-natla) | Amazon Game Studios | Personajes y universo · Publicado |
| 2026-08-20 | [Tomb Raider I-III Remastered: Challenge Mode Patch 3: Community Update](https://support.aspyr.com/hc/en-us/articles/48286884706957-Tomb-Raider-I-III-Remastered-Challenge-Mode-Patch-3-Community-Update) | Aspyr Support | Actualizaciones y parches · Actualizado |
| 2026-08-17 | [Combat Reimagined](https://www.playtombraider.com/en-us/news/articles/combat-reimagined) | Amazon Game Studios | Desarrollo · Publicado |

Se añadieron ocho publicaciones de Amazon Game Studios sobre combate, Natla, Larson, fauna/enemigos y rediseño de Grecia y Egipto. Las tres entradas de Aspyr muestran una fecha de actualización; la interfaz dice **Actualizado**, no “Publicado”.

## 4. Incidencia de fecha — Raider Records

El artículo individual `Raider Records – Exploring the Tomb Door Puzzle` muestra **Oct 16, 2026**. El listado `/news/all` muestra **Oct 23, 2026** para ese mismo enlace. Se conserva **16 de octubre**, porque es el valor mostrado dentro de la página individual, y se registra la discrepancia para revisión. No se ha presentado el dato como resuelto.

Referencias web consultadas: el artículo individual abre con `Oct 16, 2026`【turn177465view0】; el listado oficial muestra `Oct 23, 2026` para el mismo título【turn177465view1】.

## 5. Exclusiones

- [Astonishing Travels: Greece](https://www.playtombraider.com/en-us/news/articles/astonishing-travels-greece), 17 de septiembre: excluido como noticia confirmada porque el propio artículo advierte que sus estándares editoriales son más laxos y que la especulación también forma parte del contenido【turn683376view2】.
- [Puzzles Reimagined](https://www.playtombraider.com/en-us/news/articles/puzzles-reimagined), 3 de agosto: fuera de la ventana, cuyo límite inicial es el 12 de agosto de 2026【turn161328view5】.
- Páginas de listado/categoría: no se publican como artículos.
- Noticias replicadas por Crystal Dynamics: no producen tarjetas adicionales cuando repiten el mismo acontecimiento.

## 6. Índice medido desde el HTML

El índice actual, generado sobre `index.html` después de excluir el propio panel `croft-news`, registra:

| Medición | Resultado |
|---|---:|
| Paneles de pestaña | 20 |
| Elementos `details` | 49 |
| Documentos indexados | 69 |
| Encabezados | 320 |
| Entidades del vocabulario detectadas | 21 |
| Caracteres visibles en el texto de paneles | 146.806 |

El texto de las fichas `details` ya está contenido en el texto de su panel correspondiente; se mantiene separado como documento para facilitar la comparación, no como una suma independiente de contenido original.

## 7. Pruebas e integridad

La integración añade una pestaña y su panel, más estilos aislados, un bloque JSON y un renderizador. No reescribe las fichas originales. Los bloques añadidos están delimitados por marcadores `CROFT_WATCH_*`; la prueba de restauración retira esos bloques y compara el HTML resultante con `ORIGINAL_REFERENCE.html` byte por byte.

Se ejecutaron `python -m py_compile scripts/croft_watch.py` y `python -m unittest discover -s tests -v`: **47 pruebas pasaron, 0 fallaron**. Las pruebas cubren normalización de URL, deduplicación, parches, fecha, reglas de resumen, feeds, sitemaps anidados, política `robots.txt`, redirecciones fuera del host, huellas de actualización de URLs seed, índice, sincronización idempotente, escritura atómica, restauración, workflow, redirecciones entre hosts y una prueba de dos ejecuciones que publica una noticia simulada una sola vez.

También se intentó `python scripts/croft_watch.py --initial --dry-run`. El intento consultó `robots.txt` para los cuatro hosts registrados; los cuatro fallaron con `Temporary failure in name resolution`. Por ello examinó 0 candidatos, publicó 0 entradas y no modificó el HTML ni el estado. El intento confirma el límite de red de esta sesión, no un resultado editorial de “sin novedades”.

## 8. Limitaciones pendientes

1. **Primera pasada automática de 90 días:** pendiente; requiere ejecutar Croft Watch desde el runner de GitHub Actions, donde puede comprobarse el acceso de red real.
2. **Push al repositorio:** no se hizo desde esta sesión. El dominio GitHub no fue resoluble desde el cliente HTTP local y no se dispuso de una conexión de escritura al repositorio.
3. **Resumen de artículos nuevos:** no se usa IA generativa ni traducción externa. Para artículos que no coincidan con reglas deterministas y verificables, el motor crea una entrada en `review_queue.json` en lugar de inventar un resumen en español.
4. **Comparación factual:** el índice usa coincidencia léxica y huellas de contenido, con umbrales conservadores. No es una comprensión semántica perfecta de cada hecho de cada ficha.
5. **Robots / anti-bot:** si el origen bloquea la consulta o `robots.txt` no puede verificarse, se registra como inaccesible; no se eluden protecciones.

`data/croft_watch_state.json` permanece con `initial_scan_completed: false`. Esto es deliberado: precargar 14 entradas manualmente no equivale a afirmar que el rastreo automático ya cubrió toda la ventana.
