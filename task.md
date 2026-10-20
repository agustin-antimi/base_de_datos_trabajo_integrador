# TASK.md — Plan de Trabajo, Estado de Avance y Auditoría Técnica

> **Materia:** Base de Datos — Licenciatura en Ciencia de Datos en Organizaciones  
> **Institución:** Facultad de Informática / Ciencias Económicas — Universidad Nacional de La Plata (UNLP 2026)  
> **Proyecto:** Sistema de Venta de Entradas y Recomendación de Eventos (Persistencia Políglota)  
> **Referencia Principal:** [CONSIGNAS.md](CONSIGNAS.md) · **Directrices:** [AGENTS.md](AGENTS.md) · **Arquitectura:** [module_overview.md](module_overview.md)  
> **Última actualización:** 19 de Octubre de 2026  

---

## 📋 1. Tablero General de Estado de Avance

| Sección / Requerimiento Oficial | Módulo Principal en `src/` | Estado en Código | Estado en Notebook | Descripción y Cumplimiento |
| :--- | :--- | :---: | :---: | :--- |
| **Requisitos Técnicos: Limpieza** | [`src/functions.py`](src/functions.py) | `[x] Completo` | `[x] Integrado` | Limpieza idempotente (`clean_db`) de MongoDB, Neo4j y Redis. |
| **Requisitos Técnicos: Índices** | [`src/functions.py`](src/functions.py) | `[x] Completo` | `[x] Integrado` | Índices únicos en MongoDB y restricciones `IS UNIQUE` en Neo4j. |
| **Requisitos Técnicos: Cero Duplicación** | [`src/functions.py`](src/functions.py) | `[x] Completo` | `[x] Integrado` | Desasociación de listas relacionales en MongoDB (`$unset`). |
| **1. Carga Inicial y Distribución** | [`src/functions.py`](src/functions.py) | `[x] Completo` | `[x] Integrado` | Pipeline ETL completo: Mongo $\rightarrow$ Neo4j $\rightarrow$ Sanitización $\rightarrow$ Redis. |
| **2. Flujo de Compra y Transacciones** | [`src/purchase.py`](src/purchase.py) | `[x] Completo` | `[x] Integrado` | Sesiones (30m), reservas (10m), confirmación atómica y 3 casos de prueba. |
| **3. Consultas Políglotas (12)** | [`src/queries.py`](src/queries.py) | `[x] Completo` | `[x] Integrado` | 12 consultas con nombres, filtros temporales y ordenamientos correctos. |
| **4. Estadísticas y Gráficos** | [`src/analytics.py`](src/analytics.py) | `[x] Completo` | `[x] Integrado` | Lógica estadística y visualizaciones Matplotlib integradas en el notebook. |
| **5. Modificaciones Multibase** | [`src/modifications.py`](src/modifications.py) | `[x] Completo` | `[x] Integrado` | Mutaciones 5.1 a 5.5 listas con evidencias; volcadas al notebook con ejecuciones. |
| **6. Informe Conceptual** | `notebooks/TP_Integrador.ipynb` | `[x] Completo` | `[x] Integrado` | Justificaciones de diseño, consistencia, TTL y respuestas teóricas obligatorias redactadas en el notebook. |
| **Anexo 1: Reseñas de Eventos** | [`src/appendix.py`](src/appendix.py) | `[x] Completo` | `[x] Integrado` | Calificación (1-5), comentario, validación de compra confirmada y unicidad; 6 reseñas y promedios por evento y artista. |
| **Anexo 2: Historial de Precios** | [`src/appendix.py`](src/appendix.py) | `[x] Completo` | `[x] Integrado` | Registro temporal con fecha, 3 cambios sobre un evento, consulta a fecha dada y gráfico de evolución con Matplotlib. |
| **Anexo 3: Recomendación de Dos Saltos** | [`src/appendix.py`](src/appendix.py) | `[x] Completo` | `[x] Integrado` | Recomendación en 2 saltos (`amigos` $\rightarrow$ `siguen` $\rightarrow$ `similares`), exclusiones de seguidos/comprados, probado con Sofía Martínez. |
| **Anexo 4: Historial de Búsquedas por Usuario** | [`src/appendix.py`](src/appendix.py) / Redis | `[x] Completo` | `[x] Integrado` | Registro de últimas 5 búsquedas en Redis (listas con `LPUSH` + `LTRIM`) y reordenamiento de recomendaciones por género coincidente. |
| **Anexo: Justificaciones en Informe** | `notebooks/TP_Integrador.ipynb` | `[x] Completo` | `[x] Integrado` | Justificación técnica de las bases y estructuras seleccionadas para los 4 requerimientos del Anexo en Sección 6.4. |

