"""Módulo de funciones para ingesta, transformación y persistencia políglota.

Orquesta la distribución de datos entre MongoDB (documentos), Neo4j (grafos)
y Redis (clave-valor / estados en memoria) para el TP Integrador de Bases de Datos 2026.
"""

import json
from pathlib import Path
from typing import Any, Optional, Union

import redis
from neo4j import Driver
from pymongo.database import Database

try:
    from config import (
        INITIAL_GENRE_SEARCHES,
        INITIAL_ONLINE_USERS,
        INITIAL_UNCONFIRMED_RESERVATIONS,
        MAPEO_RELACIONES,
        REFERENCE_DATE,
        RELATION_MAPPINGS,
        RESERVATION_TTL_SECONDS,
        SEARCH_CACHE_TTL_SECONDS,
        SESSION_TTL_SECONDS,
    )
except ImportError:
    from src.config import (
        INITIAL_GENRE_SEARCHES,
        INITIAL_ONLINE_USERS,
        INITIAL_UNCONFIRMED_RESERVATIONS,
        MAPEO_RELACIONES,
        REFERENCE_DATE,
        RELATION_MAPPINGS,
        RESERVATION_TTL_SECONDS,
        SEARCH_CACHE_TTL_SECONDS,
        SESSION_TTL_SECONDS,
    )


# ==============================================================================
# CONSIGNAS: Requisitos Técnicos - Limpieza de las Tres Bases
# "La primera sección del notebook debe limpiar las tres bases."
# ==============================================================================


def clean_db(*databases: Union[Database, Driver, redis.Redis]) -> None:
    """Limpia las bases de datos específicas pasadas por parámetro.

    Args:
        *databases: Instancias de conexión a bases de datos (Database de PyMongo,
            Driver de Neo4j o Redis de redis-py).
    """
    for db in databases:
        if isinstance(db, Database):
            db.client.drop_database(db.name)
            print(f"[MongoDB] Base de datos '{db.name}' eliminada correctamente.")

        elif isinstance(db, Driver):
            with db.session(database="neo4j") as session:
                session.run("MATCH (n) DETACH DELETE n")
            print("[Neo4j] Grafo completamente limpiado.")

        elif isinstance(db, redis.Redis):
            db.flushdb()
            print("[Redis] Base de datos en memoria limpiada.")

        else:
            print(f"[Advertencia] Tipo de base de datos no soportado: {type(db)}")


# ==============================================================================
# CONSIGNAS: Requisitos Técnicos - Índices y Restricciones de Unicidad
# "Crear los índices o restricciones de unicidad que consideren necesarios, y justificarlos."
# ==============================================================================


def create_mongo_indexes(db_mongo: Database) -> None:
    """Crea los índices y restricciones de unicidad en las colecciones de MongoDB.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
    """
    db_mongo.usuarios.create_index("usuario_id", unique=True)
    db_mongo.artistas.create_index("artista_id", unique=True)
    db_mongo.lugares.create_index("lugar_id", unique=True)
    db_mongo.eventos.create_index("evento_id", unique=True)
    db_mongo.compras.create_index("compra_id", unique=True)
    print("[MongoDB] Índices de unicidad creados en todas las colecciones.")


def create_neo4j_constraints(driver_neo4j: Driver) -> None:
    """Crea las restricciones de unicidad sobre los identificadores en Neo4j.

    Args:
        driver_neo4j: Driver de conexión a la base de grafos Neo4j.
    """
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (u:Usuario) REQUIRE u.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Artista) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Lugar) REQUIRE l.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Evento) REQUIRE e.id IS UNIQUE",
    ]
    with driver_neo4j.session(database="neo4j") as session:
        for c in constraints:
            session.run(c)
    print("[Neo4j] Restricciones de unicidad verificadas/creadas con éxito.")


# ==============================================================================
# CONSIGNAS: Sección 1 - Carga Inicial (Extracción de Datos e Ingesta en MongoDB)
# "Cargar el dataset del final distribuyendo la información entre las tres bases..."
# ==============================================================================


