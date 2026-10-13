# Trabajo Práctico Integrador – Bases de Datos 2026
## Sistema de Venta de Entradas y Recomendación de Eventos (Persistencia Políglota)

> **Materia:** Base de Datos — Licenciatura en Ciencia de Datos en Organizaciones  
> **Institución:** Universidad Nacional de La Plata (UNLP 2026)  
> **Tecnologías:** Python 3.11, MongoDB, Neo4j, Redis, Docker, JupyterLab

---

## 📋 Descripción del Proyecto

Este proyecto implementa una plataforma integral de gestión de recitales y espectáculos, venta de entradas, control de cupos en tiempo real y recomendación personalizada de eventos, sustentada bajo un **paradigma de persistencia políglota** con tres motores NoSQL complementarios:

1. **MongoDB (Documental):** Almacén principal de datos semiestructurados y entidades del dominio (usuarios, artistas, recintos/lugares, eventos y compras confirmadas).
2. **Neo4j (Grafos):** Modelado de relaciones complejas de la red social y musical (amistades entre usuarios, artistas seguidos, similitudes entre bandas, recintos donde se realizan los recitales y participación en eventos para recomendaciones y grafo de asistencia).
3. **Redis (Clave-Valor / En Memoria):** Gestión de estados efímeros de alta concurrencia y baja latencia (sesiones activas con TTL de 30 minutos, reservas temporales de entradas con TTL de 10 minutos, disponibilidad de cupos en tiempo real y contadores de búsquedas por género).

---

## 🏛️ Arquitectura de Persistencia Políglota

```
                             ┌──────────────────────────────────────┐
                             │    Aplicación / Notebook (Python)    │
                             └──────┬──────────────┬─────────────┬──┘
                                    │              │             │
                Datos Descriptivos  │   Relaciones │   Estados   │
                  y Transaccionales │    Complejas │    Efímeros │
                                    ▼              ▼             ▼
                           ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
                           │   MongoDB   │  │    Neo4j    │  │    Redis    │
                           │ (Documental)│  │   (Grafos)  │  │(En Memoria) │
                           └─────────────┘  └─────────────┘  └─────────────┘
                             • Usuarios       • :AMIGO_DE      • Sesiones
                             • Artistas       • :SIGUE         • Reservas
                             • Lugares        • :SIMILAR_A     • Stock real
                             • Eventos        • :PARTICIPA_EN  • Búsquedas
                             • Compras        • :COMPRO        • Caché
```

### Justificación de Cada Motor:
* **MongoDB:** Fuente de verdad documental inicial. Permite almacenar atributos flexibles de usuarios, recintos (servicios, capacidad), eventos (fechas, precios, cupos) y compras sin anidamientos innecesarios.
* **Neo4j:** Optimizado para navegaciones por el grafo en múltiples saltos (amigos de amigos, artistas similares seguidos por amigos, recomendaciones personalizadas). Evita costosos JOINs documentales.
* **Redis:** Estructuras en memoria con soporte nativo de expiración temporal (`TTL`), decremento/incremento atómico de cupos para evitar sobreventas (*overbooking*) y caching de búsquedas frecuentes.

---

## ⚙️ Reglas de Negocio Implementadas

* **Tiempos de Vencimiento (TTL):**
  * Sesiones de usuario: expiran a los **30 minutos** (`SESSION_TTL_SECONDS = 1800`).
  * Reservas temporales no confirmadas: expiran a los **10 minutos** (`RESERVATION_TTL_SECONDS = 600`), restituyendo las entradas retenidas.
  * Caché de consultas/búsquedas: tiempo de reutilización de **5 minutos** (`SEARCH_CACHE_TTL_SECONDS = 300`).
* **Cálculo de Disponibilidad en Tiempo Real:**
  $$\text{Disponibles} = \text{cupo} - \text{entradas de compras confirmadas} - \sum(\text{entradas en reservas vigentes})$$
  *(La disponibilidad nunca puede quedar negativa ni permitir sobreventa).*