---

## 🎯 2. Plan de Trabajo en Visión General (Fases de Ejecución)

El plan de trabajo estructura las tareas pendientes en fases secuenciales orientadas a cumplir la totalidad de las consignas antes de la fecha límite de entrega (23/10/2026).

```mermaid
graph LR
    F1[Fase 1: Módulos de Apoyo\nqueries.py y analytics.py] --> F2[Fase 2: Sección 4 en Notebook\nEstadísticas y Matplotlib]
    F2 --> F3[Fase 3: Sección 5 en Notebook\nModificaciones Multibase]
    F3 --> F4[Fase 4: Anexo Grupos de 3\nReseñas, Precios, Búsquedas]
    F4 --> F5[Fase 5: Sección 6 - Informe\nJustificaciones y Diagramas]
    F5 --> F6[Fase 6: Validación E2E\nEjecución Limpia y Entrega]
```

---

### 🔹 Fase 1: Finalización de Módulos de Soporte y Correcciones (`src/`)
**Objetivo:** Dejar el 100% de los módulos de `src/` completamente probados, documentados y sin errores de dependencia antes de volcarlos al notebook.

- [x] **Tarea 1.1:** Implementar en [`src/queries.py`](src/queries.py) la consulta Cypher `get_artist_followers_count(driver)` para consultar en Neo4j la cantidad de usuarios que siguen a cada artista (`(:Usuario)-[:SIGUE]->(:Artista)`), ordenados de mayor a menor.
- [x] **Tarea 1.2:** Implementar en [`src/queries.py`](src/queries.py) la consulta `get_tickets_sold_per_venue(driver, db_mongo)` para calcular las entradas vendidas acumuladas por lugar o recinto, cruzando compras con lugares.
- [x] **Tarea 1.3:** Adaptar [`src/analytics.py`](src/analytics.py) para visualización interactiva exclusiva en pantalla/notebook, eliminando `save_path` y la persistencia a disco innecesaria para prevenir `FileNotFoundError`.
- [x] **Tarea 1.4:** Revisar y certificar docstrings en estilo Google y anotaciones de tipo estrictas en [`src/analytics.py`](src/analytics.py) y [`src/queries.py`](src/queries.py).

---

### 🔹 Fase 2: Integración de la Sección 4 en el Notebook (`TP_Integrador.ipynb`)
**Objetivo:** Volcar en celdas de Markdown y código ejecutables las estadísticas analíticas y los gráficos de Matplotlib generados directamente desde las bases de datos.

