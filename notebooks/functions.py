import redis
from neo4j import Driver
from pymongo.database import Database


def clean_db(*bases):
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