* **Asistencia a Eventos:** Se calcula dinámicamente a partir de las compras confirmadas de eventos cuya fecha es anterior a la fecha de referencia (`FECHA_REFERENCIA = "2026-10-01"`). No se persiste de forma redundante.
* **Cero Hardcoding:** Todas las consultas y operaciones resuelven dinámicamente las entidades por nombre o ID contra la base de datos (MongoDB/Neo4j/Redis).
* **Sanitización e Idempotencia:** Limpieza idempotente al inicio de la ejecución (`clean_db`) y remoción de atributos de relaciones en MongoDB (`$unset`) tras poblar el grafo en Neo4j para evitar duplicación inconsistente.

---

## 📁 Estructura del Directorio

```text
.
├── docker-compose.yml       # Orquestación de servicios (python, neo4j, mongo, redis)
├── .env.example             # Plantilla de credenciales y variables de entorno
├── .gitignore               # Exclusiones de Git (entornos virtuales, data local, cachés)
├── AGENTS.md                # Directivas de arquitectura y codificación para agentes
├── CONSIGNAS.md             # Enunciado y requerimientos oficiales de la cátedra
├── README.md                # Documentación del proyecto
├── requirements.txt         # Dependencias de Python del entorno
├── data/
│   └── dataset.txt          # Dataset provisto con entidades iniciales
├── notebooks/
│   ├── TP_Integrador.ipynb  # Notebook principal con ejecución interactiva y salidas
│   └── test_connections.ipynb # Notebook de verificación rápida de conectividad
├── python/
│   ├── Dockerfile           # Entorno de ejecución Python 3.11 + JupyterLab
│   └── requirements.txt     # Dependencias instaladas en el contenedor
├── scripts/
│   └── test_connections.py  # Script de verificación de conexiones por terminal
└── src/                     # Paquete principal de lógica modular
    ├── __init__.py
    ├── config.py            # Centralización de configuración, variables y helpers de conexión
    ├── functions.py         # Ingesta ETL, limpieza, índices, restricciones y sincronización
    ├── purchase.py          # Flujo transaccional de compra, sesiones y reservas
    ├── queries.py           # Ejecución genérica y parametrizada de consultas políglotas
    └── analytics.py         # Procesamiento estadístico y visualización con Matplotlib
```

---

## 🚀 Requisitos Previos e Instalación

