import os
from pathlib import Path
from typing import Any, Optional

# Directorios del proyecto (dentro del contenedor /work)
SRC_DIR: Path = Path(os.path.abspath(__file__)).resolve().parent  # /work/src
PROJECT_DIR: Path = SRC_DIR.parent                                 # /work
DATA_DIR: Path = PROJECT_DIR / "data"

# Ruta a datos provistos por la cátedra
DATASET_PATH: Path = DATA_DIR / "dataset.txt"
RUTA_DATASET: Path = DATASET_PATH  # Alias para compatibilidad

# Configuración de credenciales de servicios
CREDENTIALS: dict[str, str] = {
    "NEO4J_USER": os.getenv("NEO4J_USER", "neo4j"),
    "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", "neo4j123"),
    "MONGO_USER": os.getenv("MONGO_INITDB_ROOT_USERNAME", "admin"),
    "MONGO_PASS": os.getenv("MONGO_INITDB_ROOT_PASSWORD", "admin123"),
    "REDIS_PASSWORD": os.getenv("REDIS_PASSWORD", "redis123"),
}
USUARIOS: dict[str, str] = CREDENTIALS  # Alias para compatibilidad

# Mapeo de atributos que corresponden a relaciones de grafos (no a documentos en MongoDB)
RELATION_MAPPINGS: dict[str, tuple[str, ...]] = {
    "USUARIOS_R": ("amigos", "sigue"),
    "ARTISTAS_R": ("similares",),
    "LUGARES_R": (),
    "EVENTOS_R": ("artistas",),
    "COMPRAS_R": (),
}
MAPEO_RELACIONES: dict[str, tuple[str, ...]] = RELATION_MAPPINGS  # Alias para compatibilidad

# Reglas de negocio y constantes temporales
REFERENCE_DATE: str = "2026-10-01"
FECHA_REFERENCIA: str = REFERENCE_DATE  # Alias para compatibilidad

SESSION_TTL_SECONDS: int = 1800        # 30 minutos
RESERVATION_TTL_SECONDS: int = 600     # 10 minutos
SEARCH_CACHE_TTL_SECONDS: int = 300    # 5 minutos

# Estado inicial para Redis definido en las consignas del trabajo
INITIAL_ONLINE_USERS: list[str] = [
    "Sofía Martínez",
    "Juan López",
    "Tomás Herrera",
]

INITIAL_UNCONFIRMED_RESERVATIONS: list[dict[str, Any]] = [
    {"user_name": "Lucía Romero", "event_id": 5, "quantity": 2},
    {"user_name": "Tomás Herrera", "event_id": 4, "quantity": 3},
]

INITIAL_GENRE_SEARCHES: dict[str, int] = {
    "rock": 7,
    "electrónica": 5,
    "folk": 3,
    "cumbia": 2,
}


# Parámetros y URIs de conexión a los motores NoSQL
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "Recitales")
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
MONGO_URI: str = os.getenv(
    "MONGO_URI",
    f"mongodb://{CREDENTIALS['MONGO_USER']}:{CREDENTIALS['MONGO_PASS']}@mongo:27017/",
)
REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))


def wait_for_services(seconds: int = 5) -> None:
    """Pausa la ejecución para dar tiempo a que los servicios de Docker inicialicen.

    Args:
        seconds: Cantidad de segundos a esperar antes de continuar. Por defecto 5.
    """
    import time
    print(f"Esperando servicios ({seconds}s)...")
    time.sleep(seconds)


def get_mongo_client(uri: Optional[str] = None) -> Any:
    """Instancia y retorna un cliente conectado a MongoDB.

    Args:
        uri: URI opcional de conexión a MongoDB. Por defecto usa MONGO_URI.

    Returns:
        Instancia de MongoClient conectada.
    """
    from pymongo import MongoClient
    connection_uri = uri if uri is not None else MONGO_URI
    return MongoClient(connection_uri)


def get_mongo_db(db_name: Optional[str] = None, uri: Optional[str] = None) -> Any:
    """Obtiene y retorna la instancia de base de datos de MongoDB.

    Args:
        db_name: Nombre opcional de la base de datos. Por defecto usa MONGO_DB_NAME.
        uri: URI opcional de conexión a MongoDB. Por defecto usa MONGO_URI.

    Returns:
        Instancia de Database de PyMongo.
    """
    client = get_mongo_client(uri)
    target_name = db_name if db_name is not None else MONGO_DB_NAME
    return client[target_name]


def get_neo4j_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Any:
    """Instancia y retorna el driver de conexión a Neo4j.

    Args:
        uri: URI opcional de conexión Bolt. Por defecto usa NEO4J_URI.
        user: Usuario opcional de Neo4j. Por defecto usa CREDENTIALS['NEO4J_USER'].
        password: Password opcional de Neo4j. Por defecto usa CREDENTIALS['NEO4J_PASSWORD'].

    Returns:
        Instancia de Driver de Neo4j.
    """
    from neo4j import GraphDatabase
    target_uri = uri if uri is not None else NEO4J_URI
    target_user = user if user is not None else CREDENTIALS["NEO4J_USER"]
    target_password = password if password is not None else CREDENTIALS["NEO4J_PASSWORD"]
    return GraphDatabase.driver(target_uri, auth=(target_user, target_password))


def get_redis_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
) -> Any:
    """Instancia y retorna un cliente de conexión a Redis con decode_responses activado.

    Args:
        host: Host opcional de Redis. Por defecto usa REDIS_HOST.
        port: Puerto opcional de Redis. Por defecto usa REDIS_PORT.
        password: Password opcional de Redis. Por defecto usa CREDENTIALS['REDIS_PASSWORD'].

    Returns:
        Instancia de redis.Redis conectada y lista para operar.
    """
    import redis
    target_host = host if host is not None else REDIS_HOST
    target_port = port if port is not None else REDIS_PORT
    target_password = password if password is not None else CREDENTIALS["REDIS_PASSWORD"]
    return redis.Redis(
        host=target_host,
        port=target_port,
        password=target_password,
        decode_responses=True,
    )
