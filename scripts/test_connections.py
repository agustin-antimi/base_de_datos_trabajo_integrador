"""Pruebas mínimas de conexión a Neo4j, MongoDB y Redis desde Python dentro del contenedor."""

try:
    from config import (
        get_mongo_client,
        get_neo4j_driver,
        get_redis_client,
        wait_for_services,
    )
except ImportError:
    from src.config import (
        get_mongo_client,
        get_neo4j_driver,
        get_redis_client,
        wait_for_services,
    )

# Esperar a que los servicios estén listos
wait_for_services(5)

# ---- Neo4j ----
driver = get_neo4j_driver()
with driver.session(database="neo4j") as session:
    session.run("CREATE (:City {name:$name})", name="La Plata")
    count = session.run("MATCH (n:City) RETURN count(n) AS c").single()["c"]
    print(f"[Neo4j] Nodos City: {count}")
driver.close()

# ---- MongoDB ----
client = get_mongo_client()
db = client["clase_test"]
db.alumnos.insert_one({"nombre": "Edu", "tema": "Grafos"})
print(f"[MongoDB] Documentos alumnos: {db.alumnos.count_documents({})}")
client.close()

# ---- Redis ----
redis_client = get_redis_client()
redis_client.set("saludo", "hola")
print(f"[Redis] Saludo = {redis_client.get('saludo')}")