def load_raw_dataset(filepath: Union[str, Path]) -> dict[str, Any]:
    """Lee el archivo .txt de datos y devuelve un diccionario con las entidades crudas.

    Args:
        filepath: Ruta hacia el archivo .txt con la definición de listas de datos.

    Returns:
        Diccionario con las listas crudas de usuarios, artistas, lugares, eventos y compras.

    Raises:
        FileNotFoundError: Si el archivo no existe en la ruta provista.
    """
    scope: dict[str, Any] = {}
    path_obj = Path(filepath)
    if not path_obj.exists():
        raise FileNotFoundError(f"No se encontró el archivo de dataset en: {path_obj.resolve()}")

    with open(path_obj, "r", encoding="utf-8") as f:
        code = f.read()
    exec(code, {}, scope)
    return scope


def insert_raw_data_to_mongo(
    raw_data: dict[str, Any],
    db_mongo: Database,
    target_collections: Optional[tuple[str, ...]] = None,
) -> None:
    """Inserta el conjunto de datos completo y crudo en MongoDB como fuente de verdad inicial.

    Args:
        raw_data: Diccionario con listas de entidades extraídas del archivo de datos.
        db_mongo: Instancia de base de datos de MongoDB.
        target_collections: Tupla opcional con nombres de colecciones a persistir.
            Si no se especifica, persiste automáticamente todas las listas de entidades
            presentes en raw_data.
    """
    collections = (
        target_collections
        if target_collections is not None
        else tuple(k for k, v in raw_data.items() if isinstance(v, list))
    )
    for col_name in collections:
        items = raw_data.get(col_name, [])
        if items and isinstance(items, list):
            collection = db_mongo[col_name]
            # Limpiar colección antes de insertar por si existían datos
            collection.delete_many({})
            collection.insert_many([dict(item) for item in items])
            print(f"[MongoDB] Colección '{col_name}': {len(items)} registros insertados.")


# ==============================================================================
# CONSIGNAS: Sección 1 - Carga Inicial en Neo4j (Construcción del Grafo)
# "Los datos que existan en más de una base deben generarse a partir de los ya cargados..."
# ==============================================================================


def populate_neo4j_from_mongo(db_mongo: Database, driver_neo4j: Driver) -> None:
    """Lee las entidades y relaciones almacenadas en MongoDB y construye el grafo en Neo4j.

    Args:
        db_mongo: Instancia de base de datos de MongoDB de donde se leen los datos.
        driver_neo4j: Driver de conexión a Neo4j para ejecutar las mutaciones Cypher.
    """
    with driver_neo4j.session(database="neo4j") as session:
        # 1. Artistas y relaciones de similitud
        artists = list(db_mongo.artistas.find({}, {"_id": 0}))
        if artists:
            query_artist_nodes = """
            UNWIND $artistas AS a
            MERGE (art:Artista {id: a.artista_id})
            ON CREATE SET art.nombre = a.nombre, art.genero = a.genero
            """
            session.run(query_artist_nodes, artistas=artists)

            query_artist_similar = """
            UNWIND $artistas AS a
            UNWIND a.similares AS sim_id
            MATCH (orig:Artista {id: a.artista_id})
            MATCH (dest:Artista {id: sim_id})
            MERGE (orig)-[:SIMILAR_A]->(dest)
            """
            session.run(query_artist_similar, artistas=artists)
            print(f"[Neo4j] {len(artists)} artistas y sus relaciones de similitud cargados.")

        # 2. Lugares (recintos)
        places = list(db_mongo.lugares.find({}, {"_id": 0}))
        if places:
            query_places = """
            UNWIND $lugares AS l
            MERGE (lug:Lugar {id: l.lugar_id})
            ON CREATE SET lug.nombre = l.nombre, lug.ciudad = l.ciudad, lug.capacidad = l.capacidad
            """
            session.run(query_places, lugares=places)
            print(f"[Neo4j] {len(places)} lugares cargados.")

        # 3. Eventos y vínculos con Lugares y Artistas
        events = list(db_mongo.eventos.find({}, {"_id": 0}))
        if events:
            query_event_nodes = """
            UNWIND $eventos AS e
            MERGE (ev:Evento {id: e.evento_id})
            ON CREATE SET ev.nombre = e.nombre, ev.fecha = e.fecha, ev.genero = e.genero,
                          ev.precio = e.precio, ev.cupo = e.cupo, ev.estado = e.estado
            """
            session.run(query_event_nodes, eventos=events)

            query_event_venue = """
            UNWIND $eventos AS e
            MATCH (ev:Evento {id: e.evento_id})
            MATCH (lug:Lugar {id: e.lugar_id})
            MERGE (ev)-[:SE_REALIZA_EN]->(lug)
            """
            session.run(query_event_venue, eventos=events)

            query_event_artists = """
            UNWIND $eventos AS e
            UNWIND e.artistas AS art_id
            MATCH (art:Artista {id: art_id})
            MATCH (ev:Evento {id: e.evento_id})
            MERGE (art)-[:PARTICIPA_EN]->(ev)
            """
            session.run(query_event_artists, eventos=events)
            print(f"[Neo4j] {len(events)} eventos vinculados a lugares y artistas.")

        # 4. Usuarios, amistades y seguimiento a artistas
        users = list(db_mongo.usuarios.find({}, {"_id": 0}))
        if users:
            query_user_nodes = """
            UNWIND $usuarios AS u
            MERGE (user:Usuario {id: u.usuario_id})
            ON CREATE SET user.nombre = u.nombre, user.ciudad = u.ciudad
            """
            session.run(query_user_nodes, usuarios=users)

            query_friendships = """
            UNWIND $usuarios AS u
            UNWIND u.amigos AS amigo_id
            MATCH (orig:Usuario {id: u.usuario_id})
            MATCH (dest:Usuario {id: amigo_id})
            MERGE (orig)-[:AMIGO_DE]->(dest)
            """
            session.run(query_friendships, usuarios=users)

            query_follows = """
            UNWIND $usuarios AS u
            UNWIND u.sigue AS seguido_id
            MATCH (user:Usuario {id: u.usuario_id})
            MATCH (art:Artista {id: seguido_id})
            MERGE (user)-[:SIGUE]->(art)
            """
            session.run(query_follows, usuarios=users)
            print(f"[Neo4j] {len(users)} usuarios, red de amistades y seguidos cargados.")

        # 5. Compras
        purchases = list(db_mongo.compras.find({}, {"_id": 0}))
        if purchases:
            query_purchases = """
            UNWIND $compras AS c
            MATCH (user:Usuario {id: c.usuario_id})
            MATCH (ev:Evento {id: c.evento_id})
            MERGE (user)-[r:COMPRO {compra_id: c.compra_id}]->(ev)
            ON CREATE SET r.cantidad = c.cantidad,
                          r.precio_unitario = c.precio_unitario,
                          r.total = c.total,
                          r.fecha_compra = c.fecha_compra,
                          r.estado = c.estado
            """
            session.run(query_purchases, compras=purchases)
            print(f"[Neo4j] {len(purchases)} compras asociadas entre usuarios y eventos.")