- [x] **Tarea 2.1:** Encabezado explicativo de la **Sección 4: Estadísticas y Gráficos**, justificando la arquitectura desacoplada en dos capas (cálculo estadístico puro + visualización).
- [x] **Tarea 2.2 — Métrica 4.1:** Celda para *Cantidad de seguidores por artista* (consulta a Neo4j $\rightarrow$ `build_artist_followers_stats` $\rightarrow$ visualización con DataFrame y gráfico de barras verticales).
- [x] **Tarea 2.3 — Métrica 4.2:** Celda para *Recaudación por evento* (consulta a MongoDB $\rightarrow$ `build_event_revenue_stats` $\rightarrow$ visualización con DataFrame y gráfico de barras horizontales formateado en moneda).
- [x] **Tarea 2.4 — Métrica 4.3:** Celda para *Entradas vendidas por lugar* (consulta a Neo4j/Mongo $\rightarrow$ `build_venue_tickets_stats` $\rightarrow$ gráfico de barras).
- [x] **Tarea 2.5 — Métrica 4.4:** Celda para *Cantidad de búsquedas por género* (consulta al Sorted Set en Redis $\rightarrow$ `build_genre_searches_stats` $\rightarrow$ gráfico).
- [x] **Tarea 2.6 — Dashboard Integrado:** Celda opcional que invoque `plot_combined_dashboard` para mostrar un panel unificado 2x2 de alta calidad.

---

### 🔹 Fase 3: Integración de la Sección 5 en el Notebook (`TP_Integrador.ipynb`)
**Objetivo:** Demostrar interactivamente en el notebook las 5 modificaciones multibase exigidas, evidenciando el estado previo y posterior al cambio en cada motor involucrado.

- [x] **Tarea 3.1 — Modificación 5.1:** Aumento del 10% en el precio de eventos futuros en Rosario.
  - Celda de evidencia previa (`get_city_events_price_evidence`).
  - Celda de ejecución (`increase_future_events_price`).
  - Celda de evidencia posterior verificando precios en MongoDB y Neo4j, demostrando que las compras anteriores no cambiaron.
- [x] **Tarea 3.2 — Modificación 5.2:** Agregar servicio `"accesibilidad"` al lugar con ID 2 (Sala Diagonal).
  - Celda de evidencia previa (`get_place_services_evidence`).
  - Celda de ejecución (`add_service_to_place`).
  - Celda de evidencia posterior verificando la lista de servicios.
- [x] **Tarea 3.3 — Modificación 5.3:** Cancelación integral del evento 7 ("Radio Neón Tour").
  - Celda de evidencia previa (`get_cancelled_event_evidence`).
  - Celda de ejecución (`cancel_event`).
  - Celda de evidencia posterior verificando: estado cancelado en Mongo y Neo4j, compras en estado `"reembolsada"`, stock y capacidad en 0 en Redis, reservas destruidas y exclusión en recomendaciones.
- [x] **Tarea 3.4 — Modificación 5.4:** Eliminación del usuario Tomás Herrera (ID 6).
  - Celda de evidencia previa (`get_deleted_user_evidence`).
  - Celda con Markdown justificando la decisión de **anonimizar compras** para resguardar la consistencia contable.
  - Celda de ejecución (`delete_user`).
  - Celda de evidencia posterior demostrando: eliminación en MongoDB, disociación de aristas `:AMIGO_DE` y `:SIGUE` en Neo4j, destrucción de sesión en Redis y preservación de compras con `usuario_id = null`.
- [x] **Tarea 3.5 — Modificación 5.5:** Eliminación de amistades de un usuario a elección (Juan López).
  - Celda de evidencia previa (`get_user_friendships_evidence`).
  - Celda de ejecución (`delete_user_friendships`).
  - Celda de evidencia posterior confirmando 0 relaciones `:AMIGO_DE` para dicho usuario en Neo4j.

---

### 🔹 Fase 4: Implementación e Integración del Anexo (Requisitos para Grupos de 3)
**Objetivo:** Desarrollar, probar e integrar en el notebook los cuatro requerimientos adicionales del Anexo estipulados en `CONSIGNAS.md`, garantizando persistencia políglota adecuada y validaciones estrictas de negocio.

