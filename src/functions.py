from pathlib import Path
from typing import Any, Optional, Union

import redis
from neo4j import Driver
from pymongo.database import Database

try:
    from config import MAPEO_RELACIONES
except ImportError:
    from src.config import MAPEO_RELACIONES


def clean_db(*bases: Union[Database, Driver, redis.Redis]) -> None:
    """Limpia las bases de datos específicas pasadas por parámetro."""
    for b in bases:
        # Caso MongoDB: recibe directamente el objeto Database
        if isinstance(b, Database):
            b.client.drop_database(b.name)
            print(f"MongoDB: base '{b.name}' eliminada.")

        # Caso Neo4j: recibe el driver y limpia la base del grafo
        elif isinstance(b, Driver):
            with b.session(database="neo4j") as session:
                session.run("MATCH (n) DETACH DELETE n")
            print("Neo4j: grafo limpiado.")

        # Caso Redis: recibe el cliente que ya apunta a la base actual
        elif isinstance(b, redis.Redis):
            b.flushdb()
            print("Redis: base limpiada.")

        else:
            print(f"Tipo no soportado: {type(b)}")

def process_user(
    users_list: list[dict[str, Any]],
    db_mongo: Database,
    driver_neo4j: Driver,
) -> None:
    """Procesa la lista de usuarios y almacena los valores de cada registro en la base de datos correspondiente."""
    print("Se procesarán los usuarios:")
    if not users_list:
        return

    mongo_docs: list[dict[str, Any]] = []
    
    #Se procesan los usuarios dejando los documentos para insertar en mongo:
    for u in users_list:
        doc = {k: v for k, v in u.items() if k not in MAPEO_RELACIONES["USUARIOS_R"]}
        mongo_docs.append(doc)        
    
    #Se insertarán los documentos en la colección de usuarios:
    db_mongo.usuarios.insert_many(mongo_docs)
    print(f"MongoDB: {len(mongo_docs)} usuarios insertados.")

    #Se crean los nodos con los ID de los usuarios, posteriormente se crean las relaciones y se carga en NEO4J:
    with driver_neo4j.session(database="neo4j") as session:
            # Paso 2.1: Crear los nodos únicamente con su id
            query_nodos = """
            UNWIND $usuarios AS u
            MERGE (:Usuario {id: u.usuario_id})
            """
            session.run(query_nodos, usuarios=users_list)
    
            # Paso 2.2: Crear relaciones de amistad a partir de los IDs
            query_amigos = """
            UNWIND $usuarios AS u
            UNWIND u.amigos AS amigo_id
            MATCH (origen:Usuario {id: u.usuario_id})
            MATCH (destino:Usuario {id: amigo_id})
            MERGE (origen)-[:AMIGO_DE]->(destino)
            """
            session.run(query_amigos, usuarios=users_list)
    
            # Paso 2.3: Crear relaciones de seguimiento a partir de los IDs
            query_sigue = """
            UNWIND $usuarios AS u
            UNWIND u.sigue AS seguido_id
            MATCH (origen:Usuario {id: u.usuario_id})
            MATCH (destino:Usuario {id: seguido_id})
            MERGE (origen)-[:SIGUE]->(destino)
            """
            session.run(query_sigue, usuarios=users_list)
    
    print("Neo4j: Nodos (solo IDs) y relaciones creados con éxito.")

    print("Usuarios procesados exitosamente")

    
def process_artist(
    artists_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> None:
    """Procesa la lista de artistas y almacena los valores de cada registro en la base de datos correspondiente."""
    print("Se procesan artistas")


def process_place(
    places_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
) -> None:
    """Procesa la lista de lugares y almacena los valores de cada registro en la base de datos correspondiente."""
    print("Se procesan lugares")


def process_event(
    events_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Procesa la lista de eventos y almacena los valores de cada registro en la base de datos correspondiente."""
    print("Se procesan eventos")


def process_sale(
    sales_list: list[dict[str, Any]],
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Procesa la lista de ventas y almacena los valores de cada registro en la base de datos correspondiente."""
    print("Se procesan ventas")


def load_raw_dataset(filepath: Union[str, Path]) -> dict[str, Any]:
    """Lee el archivo .txt de datos y devuelve un diccionario con las listas."""
    scope: dict[str, Any] = {}
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    exec(code, {}, scope)
    return scope


def process_dataset(
    filepath: Union[str, Path],
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
) -> None:
    """Carga el archivo y procesa los registros de cada entidad."""
    data = load_raw_dataset(filepath)
    print(data)
    process_user(data.get("usuarios", []), db_mongo, driver_neo4j)
    process_artist(data.get("artistas", []), db_mongo, driver_neo4j)
    process_place(data.get("lugares", []), db_mongo)
    process_event(data.get("eventos", []), db_mongo, driver_neo4j, redis_client)
    process_sale(data.get("compras", []), db_mongo, driver_neo4j, redis_client)
    print("Archivo procesado correctamente")