# ==============================================================================
# CONSIGNAS: Requisitos Técnicos - Evitar Duplicación Innecesaria
# "Evitar la duplicación innecesaria de datos. Si deciden duplicar algo, justificarlo..."
# ==============================================================================


def sanitize_mongo_collections(
    db_mongo: Database,
    relation_mappings: Optional[dict[str, tuple[str, ...]]] = None,
) -> None:
    """Elimina de MongoDB los atributos relacionales que ya residen en Neo4j para evitar duplicación.

    Args:
        db_mongo: Instancia de base de datos de MongoDB a sanitizar.
        relation_mappings: Mapeo opcional de atributos a desasociar por entidad.
            Por defecto utiliza RELATION_MAPPINGS de config.py.
    """
    mappings = relation_mappings if relation_mappings is not None else RELATION_MAPPINGS
    for key, fields in mappings.items():
        if not fields:
            continue
        col_name = key.replace("_R", "").lower()
        if col_name in db_mongo.list_collection_names():
            unset_spec = {field: "" for field in fields}
            res = db_mongo[col_name].update_many({}, {"$unset": unset_spec})
            print(
                f"[MongoDB Sanitización] Colección '{col_name}': "
                f"removidos {fields} en {res.modified_count} documentos."
            )


# ==============================================================================
# CONSIGNAS: Sección 1 - Situación al Momento de la Carga Inicial en Redis
# - Usuarios conectados (sesiones con TTL 30m)
# - Reservas sin confirmar (TTL 10m)
# - Disponibilidad: cupo - compras confirmadas - reservas vigentes
# - Búsquedas realizadas hasta el momento por género
# ==============================================================================