- [x] **Tarea 4.1 — Anexo 1: Reseñas de Eventos (MongoDB)**
  - **Estado en código:** Implementado en [`src/appendix.py`](src/appendix.py) (`create_event_review`, `validate_event_review`, `seed_sample_reviews`, `get_average_ratings_per_event`, `get_average_ratings_per_artist`, `demonstrate_reviews_flow`).
  - **Estado en notebook:** `[x] Integrado` en celdas 68, 69 y 70 de `TP_Integrador.ipynb`.
  - **Requerimientos de negocio:**
    - Permitir a un usuario calificar (1 a 5) y comentar un evento pasado (`fecha < FECHA_REFERENCIA`).
    - Validar que el usuario posea una compra confirmada para dicho evento (`estado == "confirmada"`).
    - Garantizar unicidad estricta (máximo una sola reseña por usuario y evento) mediante índice único compuesto en MongoDB (`{"usuario_id": 1, "evento_id": 1}`).
    - Demostrar en código un caso válido exitoso y un caso rechazado con captura de excepción.
    - Sembrar y persistir al menos 6 reseñas de diferentes usuarios.
    - Calcular y exhibir promedios de calificación por evento y por artista (agregando todos los eventos en los que participa el artista).

- [x] **Tarea 4.2 — Anexo 2: Historial de Precios y Gráfico de Evolución (MongoDB + Matplotlib)**
  - **Estado en código:** Implementado en [`src/appendix.py`](src/appendix.py) (`init_price_history`, `register_price_change`, `seed_sample_price_changes`, `get_event_price_at_date`, `get_event_price_history`, `plot_event_price_evolution`, `demonstrate_price_history_flow`).
  - **Estado en notebook:** `[x] Integrado` en celdas 71, 72 y 73 de `TP_Integrador.ipynb`.
  - **Requerimientos de negocio:**
    - Registrar cada variación de precio de un evento con su fecha de vigencia asociada.
    - Considerar el precio inicial del dataset vigente a partir de `2026-01-01`.
    - Registrar al menos 3 cambios de precio cronológicos sobre un mismo evento (ej. "Rock del Lago" / Evento 4).
    - Consultar el precio vigente de un evento en una fecha determinada cualquiera (`get_event_price_at_date`).
    - Graficar la evolución temporal del precio mediante un gráfico escalonado (*step plot*) con Matplotlib, visualizando fechas y precios históricos con formato adecuado.

- [x] **Tarea 4.3 — Anexo 3: Recomendación de Dos Saltos (Neo4j)**
  - **Estado en código:** Implementado en [`src/appendix.py`](src/appendix.py) (`recommend_events_two_hops`).
  - **Estado en notebook:** `[x] Integrado` en celdas 74 y 75 de `TP_Integrador.ipynb` probado con el usuario `"Sofía Martínez"` (quien conserva sus amistades tras las modificaciones).
  - **Requerimientos de negocio:**
    - Recomendar eventos futuros de artistas similares a los que siguen los amigos del usuario.
    - Navegación Cypher en 2 saltos: `(:Usuario)-[:AMIGO_DE]-(:Usuario)-[:SIGUE]->(:Artista)-[:SIMILAR_A]->(:Artista)-[:PARTICIPA_EN]->(:Evento)`.
    - Exclusión estricta de artistas que el usuario ya sigue directamente (`NOT (u)-[:SIGUE]->(recArt)`).
    - Exclusión estricta de eventos para los cuales el usuario ya tiene compra confirmada (`NOT (u)-[:COMPRO {estado: 'confirmada'}]->(ev)`).
    - Proyectar evento, artista y fecha, ordenados cronológicamente.
    - Ejecutar con un usuario que conserve sus amistades tras las modificaciones.

