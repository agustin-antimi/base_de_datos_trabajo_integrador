# AGENTS.md — Instrucciones y Guía para Agentes de IA

Este documento define el contexto, las directrices de arquitectura y los estándares de codificación para el desarrollo en este repositorio. Cualquier agente que opere en este proyecto debe acatar estas directivas.

---

## 1. Contexto y Objetivo del Proyecto

* **Materia e Institución:** Trabajo Práctico Integrador — Base de Datos, Licenciatura en Ciencia de Datos en Organizaciones (UNLP 2026).
* **Dominio:** Plataforma de gestión de eventos, recitales, artistas, recintos, usuarios y venta de entradas.
* **Paradigma de Persistencia Políglota:**
  * **MongoDB (Documental):** Almacenamiento de información descriptiva y semiestructurada de entidades (usuarios, artistas, eventos, lugares, compras) sin anidamientos relacionales complejos.
  * **Neo4j (Grafos):** Modelado y consulta de relaciones complejas de la red (seguimiento y amistad entre usuarios, similitud entre artistas, relaciones usuario-evento).
  * **Redis (Clave-Valor / En Memoria):** Consultas de alta concurrencia y baja latencia, control de cupos/stock en tiempo real, caché y contadores.

---

## 2. Reglas de Idioma y Estilo de Código

1. **Lenguaje del Código:**
   * **Identificadores en Inglés:** Nombres de variables, funciones, clases, métodos, módulos, constantes y nombres de nuevos archivos deben estar redactados en **inglés** (ej. `fetch_user_by_id`, `event_payload`, `batch_size`).
   * **Comentarios y Docstrings en Español:** Todo comentario aclaratorio, documentación de funciones, módulos y clases debe escribirse en **español** formal y conciso.
2. **Tipado Estricto (Type Hints):**
   * Todo parámetro y valor de retorno de funciones y métodos debe contar con anotaciones de tipo explícitas (`list[dict[str, Any]]`, `Optional[Driver]`, `tuple[int, ...]` aprovechando Python 3.11+).
3. **Modularidad y Separación de Responsabilidades:**
   * Evitar scripts monolíticos o acoplamiento excesivo.
   * La lógica reutilizable de ingesta, transformación y consultas reside en módulos dentro del directorio `src/`.
   * Los notebooks en `notebooks/` se reservan para orquestación de alto nivel, experimentación interactiva y visualizaciones.

---

## 3. Estructura del Directorio

```text
.
├── docker-compose.yml       # Orquestación de servicios (python, neo4j, mongo, redis)
├── .env.example             # Plantilla de credenciales y variables de entorno
├── .gitignore               # Exclusiones de Git (secretos, data local, cachés)
├── AGENTS.md                # Directivas para agentes de IA
├── README.md                # Documentación del proyecto
├── data/                    # Archivos de datos crudos (ej. dataset.txt - excluido de git)
├── notebooks/               # Jupyter Notebooks de desarrollo y entregas
├── python/                  # Definición del contenedor de Python
│   ├── Dockerfile           # Entorno Python 3.11 + JupyterLab
│   └── requirements.txt     # Dependencias de Python del contenedor
├── scripts/                 # Scripts autónomos de prueba y utilidades de consola
└── src/                     # Paquete principal de lógica modular
    ├── __init__.py
    ├── config.py            # Rutas, variables de entorno y constantes de configuración
    └── functions.py         # Ingesta, limpieza y manipulación de datos
```

---

## 4. Buenas Prácticas por Motor de Base de Datos

### Neo4j (Grafos)
* Usar siempre consultas Cypher parametrizadas (`$param`) para evitar inyección y mejorar el rendimiento del plan de ejecución.
* Para cargas de datos, utilizar `UNWIND` y cláusulas `MERGE` con índices/restricciones de unicidad en los IDs.
* Gestionar las sesiones mediante administradores de contexto (`with driver.session(...) as session:`).

### MongoDB (Documentos)
* Inserciones y actualizaciones por lote (`insert_many`, `bulk_write`) en lugar de operaciones individuales dentro de bucles.
* Separar y sanitizar atributos antes de persistir (eliminar listas que pertenecen a relaciones de grafos de los documentos si corresponde).

### Redis (Clave-Valor)
* Instanciar conexiones con `decode_responses=True` para trabajar con strings legibles.
* Utilizar convención de nombres de claves estandarizada con prefijos y delimitador `:` (ej. `event:<id>:capacity`, `user:<id>:cart`).
* Manejar operaciones atómicas (`INCR`, `DECR`) para cupos concurrentes.

---

## 5. Entorno de Ejecución (Docker Compose)

* Todo el entorno corre bajo Docker. Al sugerir o ejecutar comandos, considerar si se ejecutan en el host o dentro del contenedor:
  * **Dentro del contenedor:** Directorio de trabajo `/work`, `PYTHONPATH=/work/src`. Nombres de host: `neo4j`, `mongo`, `redis`.
  * **Desde el host:** Conexiones mediante `localhost` y puertos expuestos (Neo4j: `7474`/`7687`, Mongo: `27017`, Redis: `6379`, Jupyter: `8888`).
* Nunca exponer contraseñas reales en commits ni modificar `.env.example` con secretos de producción.