def populate_redis_initial_state(
    db_mongo: Database,
    redis_client: redis.Redis,
    online_users: Optional[list[Union[int, str]]] = None,
    unconfirmed_reservations: Optional[list[dict[str, Any]]] = None,
    genre_searches: Optional[dict[str, int]] = None,
) -> None:
    """Inicializa en Redis el estado en tiempo real (cupos, sesiones activas, reservas y búsquedas).

    Args:
        db_mongo: Instancia de base de datos de MongoDB para consultar eventos, usuarios y compras.
        redis_client: Cliente de conexión a Redis donde se persisten los estados efímeros.
        online_users: Lista opcional de identificadores (int) o nombres (str) de usuarios con sesión activa.
            Si no se provee, utiliza INITIAL_ONLINE_USERS de config.py.
        unconfirmed_reservations: Lista opcional de diccionarios con datos de reservas iniciales.
            Cada reserva puede especificar 'user_name' o 'usuario_id', 'event_id' o 'evento_id',
            y 'quantity' o 'cantidad'. Si no se provee, utiliza INITIAL_UNCONFIRMED_RESERVATIONS de config.py.
        genre_searches: Diccionario opcional con cantidad de búsquedas iniciales por género.
            Si no se provee, utiliza INITIAL_GENRE_SEARCHES de config.py.
    """
    users_to_connect = online_users if online_users is not None else INITIAL_ONLINE_USERS
    reservations_to_create = (
        unconfirmed_reservations if unconfirmed_reservations is not None else INITIAL_UNCONFIRMED_RESERVATIONS
    )
    searches_to_register = genre_searches if genre_searches is not None else INITIAL_GENRE_SEARCHES

    # 1. Registrar reservas sin confirmar acumulando entradas retenidas por evento
    reserved_tickets_by_event: dict[int, int] = {}
    for idx, res in enumerate(reservations_to_create, start=1):
        # Resolver usuario dinámicamente por ID o por nombre contra MongoDB
        user_id = res.get("usuario_id") or res.get("user_id")
        user_name = res.get("user_name") or res.get("usuario_nombre") or res.get("user")
        if user_id is None and user_name:
            user_doc = db_mongo.usuarios.find_one({"nombre": str(user_name)})
            if user_doc:
                user_id = user_doc.get("usuario_id")
        elif user_id is not None and not user_name:
            user_doc = db_mongo.usuarios.find_one({"usuario_id": user_id})
            if user_doc:
                user_name = user_doc.get("nombre")

        event_id = res.get("evento_id") or res.get("event_id")
        event_name = res.get("evento_nombre") or res.get("event_name") or res.get("event")
        if event_id is None and event_name:
            event_doc = db_mongo.eventos.find_one({"nombre": str(event_name)})
            if event_doc:
                event_id = event_doc.get("evento_id")
        elif event_id is not None and not event_name:
            event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
            if event_doc:
                event_name = event_doc.get("nombre")

        event_doc = db_mongo.eventos.find_one({"evento_id": event_id}) if event_id else None
        price = int(event_doc.get("precio", 0)) if event_doc else 0
        quantity = res.get("cantidad") or res.get("quantity", 0)

        if event_id is not None:
            reserved_tickets_by_event[event_id] = reserved_tickets_by_event.get(event_id, 0) + quantity

        res_payload = {
            "reservation_id": idx,
            "usuario_id": user_id,
            "usuario_nombre": user_name,
            "evento_id": event_id,
            "evento_nombre": event_name,
            "cantidad": quantity,
            "precio_unitario": price,
        }
        redis_client.set(f"reservation:{idx}", json.dumps(res_payload), ex=RESERVATION_TTL_SECONDS)

    # El contador reservation:next_id almacena el último ID utilizado para que redis.incr devuelva el siguiente consecutivo
    last_res_id = len(reservations_to_create)
    redis_client.set("reservation:next_id", last_res_id)
    print(
        f"[Redis] {len(reservations_to_create)} reservas sin confirmar registradas (TTL {RESERVATION_TTL_SECONDS}s)."
    )

    # 2. Cupos disponibles para eventos futuros (Disponibles = cupo - compras confirmadas - reservas vigentes)
    events = list(db_mongo.eventos.find({}, {"_id": 0}))
    for ev in events:
        eid = ev["evento_id"]
        confirmed_docs = db_mongo.compras.find({"evento_id": eid, "estado": "confirmada"})
        confirmed_tickets = sum(c.get("cantidad", 0) for c in confirmed_docs)
        reserved_tickets = reserved_tickets_by_event.get(eid, 0)
        available_stock = max(0, ev["cupo"] - confirmed_tickets - reserved_tickets)

        redis_client.set(f"event:{eid}:capacity", ev["cupo"])
        redis_client.set(f"event:{eid}:stock", available_stock)

    print(f"[Redis] Cupos y capacidades inicializadas para {len(events)} eventos.")

    # 3. Sesiones activas iniciales (TTL: SESSION_TTL_SECONDS)
    connected_count = 0
    for item in users_to_connect:
        if isinstance(item, int):
            uid = item
        else:
            # Buscar ID de usuario por nombre en MongoDB
            user_doc = db_mongo.usuarios.find_one({"nombre": str(item)})
            uid = user_doc.get("usuario_id") if user_doc else None

        if uid is not None:
            session_payload = json.dumps({"user_id": uid, "status": "active"})
            redis_client.set(f"session:user:{uid}", session_payload, ex=SESSION_TTL_SECONDS)
            connected_count += 1

    print(f"[Redis] {connected_count} sesiones activas inicializadas (TTL {SESSION_TTL_SECONDS}s).")

    # 4. Historial de búsquedas iniciales por género
    if searches_to_register:
        redis_client.zadd("searches:genre", searches_to_register)
        print(f"[Redis] Contadores de búsquedas registrados para {len(searches_to_register)} géneros.")