- [x] **Tarea 4.4 — Anexo 4: Historial de Búsquedas por Usuario y Recomendación Personalizada (Redis + Python)**
  - **Estado en código:** `[x] Completo` (implementado en [`src/appendix.py`](src/appendix.py) con `record_user_search`, `get_user_recent_searches`, `seed_sample_user_searches`, `recommend_events_two_hops_personalized` y `demonstrate_user_searches_flow`).
  - **Estado en notebook:** `[x] Integrado` en celdas 76 y 77 de `TP_Integrador.ipynb`.
  - **Requerimientos de negocio:**
    - Almacenar las últimas 5 búsquedas de cada usuario en Redis utilizando una estructura de Lista (`LPUSH` + `LTRIM 0 4`), descartando automáticamente las búsquedas más antiguas para mantener tamaño fijo O(1).
    - Implementar `record_user_search(user_id, search_term, genre, redis_client)` y `get_user_recent_searches(user_id, redis_client)`.
    - Implementar función de ordenamiento personalizado `recommend_events_two_hops_personalized(user, driver, db_mongo, redis_client)`:
      - Obtener las recomendaciones de dos saltos del Punto 3.
      - Obtener el historial reciente de búsquedas del usuario desde Redis.
      - Priorizar en primer lugar aquellos eventos cuyo género coincida con alguna búsqueda reciente del usuario, preservando subcriterios cronológicos.

---

### 🔹 Fase 5: Redacción del Informe Conceptual (Sección 6 e Informe del Anexo)
**Objetivo:** Desarrollar en celdas de Markdown dentro del notebook las explicaciones técnicas, teóricas y justificaciones arquitectónicas exigidas por la cátedra para el trabajo principal y el Anexo.

- [x] **Tarea 5.1 — Arquitectura Políglota:** Cuadro consolidado de qué se almacena en cada motor y su justificación técnica redactado e integrado en la Sección 6.1 del notebook.
- [x] **Tarea 5.2 — Integración e Identificadores:** Explicación de identificadores canónicos compartidos (`usuario_id`, `evento_id`, etc.) y consultas multibase que combinan motores integrada en la Sección 6.2 del notebook.
- [x] **Tarea 5.3 — Respuestas Teóricas Obligatorias:**
  - *Pregunta 1:* Vencimiento de reservas por TTL en Redis (10m) y liberación automática por fórmula de disponibilidad sin necesidad de procesos en segundo plano. Integrado en Sección 6.3.
  - *Pregunta 2:* Datos compartidos en más de una base, principio de MongoDB como Single Source of Truth y funciones atómicas de actualización en cascada. Integrado en Sección 6.3.
  - *Pregunta 3:* Consistencia en eliminación de Tomás Herrera (anonimización contable de compras desvinculando identidad vs. borrado en cascada) y eliminación de amistades en Neo4j sin inconsistencias en MongoDB. Integrado en Sección 6.3.
- [x] **Tarea 5.4 — Justificación Arquitectónica del Anexo:** Justificación técnica de las bases y estructuras seleccionadas para los 4 requerimientos del Anexo (colección documental `resenas` e `historial_precios` embebido en MongoDB; navegación en grafo Neo4j; listas acotadas `LPUSH` + `LTRIM` en Redis) integrada en Sección 6.4.
- [ ] **Tarea 5.5 — Capturas y Salidas:** Asegurar que todas las celdas del notebook conserven sus outputs visibles tras la ejecución completa en el contenedor Docker.

---

### 🔹 Fase 6: Validación End-to-End y Empaquetado para Entrega
**Objetivo:** Certificar la idempotencia, reproducibilidad y empaquetado del proyecto según las pautas de entrega.

- [ ] **Tarea 6.1:** Reiniciar el kernel y ejecutar todas las celdas de principio a fin (*Restart Kernel and Run All Cells*) en un entorno Docker limpio.
- [ ] **Tarea 6.2:** Verificar que no se produzcan excepciones no controladas ni advertencias de deprecación.
- [ ] **Tarea 6.3:** Validar que [`requirements.txt`](requirements.txt) refleje exactamente las versiones compatibles del contenedor.
- [ ] **Tarea 6.4:** Empaquetar el archivo `.zip` de entrega con el notebook ejecutado, el informe y el archivo de requerimientos.

---

## 🔍 3. Registro de Auditoría Técnica y Vulnerabilidades Resueltas

