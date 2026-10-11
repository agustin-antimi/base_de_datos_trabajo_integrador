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
        MAPEO_RELACIONES,
        REFERENCE_DATE,
        SESSION_TTL_SECONDS,
        RESERVATION_TTL_SECONDS,
    )
except ImportError:
    from src.config import (
        MAPEO_RELACIONES,
        REFERENCE_DATE,
        SESSION_TTL_SECONDS,
        RESERVATION_TTL_SECONDS,
    )


def clean_db(*databases: Union[Database, Driver, redis.Redis]) -> None:
    """Limpia las bases de datos específicas pasadas por parámetro."""
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


def create_mongo_indexes(db_mongo: Database) -> None:
    """Crea los índices y restricciones de unicidad en las colecciones de MongoDB."""
    db_mongo.usuarios.create_index("usuario_id", unique=True)
    db_mongo.artistas.create_index("artista_id", unique=True)
    db_mongo.lugares.create_index("lugar_id", unique=True)
    db_mongo.eventos.create_index("evento_id", unique=True)
    db_mongo.compras.create_index("compra_id", unique=True)
    print("[MongoDB] Índices de unicidad creados en todas las colecciones.")


def create_neo4j_constraints(driver_neo4j: Driver) -> None:
    """Crea las restricciones de unicidad sobre los identificadores en Neo4j."""
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


def load_raw_dataset(filepath: Union[str, Path]) -> dict[str, Any]:
    """Lee el archivo .txt de datos y devuelve un diccionario con las entidades crudas."""
    scope: dict[str, Any] = {}
    path_obj = Path(filepath)
    if not path_obj.exists():
        raise FileNotFoundError(f"No se encontró el archivo de dataset en: {path_obj.resolve()}")

    with open(path_obj, "r", encoding="utf-8") as f:
        code = f.read()
    exec(code, {}, scope)
    return scope


def insert_raw_data_to_mongo(raw_data: dict[str, Any], db_mongo: Database) -> None:
    """Inserta el conjunto de datos completo y crudo en MongoDB como fuente de verdad inicial."""
    collections = ("usuarios", "artistas", "lugares", "eventos", "compras")
    for col_name in collections:
        items = raw_data.get(col_name, [])
        if items:
            collection = db_mongo[col_name]
            # Limpiar colección antes de insertar por si existían datos
            collection.delete_many({})
            collection.insert_many([dict(item) for item in items])
            print(f"[MongoDB] Colección '{col_name}': {len(items)} registros insertados.")


def populate_neo4j_from_mongo(db_mongo: Database, driver_neo4j: Driver) -> None:
    """Lee las entidades y relaciones almacenadas en MongoDB y construye el grafo en Neo4j."""
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


def sanitize_mongo_collections(db_mongo: Database) -> None:
    """Elimina de MongoDB los atributos relacionales que ya residen en Neo4j para evitar duplicación."""
    res_usuarios = db_mongo.usuarios.update_many({}, {"$unset": {"amigos": "", "sigue": ""}})
    res_artistas = db_mongo.artistas.update_many({}, {"$unset": {"similares": ""}})
    res_eventos = db_mongo.eventos.update_many({}, {"$unset": {"artistas": ""}})

    print(
        f"[MongoDB Sanitización] Campos relacionales removidos: "
        f"{res_usuarios.modified_count} usuarios, "
        f"{res_artistas.modified_count} artistas, "
        f"{res_eventos.modified_count} eventos."
    )


def populate_redis_initial_state(db_mongo: Database, redis_client: redis.Redis) -> None:
    """Inicializa en Redis el estado en tiempo real (cupos, sesiones activas, reservas y búsquedas)."""
    # 1. Cupos disponibles para eventos futuros
    # Regla: Disponibles = cupo - compras confirmadas - reservas vigentes
    initial_unconfirmed_reservations: dict[int, int] = {
        5: 2,  # Lucía Romero: 2 entradas para evento 5
        4: 3,  # Tomás Herrera: 3 entradas para evento 4
    }

    events = list(db_mongo.eventos.find({}, {"_id": 0}))
    for ev in events:
        eid = ev["evento_id"]
        confirmed_docs = db_mongo.compras.find({"evento_id": eid, "estado": "confirmada"})
        confirmed_tickets = sum(c.get("cantidad", 0) for c in confirmed_docs)
        reserved_tickets = initial_unconfirmed_reservations.get(eid, 0)
        available_stock = max(0, ev["cupo"] - confirmed_tickets - reserved_tickets)

        redis_client.set(f"event:{eid}:capacity", ev["cupo"])
        redis_client.set(f"event:{eid}:stock", available_stock)

    print(f"[Redis] Cupos y capacidades inicializadas para {len(events)} eventos.")

    # 2. Sesiones activas iniciales (TTL: 30 minutos = 1800 segundos)
    # Sofía Martínez (1), Juan López (2), Tomás Herrera (6)
    initial_online_users = [1, 2, 6]
    for uid in initial_online_users:
        session_payload = json.dumps({"user_id": uid, "status": "active"})
        redis_client.set(f"session:user:{uid}", session_payload, ex=SESSION_TTL_SECONDS)
    print(f"[Redis] {len(initial_online_users)} sesiones activas inicializadas (TTL 30m).")

    # 3. Reservas iniciales sin confirmar (TTL: 10 minutos = 600 segundos)
    res_1 = {
        "reservation_id": 1,
        "usuario_id": 3,
        "evento_id": 5,
        "cantidad": 2,
    }
    redis_client.set("reservation:1", json.dumps(res_1), ex=RESERVATION_TTL_SECONDS)

    res_2 = {
        "reservation_id": 2,
        "usuario_id": 6,
        "evento_id": 4,
        "cantidad": 3,
    }
    redis_client.set("reservation:2", json.dumps(res_2), ex=RESERVATION_TTL_SECONDS)
    redis_client.set("reservation:next_id", 3)
    print("[Redis] 2 reservas sin confirmar inicializadas (TTL 10m).")

    # 4. Historial de búsquedas iniciales por género
    initial_searches: dict[str, int] = {
        "rock": 7,
        "electrónica": 5,
        "folk": 3,
        "cumbia": 2,
    }
    redis_client.zadd("searches:genre", initial_searches)
    print("[Redis] Contadores de búsquedas por género registrados.")


def process_user(
    users_list: list[dict[str, Any]],
    db_mongo: Database,
    driver_neo4j: Driver,
) -> None:
    """Procesa e ingesta usuarios en MongoDB y Neo4j de forma modular."""
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
    """Procesa e ingesta artistas en MongoDB y Neo4j de forma modular."""
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
    """Procesa e ingesta lugares en MongoDB y Neo4j de forma modular."""
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
    """Procesa e ingesta eventos en MongoDB y Neo4j de forma modular."""
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
    """Procesa e ingesta compras en MongoDB y Neo4j de forma modular."""
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


def process_dataset(
    filepath: Union[str, Path],
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
) -> None:
    """Coordina el flujo completo de persistencia políglota:

    1. Carga cruda del dataset en MongoDB como base principal.
    2. Creación de índices y restricciones en MongoDB y Neo4j.
    3. Construcción del grafo en Neo4j a partir de los datos en MongoDB.
    4. Sanitización de colecciones en MongoDB eliminando atributos relacionales duplicados.
    5. Inicialización de estado en tiempo real (stock, sesiones, reservas y búsquedas) en Redis.
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
    populate_redis_initial_state(db_mongo, redis_client)

    print("\n--- CARGA POLÍGLOTA FINALIZADA CON ÉXITO ---\n")
