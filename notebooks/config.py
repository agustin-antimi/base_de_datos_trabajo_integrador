import os, time
from pathlib import Path

BASE_DIR = Path(os.path.abspath(__file__)).resolve().parent

#Ruta a datos provistos por la cátedra:
RUTA_DATASET = BASE_DIR / "dataset.txt"

# CONFIGURACION DE USUARIOS Y CONTRASEÑAS:
USUARIOS = {
    "NEO4J_USER": os.getenv("NEO4J_USER", "neo4j"),
    "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", "neo4j123"),
    "MONGO_USER": os.getenv("MONGO_INITDB_ROOT_USERNAME", "admin"),
    "MONGO_PASS": os.getenv("MONGO_INITDB_ROOT_PASSWORD", "admin123"),
    "REDIS_PASSWORD": os.getenv("REDIS_PASSWORD", "redis123"),
}

print("Esperando servicios (5s)...")
time.sleep(5)


MAPEO_RELACIONES = {
    "USUARIOS_R":("amigos","sigue"),
    "ARTISTAS_R":("similares",),
    "LUGARES_R":(),
    "EVENTOS_R":(),
    "COMPRAS_R":()
}