# ==============================================================================
# CONSIGNAS: Reglas de Negocio - Cálculo Dinámico de Disponibilidad y Sincronización
# "Disponibles = cupo - compras confirmadas - reservas vigentes (nunca negativo)"
# ==============================================================================


def get_event_available_stock(
    event_id: int,
    db_mongo: Database,
    redis_client: redis.Redis,
) -> int:
    """Calcula la cantidad de entradas disponibles en tiempo real para un evento.

    Aplica la fórmula oficial de las consignas:
    Disponibles = cupo - compras confirmadas - reservas vigentes en Redis.
    Al vencer una reserva por TTL (10 min), Redis elimina la clave y sus entradas
    se liberan solas, recalculándose la disponibilidad automáticamente.

    Args:
        event_id: Identificador numérico del evento.
        db_mongo: Instancia de base de datos de MongoDB.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Cantidad entera de entradas disponibles (nunca menor a 0).
    """
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    if not event_doc:
        return 0
    total_capacity = int(event_doc.get("cupo", 0))

    # 1. Compras confirmadas en MongoDB
    confirmed_docs = db_mongo.compras.find({"evento_id": event_id, "estado": "confirmada"})
    confirmed_tickets = sum(int(c.get("cantidad", 0)) for c in confirmed_docs)

    # 2. Reservas vigentes en Redis (las que aún no expiraron)
    active_reserved_tickets = 0
    for key in redis_client.scan_iter("reservation:*"):
        if key == "reservation:next_id":
            continue
        raw_res = redis_client.get(key)
        if raw_res:
            try:
                res_data = json.loads(raw_res)
                if int(res_data.get("evento_id", -1)) == event_id:
                    active_reserved_tickets += int(res_data.get("cantidad", 0))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    available = max(0, total_capacity - confirmed_tickets - active_reserved_tickets)
    return available


def sync_event_stock(
    event_id: int,
    db_mongo: Database,
    redis_client: redis.Redis,
) -> int:
    """Sincroniza y actualiza la clave event:{event_id}:stock en Redis con la disponibilidad real.

    Args:
        event_id: Identificador numérico del evento.
        db_mongo: Instancia de base de datos de MongoDB.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Nuevo stock disponible actualizado y persistido en Redis.
    """
    available = get_event_available_stock(event_id, db_mongo, redis_client)
    redis_client.set(f"event:{event_id}:stock", available)
    return available


# ==============================================================================
# CONSIGNAS: Sección 1 - Carga Modular de Entidades (Usuarios, Artistas, Lugares, Eventos, Compras)
# ==============================================================================