Este registro audita los hallazgos técnicos, vulnerabilidades de negocio y desfasajes de esquemas detectados durante la revisión del código fuente.

### 🔴 Problemas Críticos / Vulnerabilidades de Negocio

- [x] **BUG-01: Estado por defecto permisivo (`"activo"`) en `resolve_event`**
  - **Ubicación:** `src/purchase.py` (`resolve_event`)
  - **Riesgo:** Si un evento carecía del atributo `estado` en MongoDB (borrador, error de carga o `$unset`), el default `"activo"` habilitaba la venta indebida de entradas (*violación del principio Fail-Closed*).
  - **Resolución:** Se configuró `"cancelado"` como estado por defecto (`str(doc.get("estado") or "cancelado")`), bloqueando cualquier venta de eventos incompletos o corruptos.

- [x] **BUG-02: Omisión de verificación de estado del evento en confirmación de compra**
  - **Ubicación:** `src/purchase.py` (`confirm_reservation`)
  - **Riesgo:** Si un evento se cancelaba durante los 10 minutos de una reserva previa, la confirmación procedía sin revalidar el estado vigente en MongoDB.
  - **Resolución:** Se agregó una guarda explícita en `confirm_reservation` que consulta MongoDB y lanza `ValueError` si el evento ya no se encuentra en estado `"activo"`.

- [x] **BUG-03: Precio por defecto en `$0` (*Free Checkout Exploit*)**
  - **Ubicación:** `src/purchase.py` (`resolve_event`, `reserve_tickets`, `confirm_reservation`)
  - **Riesgo:** Con `doc.get("precio", 0)`, si un evento se registraba sin precio o con precio nulo, los usuarios podían reservar y comprar entradas gratis por `$0`, impactando compras por valor cero en MongoDB y relaciones `:COMPRO {total: 0}` en Neo4j.
  - **Resolución:** Se agregaron validaciones estrictas en cascada:
    1. En `resolve_event`: lanza `ValueError` si `precio` no existe o es `<= 0`.
    2. En `reserve_tickets`: valida que `price > 0` antes de reservar cupo.
    3. En `confirm_reservation`: valida que el precio final liquidado sea estrictamente mayor a 0.

### 🟠 Problemas de Integración entre Módulos y Bugs de Ejecución

- [x] **BUG-04: Error de tipeo `tuple_itemb` en `build_genre_searches_stats`**
  - **Ubicación:** `src/analytics.py` (Línea 162)
  - **Riesgo:** Al procesar tuplas crudas de Redis (`zrange/zrevrange(..., withscores=True)`), el bucle definía `tuple_itemb` pero utilizaba `tuple_item`, arrojando un `NameError` inmediato en tiempo de ejecución.
  - **Resolución:** Se corrigió el nombre de la variable en el bucle a `tuple_item`.

- [x] **BUG-05: Desfasaje de claves entre `src/analytics.py` y `src/queries.py`**
  - **Ubicación:** `src/analytics.py` (capa de estadísticas)
  - **Causa:** `analytics.py` se implementó esperando claves en inglés (`event_name`, `total_revenue`, `search_count`), mientras que `queries.py` devuelve campos en español (`evento_nombre`, `total_recaudado`, `cantidad_busquedas`).
  - **Riesgo:** Al pasar la salida de `get_tickets_sold_per_event` o `get_top_searched_genres`, los gráficos generaban recaudación en `$0`, nombres genéricos y conteo de búsquedas en 0.
  - **Resolución:** Se adaptaron las 4 funciones de estadísticas para priorizar los campos en español del modelo de datos de la base.

- [x] **BUG-06: Creación automática de directorios al guardar figuras (`save_path`)**
  - **Ubicación:** `src/analytics.py` (`plot_*`)
  - **Riesgo:** Si el usuario especificaba una ruta hacia un subdirectorio que no existía (ej. `figures/dashboard.png`), `fig.savefig` lanzaba `FileNotFoundError`.
  - **Resolución:** Se eliminó el parámetro `save_path` y la lógica de guardado en disco en favor de renderizado puro en notebook con Matplotlib, descartando el riesgo de `FileNotFoundError`.

