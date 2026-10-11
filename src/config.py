import os
from pathlib import Path

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


def wait_for_services(seconds: int = 5) -> None:
    """Pausa la ejecución para dar tiempo a que los servicios de Docker inicialicen."""
    import time
    print(f"Esperando servicios ({seconds}s)...")
    time.sleep(seconds)