def process_user(
    users_list: list[dict[str, Any]],
    db_mongo: Database,
    driver_neo4j: Driver,
) -> None:
    """Procesa e ingesta usuarios en MongoDB y Neo4j de forma modular.

    Args:
        users_list: Lista de diccionarios con datos de usuarios.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
    """
    if not users_list:
        return
    db_mongo.usuarios.delete_many({})
    db_mongo.usuarios.insert_many([dict(u) for u in users_list])

    with driver_neo4j.session(database="neo4j") as session:
        session.run(
            """
            UNWIND $usuarios AS u
            MERGE (user:Usuario {id: u.usuario_id})
            ON CREATE SET user.nombre = u.nombre, user.ciudad = u.ciudad
            """,
            usuarios=users_list,
        )
        session.run(
            """
            UNWIND $usuarios AS u
            UNWIND u.amigos AS amigo_id
            MATCH (orig:Usuario {id: u.usuario_id})
            MATCH (dest:Usuario {id: amigo_id})
            MERGE (orig)-[:AMIGO_DE]->(dest)
            """,
            usuarios=users_list,
        )
        session.run(
            """
            UNWIND $usuarios AS u
            UNWIND u.sigue AS seguido_id
            MATCH (user:Usuario {id: u.usuario_id})
            MATCH (art:Artista {id: seguido_id})
            MERGE (user)-[:SIGUE]->(art)
            """,
            usuarios=users_list,
        )

    db_mongo.usuarios.update_many({}, {"$unset": {"amigos": "", "sigue": ""}})