### Opción A: Entorno Contenerizado con Docker (Recomendado)

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/agustin-antimi/base_de_datos_trabajo_integrador.git
   cd base_de_datos_trabajo_integrador
   ```

2. **Configurar el archivo de entorno:**
   Copiar `.env.example` a `.env`:
   ```bash
   cp .env.example .env
   ```

3. **Iniciar los servicios con Docker Compose:**
   ```bash
   docker compose up -d
   ```

4. **Acceder a las interfaces y servicios:**
   * **JupyterLab:** [http://localhost:8888](http://localhost:8888)
   * **Neo4j Browser:** [http://localhost:7474](http://localhost:7474) (Credenciales: `neo4j` / `neo4j123` o las definidas en `.env`)
   * **MongoDB:** Puerto `27017` (Credenciales: `admin` / `admin123`)
   * **Redis:** Puerto `6379` (Password: `redis123`)

---

### Opción B: Ejecución Local en el Host (Windows / Linux / macOS)

Si ya se dispone de instancias locales de MongoDB, Neo4j y Redis (o mediante los contenedores de base de datos de Docker sin el contenedor `python`):

1. **Crear y activar un entorno virtual de Python 3.11+:**
   ```bash
   python -m venv .venv
   # En Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # En Linux/macOS:
   source .venv/bin/activate
   ```

2. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Iniciar JupyterLab o ejecutar scripts:**
   ```bash
   jupyter lab
   ```
   *Nota: `src/config.py` cuenta con resolución automática de host, adaptándose transparentemente si se ejecuta en Docker (`mongo`, `neo4j`, `redis`) o en el host anfitrión (`localhost`).*

---

## 🛠️ Componentes y Módulos de `src/`

* **`config.py`:**
  * Centraliza credenciales, puertos, URIs y constantes de negocio (`SESSION_TTL_SECONDS`, `RESERVATION_TTL_SECONDS`, `REFERENCE_DATE`).
  * Expone funciones conectoras reutilizables: `get_mongo_client()`, `get_mongo_db()`, `get_neo4j_driver()`, `get_redis_client()` y `wait_for_services()`.
* **`functions.py`:**
  * `clean_db()`: Limpieza completa e idempotente de las tres bases.
  * `create_mongo_indexes()` y `create_neo4j_constraints()`: Creación de índices y restricciones de unicidad.
  * `process_dataset()`: Orquesta el pipeline ETL (carga cruda en MongoDB $\rightarrow$ creación de restricciones $\rightarrow$ población del grafo en Neo4j $\rightarrow$ sanitización `$unset` en MongoDB $\rightarrow$ inicialización de stock y sesiones en Redis).
  * `get_event_available_stock()`: Cálculo en tiempo real de entradas disponibles según la fórmula oficial.
* **`purchase.py`:**
  * `create_user_session()`: Generación de sesión activa en Redis con TTL de 30 minutos.
  * `reserve_tickets()`: Reserva temporal con validación de sesión y disponibilidad, bloqueo de stock y TTL de 10 minutos.
  * `confirm_reservation()`: Transacción de confirmación, impacto en MongoDB (`compras`), creación de relación `:COMPRO` en Neo4j y liberación de reserva en Redis.
  * `cancel_reservation()`: Cancelación voluntaria liberando stock en Redis.
  * `demonstrate_purchase_flow()`: Suite con demostración de los tres casos requeridos (compra exitosa, rechazo por falta de cupo, cancelación).
* **`queries.py`:**
  * Ejecución desacoplada de consultas Cypher (`execute_neo4j_query`), pipelines de agregación en MongoDB (`execute_mongo_aggregation`) y operaciones en Redis.
* **`analytics.py`:**
  * Arquitectura desacoplada en dos capas: capa de procesamiento estadístico puro y capa de visualización gráfica con Matplotlib (seguidores por artista, recaudación por evento, entradas por recinto, búsquedas por género).

---

## 📊 Demostraciones y Consultas Resueltas

El notebook [notebooks/TP_Integrador.ipynb](notebooks/TP_Integrador.ipynb) cubre la totalidad de los puntos de las consignas:

1. **Limpieza e Ingesta:** Limpieza idempotente y carga políglota distribuida.
2. **Flujo de Compra:** Demostración de compra exitosa, rechazo por stock y cancelación.
3. **12 Consultas Políglotas:**
   * Usuarios asistentes a recitales de una banda específica.
   * Amigos con gustos musicales compartidos.
   * Recomendación de artistas según amigos y disponibilidad de eventos futuros.
   * Artistas similares a los seguidos.
   * Filtrado de eventos por ciudad y rango de precio.
   * Agrupaciones por género y total gastado por usuario.
   * Métricas en tiempo real en Redis (usuarios conectados, reservas vigentes con tiempo restante, géneros más buscados).
4. **Estadísticas y Gráficos:** Reportes agregados y gráficos con Matplotlib (seguidores, recaudación, entradas por lugar, búsquedas).
5. **Modificaciones Multibase:** Aumento porcentual de precios futuros, actualización de servicios en recintos, cancelación de eventos con reembolso y cascada en las tres bases, eliminación controlada de usuarios y desvinculación de amistades.

---

## 👥 Autores y Materia

* **Carrera:** Licenciatura en Ciencia de Datos en Organizaciones.
* **Facultad de Informática / Ciencias Económicas — UNLP (2026).**
* **Materia:** Base de Datos — Trabajo Práctico Integrador.