- [x] **BUG-07: Faltan 2 consultas en `src/queries.py` para alimentar los gráficos 1 y 3**
  - **Ubicación:** `src/queries.py`
  - **Detalle:** `analytics.py` tiene visualizadores para *Seguidores por artista* y *Entradas por lugar*, pero en `queries.py` no estaban creadas las funciones para extraer esos datos directamente desde Neo4j/MongoDB.
  - **Resolución:** Se implementaron `get_artist_followers_count(driver)` y `get_tickets_sold_per_venue(driver)` utilizando consultas Cypher parametrizadas con `OPTIONAL MATCH`.

- [x] **BUG-08: Desconexión de Secciones 4 y 5 en el Notebook `TP_Integrador.ipynb`**
  - **Ubicación:** `notebooks/TP_Integrador.ipynb`
  - **Detalle:** El notebook originalmente concluía en la celda de la Consulta 12. Faltaban las celdas ejecutables de la **Sección 4** (Estadísticas y gráficos con Matplotlib) y de la **Sección 5** (Modificaciones multibase con evidencia).
  - **Resolución:** Se incorporaron exitosamente las celdas de Markdown y código ejecutables para la Sección 4 (métricas 4.1 a 4.4 más dashboard combinado) y la Sección 5 (mutaciones 5.1 a 5.5 con evidencias antes y después), conservando sus outputs visibles en el notebook.

- [x] **BUG-09: Falta implementar el Punto 4 del Anexo en `src/appendix.py` (Historial de Búsquedas en Redis)**
  - **Ubicación:** `src/appendix.py`
  - **Detalle:** El archivo `appendix.py` incluía implementaciones para los puntos 1, 2 y 3, pero carecía de las funciones para el registro de las últimas 5 búsquedas por usuario en Redis (`LPUSH` + `LTRIM`) y el reordenamiento de recomendaciones por género coincidente.
  - **Resolución:** Se implementaron con éxito `record_user_search`, `get_user_recent_searches`, `seed_sample_user_searches`, `recommend_events_two_hops_personalized` y `demonstrate_user_searches_flow`, cumpliendo estrictamente con la estructura de lista acotada a 5 elementos y el ordenamiento por prioridad de género coincidente.

- [x] **BUG-10: Celdas de los Puntos 1, 2 y 4 del Anexo pendientes en el Notebook `TP_Integrador.ipynb`**
  - **Ubicación:** `notebooks/TP_Integrador.ipynb`
  - **Detalle:** Solo el Punto 3 (Recomendación de dos saltos) se encontraba originalmente integrado en el notebook. Faltaban las celdas interactivas para Reseñas de Eventos (Punto 1), Historial y Gráfico de Precios (Punto 2) e Historial de Búsquedas con Recomendación Personalizada (Punto 4).
  - **Resolución:** Se incorporaron con éxito las celdas de Markdown y código ejecutables para los Anexos 1, 2 y 4 (celdas 68 a 77 de `TP_Integrador.ipynb`), invocando a los módulos de `src/appendix.py` con validaciones de flujo, promedios y renderizado de gráficos.

- [x] **BUG-11: Funciones procesadoras intermedias redundantes en `src/functions.py`**
  - **Ubicación:** `src/functions.py` (`process_user`, `process_artist`, `process_place`, `process_event`, `process_sale`)
  - **Detalle:** Existían funciones auxiliares intermedias no utilizadas que duplicaban la lógica de ingesta y sanitización ya centralizada de forma atómica en `process_dataset` y sus etapas especializadas.
  - **Resolución:** Se refactorizó y depuró `src/functions.py`, eliminando las 213 líneas de código no utilizado y consolidando el flujo exclusivamente en el pipeline principal.

