import os
from pathlib import Path
import socket
from typing import Any, Optional

# Directorios del proyecto (dentro del contenedor /work)
SRC_DIR: Path = Path(os.path.abspath(__file__)).resolve().parent  # /work/src
PROJECT_DIR: Path = SRC_DIR.parent                                 # /work
DATA_DIR: Path = PROJECT_DIR / "data"

def _resolve_dataset_path() -> Path:
    """Localiza dinámicamente la ruta al archivo dataset.txt en entornos local o Docker.

    Returns:
        Instancia de Path apuntando a dataset.txt existente o por defecto en data/.
    """
    candidates = [
        DATA_DIR / "dataset.txt",
        PROJECT_DIR / "dataset.txt",
        Path.cwd() / "data" / "dataset.txt",
        Path.cwd() / "dataset.txt",
        Path.cwd().parent / "data" / "dataset.txt",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return DATA_DIR / "dataset.txt"


# Ruta a datos provistos por la cátedra
DATASET_PATH: Path = _resolve_dataset_path()
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

# Parámetros y valores por defecto para la sección 5 (Modificaciones)
DEFAULT_PRICE_INCREASE_PERCENTAGE: float = 10.0
DEFAULT_PRICE_INCREASE_CITY: str = "Rosario"
DEFAULT_SERVICE_NAME: str = "accesibilidad"
DEFAULT_SERVICE_PLACE_ID: int = 2
DEFAULT_CANCEL_EVENT_ID: int = 7
DEFAULT_DELETE_USER_NAME: str = "Tomás Herrera"
DEFAULT_DELETE_USER_ID: int = 6
DEFAULT_REMOVE_FRIENDS_USER_NAME: str = "Juan López"
DEFAULT_REMOVE_FRIENDS_USER_ID: int = 2


def _is_running_in_docker() -> bool:
    """Verifica si el proceso actual se ejecuta dentro de un contenedor Docker.

    Returns:
        True si se detecta el entorno Docker, False en caso contrario.
    """
    if os.name == "nt":
        return False
    return (
        os.path.exists("/.dockerenv")
        or os.path.exists("/run/.containerenv")
        or (Path("/work").exists() and not Path("C:/").exists())
    )


_DOCKER_HOST_MAPPINGS: dict[str, str] = {
    "mongo": "localhost",
    "class-mongo": "localhost",
    "neo4j": "localhost",
    "class-neo4j": "localhost",
    "redis": "localhost",
    "class-redis": "localhost",
}

_orig_getaddrinfo = socket.getaddrinfo
_orig_gethostbyname = socket.gethostbyname


def _patch_socket_for_docker_hosts() -> None:
    """Instala hooks en socket para redirigir hosts de Docker a localhost si no resuelven.

    Permite que el código que referencia explícitamente a 'mongo', 'neo4j' o 'redis'
    funcione transparentemente tanto en la máquina anfitriona (host Windows) como
    dentro de los contenedores Docker.
    """
    if _is_running_in_docker():
        return

    def _normalize_host_str(target: Any) -> str:
        if isinstance(target, bytes):
            return target.decode("utf-8", errors="ignore").lower()
        if isinstance(target, str):
            return target.lower()
        return ""

    def _fallback_getaddrinfo(
        host: Any,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        try:
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        except OSError:
            host_key = _normalize_host_str(host)
            if host_key in _DOCKER_HOST_MAPPINGS:
                fallback_host = _DOCKER_HOST_MAPPINGS[host_key]
                return _orig_getaddrinfo(fallback_host, port, family, type, proto, flags)
            raise

    def _fallback_gethostbyname(hostname: Any) -> str:
        try:
            return _orig_gethostbyname(hostname)
        except OSError:
            host_key = _normalize_host_str(hostname)
            if host_key in _DOCKER_HOST_MAPPINGS:
                fallback_host = _DOCKER_HOST_MAPPINGS[host_key]
                return _orig_gethostbyname(fallback_host)
            raise

    socket.getaddrinfo = _fallback_getaddrinfo
    socket.gethostbyname = _fallback_gethostbyname


_patch_socket_for_docker_hosts()


def _resolve_default_host(service_name: str) -> str:
    """Determina si debe usarse el hostname interno de Docker o localhost para el host anfitrión.

    Args:
        service_name: Nombre del servicio dentro de la red Docker (ej. 'mongo', 'neo4j', 'redis').

    Returns:
        service_name si corre en Docker o si el host resuelve nativamente, de lo contrario 'localhost'.
    """
    if _is_running_in_docker():
        return service_name
    try:
        _orig_gethostbyname(service_name)
        return service_name
    except OSError:
        return "localhost"


DEFAULT_MONGO_HOST: str = _resolve_default_host("mongo")
DEFAULT_NEO4J_HOST: str = _resolve_default_host("neo4j")
DEFAULT_REDIS_HOST: str = _resolve_default_host("redis")

MONGO_HOST: str = os.getenv("MONGO_HOST", DEFAULT_MONGO_HOST)
NEO4J_HOST: str = os.getenv("NEO4J_HOST", DEFAULT_NEO4J_HOST)
REDIS_HOST: str = os.getenv("REDIS_HOST", DEFAULT_REDIS_HOST)
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

# Parámetros y URIs de conexión a los motores NoSQL
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "Recitales")
NEO4J_URI: str = os.getenv("NEO4J_URI", f"bolt://{NEO4J_HOST}:7687")
MONGO_URI: str = os.getenv(
    "MONGO_URI",
    f"mongodb://{CREDENTIALS['MONGO_USER']}:{CREDENTIALS['MONGO_PASS']}@{MONGO_HOST}:27017/",
)

# Se inyectan los hosts resueltos en CREDENTIALS / USUARIOS para fácil acceso
CREDENTIALS["MONGO_HOST"] = MONGO_HOST
CREDENTIALS["NEO4J_HOST"] = NEO4J_HOST
CREDENTIALS["REDIS_HOST"] = REDIS_HOST


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
    if not _is_running_in_docker():
        if "@mongo:" in connection_uri or "//mongo:" in connection_uri:
            try:
                _orig_gethostbyname("mongo")
            except OSError:
                connection_uri = connection_uri.replace("@mongo:", "@localhost:").replace("//mongo:", "//localhost:")
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
    if not _is_running_in_docker():
        if "neo4j:" in target_uri or "@neo4j" in target_uri:
            try:
                _orig_gethostbyname("neo4j")
            except OSError:
                target_uri = target_uri.replace("neo4j:", "localhost:").replace("@neo4j", "@localhost")
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
    if not _is_running_in_docker() and target_host == "redis":
        try:
            _orig_gethostbyname("redis")
        except OSError:
            target_host = "localhost"
    target_port = port if port is not None else REDIS_PORT
    target_password = password if password is not None else CREDENTIALS["REDIS_PASSWORD"]
    return redis.Redis(
        host=target_host,
        port=target_port,
        password=target_password,
        decode_responses=True,
    )