def process_artist(
    artists_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> None:
    """Procesa e ingesta artistas en MongoDB y Neo4j de forma modular.

    Args:
        artists_list: Lista de diccionarios con datos de artistas.
        db_mongo: Instancia de base de datos de MongoDB (opcional).
        driver_neo4j: Driver de conexión a Neo4j (opcional).
    """
    if not artists_list or db_mongo is None or driver_neo4j is None:
        return
    db_mongo.artistas.delete_many({})
    db_mongo.artistas.insert_many([dict(a) for a in artists_list])

    with driver_neo4j.session(database="neo4j") as session:
        session.run(
            """
            UNWIND $artistas AS a
            MERGE (art:Artista {id: a.artista_id})
            ON CREATE SET art.nombre = a.nombre, art.genero = a.genero
            """,
            artistas=artists_list,
        )
        session.run(
            """
            UNWIND $artistas AS a
            UNWIND a.similares AS sim_id
            MATCH (orig:Artista {id: a.artista_id})
            MATCH (dest:Artista {id: sim_id})
            MERGE (orig)-[:SIMILAR_A]->(dest)
            """,
            artistas=artists_list,
        )

    db_mongo.artistas.update_many({}, {"$unset": {"similares": ""}})


def process_place(
    places_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> None:
    """Procesa e ingesta lugares en MongoDB y Neo4j de forma modular.

    Args:
        places_list: Lista de diccionarios con datos de lugares.
        db_mongo: Instancia de base de datos de MongoDB (opcional).
        driver_neo4j: Driver de conexión a Neo4j (opcional).
    """
    if not places_list or db_mongo is None:
        return
    db_mongo.lugares.delete_many({})
    db_mongo.lugares.insert_many([dict(p) for p in places_list])

    if driver_neo4j is not None:
        with driver_neo4j.session(database="neo4j") as session:
            session.run(
                """
                UNWIND $lugares AS l
                MERGE (lug:Lugar {id: l.lugar_id})
                ON CREATE SET lug.nombre = l.nombre, lug.ciudad = l.ciudad, lug.capacidad = l.capacidad
                """,
                lugares=places_list,
            )


def process_event(
    events_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Procesa e ingesta eventos en MongoDB y Neo4j de forma modular.

    Args:
        events_list: Lista de diccionarios con datos de eventos.
        db_mongo: Instancia de base de datos de MongoDB (opcional).
        driver_neo4j: Driver de conexión a Neo4j (opcional).
        redis_client: Cliente de conexión a Redis (opcional).
    """
    if not events_list or db_mongo is None:
        return
    db_mongo.eventos.delete_many({})
    db_mongo.eventos.insert_many([dict(e) for e in events_list])

    if driver_neo4j is not None:
        with driver_neo4j.session(database="neo4j") as session:
            session.run(
                """
                UNWIND $eventos AS e
                MERGE (ev:Evento {id: e.evento_id})
                ON CREATE SET ev.nombre = e.nombre, ev.fecha = e.fecha, ev.genero = e.genero,
                              ev.precio = e.precio, ev.cupo = e.cupo, ev.estado = e.estado
                """,
                eventos=events_list,
            )
            session.run(
                """
                UNWIND $eventos AS e
                MATCH (ev:Evento {id: e.evento_id})
                MATCH (lug:Lugar {id: e.lugar_id})
                MERGE (ev)-[:SE_REALIZA_EN]->(lug)
                """,
                eventos=events_list,
            )
            session.run(
                """
                UNWIND $eventos AS e
                UNWIND e.artistas AS art_id
                MATCH (art:Artista {id: art_id})
                MATCH (ev:Evento {id: e.evento_id})
                MERGE (art)-[:PARTICIPA_EN]->(ev)
                """,
                eventos=events_list,
            )

        db_mongo.eventos.update_many({}, {"$unset": {"artistas": ""}})


def process_sale(
    sales_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Procesa e ingesta compras en MongoDB y Neo4j de forma modular.

    Args:
        sales_list: Lista de diccionarios con datos de compras.
        db_mongo: Instancia de base de datos de MongoDB (opcional).
        driver_neo4j: Driver de conexión a Neo4j (opcional).
        redis_client: Cliente de conexión a Redis (opcional).
    """
    if not sales_list or db_mongo is None:
        return
    db_mongo.compras.delete_many({})
    db_mongo.compras.insert_many([dict(s) for s in sales_list])

    if driver_neo4j is not None:
        with driver_neo4j.session(database="neo4j") as session:
            session.run(
                """
                UNWIND $compras AS c
                MATCH (user:Usuario {id: c.usuario_id})
                MATCH (ev:Evento {id: c.evento_id})
                MERGE (user)-[r:COMPRO {compra_id: c.compra_id}]->(ev)
                ON CREATE SET r.cantidad = c.cantidad,
                              r.precio_unitario = c.precio_unitario,
                              r.total = c.total,
                              r.fecha_compra = c.fecha_compra,
                              r.estado = c.estado
                """,
                compras=sales_list,
            )


# ==============================================================================
# CONSIGNAS: Sección 1 - Orquestación Completa del Pipeline de Carga Inicial
# ==============================================================================


def process_dataset(
    filepath: Union[str, Path],
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
    online_users: Optional[list[Union[int, str]]] = None,
    unconfirmed_reservations: Optional[list[dict[str, Any]]] = None,
    genre_searches: Optional[dict[str, int]] = None,
) -> None:
    """Coordina el flujo completo de persistencia políglota.

    Ejecuta las etapas en orden:
    1. Carga cruda del dataset en MongoDB como base principal.
    2. Creación de índices y restricciones en MongoDB y Neo4j.
    3. Construcción del grafo en Neo4j a partir de los datos en MongoDB.
    4. Sanitización de colecciones en MongoDB eliminando atributos relacionales duplicados.
    5. Inicialización de estado en tiempo real (stock, sesiones, reservas y búsquedas) en Redis.

    Args:
        filepath: Ruta hacia el archivo .txt con el conjunto de datos.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.
        online_users: Lista opcional de identificadores o nombres de usuarios conectados inicialmente.
        unconfirmed_reservations: Lista opcional de diccionarios con reservas iniciales sin confirmar.
        genre_searches: Diccionario opcional con búsquedas acumuladas iniciales por género.
    """
    print("\n--- INICIANDO CARGA POLÍGLOTA DEL DATASET ---")

    # 1. Cargar archivo crudo
    raw_data = load_raw_dataset(filepath)

    # 2. Insertar primero en MongoDB (fuente de verdad)
    print("\n[Paso 1] Insertando datos crudos en MongoDB...")
    insert_raw_data_to_mongo(raw_data, db_mongo)

    # 3. Restricciones e índices
    print("\n[Paso 2] Creando índices y restricciones...")
    create_mongo_indexes(db_mongo)
    create_neo4j_constraints(driver_neo4j)

    # 4. Poblar Neo4j a partir de lo guardado en MongoDB
    print("\n[Paso 3] Poblando grafo de Neo4j a partir de MongoDB...")
    populate_neo4j_from_mongo(db_mongo, driver_neo4j)

    # 5. Sanitizar MongoDB (eliminar campos relacionales duplicados)
    print("\n[Paso 4] Sanitizando MongoDB (eliminando listas relacionales)...")
    sanitize_mongo_collections(db_mongo)

    # 6. Poblar Redis con estado inicial
    print("\n[Paso 5] Inicializando estados efímeros y stock en Redis...")
    populate_redis_initial_state(
        db_mongo,
        redis_client,
        online_users=online_users,
        unconfirmed_reservations=unconfirmed_reservations,
        genre_searches=genre_searches,
    )

    print("\n--- CARGA POLÍGLOTA FINALIZADA CON ÉXITO ---\n")
