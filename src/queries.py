"""Módulo para la ejecución genérica y modular de consultas políglotas.

Provee funciones desacopladas para ejecutar consultas sobre Neo4j (Cypher),
MongoDB (agregaciones y búsquedas) y Redis (comandos en memoria) sin hardcodear
sentencias de dominio dentro de los módulos de estadísticas o visualización.
"""

from typing import Any, Callable, Optional, Union
import redis
from neo4j import Driver
from pymongo.database import Database


def execute_neo4j_query(
    driver: Driver,
    query: str,
    parameters: Optional[dict[str, Any]] = None,
    database: str = "neo4j",
) -> list[dict[str, Any]]:
    """Ejecuta una consulta Cypher parametrizada en Neo4j y retorna los registros como diccionarios.

    Args:
        driver: Driver de conexión a Neo4j.
        query: Sentencia Cypher a ejecutar.
        parameters: Diccionario opcional con parámetros para la consulta Cypher ($param).
        database: Nombre de la base de datos en Neo4j. Por defecto 'neo4j'.

    Returns:
        Lista de diccionarios con los registros retornados por la consulta.

    Raises:
        ValueError: Si la sentencia query está vacía.
    """
    if not query or not query.strip():
        raise ValueError("La consulta Cypher no puede ser vacía.")

    params = parameters or {}
    with driver.session(database=database) as session:
        result = session.run(query, **params)
        return [dict(record) for record in result]


def execute_mongo_aggregation(
    db_mongo: Database,
    collection_name: str,
    pipeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ejecuta un pipeline de agregación en una colección específica de MongoDB.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        collection_name: Nombre de la colección sobre la cual ejecutar la agregación.
        pipeline: Lista de etapas (stages) del pipeline de agregación de MongoDB.

    Returns:
        Lista de documentos resultantes de la agregación.

    Raises:
        ValueError: Si el nombre de la colección está vacío o el pipeline no es una lista.
    """
    if not collection_name or not collection_name.strip():
        raise ValueError("El nombre de la colección no puede ser vacío.")
    if not isinstance(pipeline, list):
        raise ValueError("El pipeline de agregación debe ser una lista de diccionarios.")

    collection = db_mongo[collection_name]
    cursor = collection.aggregate(pipeline)
    return [dict(doc) for doc in cursor]


def execute_mongo_find(
    db_mongo: Database,
    collection_name: str,
    filter_query: Optional[dict[str, Any]] = None,
    projection: Optional[dict[str, Any]] = None,
    sort: Optional[list[tuple[str, int]]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Ejecuta una búsqueda (find) en MongoDB con filtros, proyecciones y ordenamiento opcionales.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        collection_name: Nombre de la colección a consultar.
        filter_query: Diccionario de filtro de consulta. Por defecto {}.
        projection: Diccionario de proyección de campos (ej. {'_id': 0, 'nombre': 1}).
        sort: Lista opcional de tuplas para ordenamiento (ej. [('precio', -1)]).
        limit: Cantidad máxima opcional de documentos a retornar.

    Returns:
        Lista de documentos encontrados.
    """
    collection = db_mongo[collection_name]
    query = filter_query or {}
    cursor = collection.find(query, projection)

    if sort:
        cursor = cursor.sort(sort)
    if limit is not None and limit > 0:
        cursor = cursor.limit(limit)

    return [dict(doc) for doc in cursor]


def execute_redis_command(
    redis_client: redis.Redis,
    command_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Ejecuta un comando dinámico sobre el cliente de Redis.

    Args:
        redis_client: Cliente de conexión a Redis.
        command_name: Nombre del método o comando de Redis (ej. 'zrange', 'get', 'hgetall').
        *args: Argumentos posicionales a pasar al comando de Redis.
        **kwargs: Argumentos nombrados a pasar al comando de Redis.

    Returns:
        Resultado retornado por el comando de Redis ejecutado.

    Raises:
        AttributeError: Si el comando especificado no existe en el cliente de Redis.
    """
    command_method: Optional[Callable[..., Any]] = getattr(redis_client, command_name, None)
    if command_method is None or not callable(command_method):
        raise AttributeError(f"El cliente de Redis no dispone del método o comando '{command_name}'.")

    return command_method(*args, **kwargs)


def execute_query(
    client: Union[Driver, Database, redis.Redis],
    target: str,
    query_payload: Any = None,
    **kwargs: Any,
) -> Any:
    """Función despachadora políglota para ejecutar consultas según el tipo de cliente NoSQL.

    Args:
        client: Instancia de conexión (Driver de Neo4j, Database de MongoDB o Redis de redis-py).
        target: Especificación del objetivo según la base:
            - En Neo4j: Sentencia Cypher a ejecutar.
            - En MongoDB: Nombre de la colección objetivo.
            - En Redis: Nombre del comando a ejecutar (ej. 'zrange').
        query_payload: Carga de consulta opcional según la base:
            - En Neo4j: Diccionario de parámetros ($param).
            - En MongoDB: Pipeline de agregación (list) o filtro de búsqueda (dict).
            - En Redis: Primer argumento posicional del comando.
        **kwargs: Parámetros adicionales específicos del motor.

    Returns:
        Resultado estructurado devuelto por la consulta.

    Raises:
        TypeError: Si el tipo de cliente no es soportado.
    """
    if isinstance(client, Driver):
        params = query_payload if isinstance(query_payload, dict) else kwargs.get("parameters")
        database = kwargs.get("database", "neo4j")
        return execute_neo4j_query(client, query=target, parameters=params, database=database)

    if isinstance(client, Database):
        if isinstance(query_payload, list):
            return execute_mongo_aggregation(client, collection_name=target, pipeline=query_payload)
        filter_query = query_payload if isinstance(query_payload, dict) else {}
        return execute_mongo_find(
            client,
            collection_name=target,
            filter_query=filter_query,
            projection=kwargs.get("projection"),
            sort=kwargs.get("sort"),
            limit=kwargs.get("limit"),
        )

    if isinstance(client, redis.Redis):
        args = [query_payload] if query_payload is not None else []
        extra_args = kwargs.get("args", ())
        if isinstance(extra_args, (list, tuple)):
            args.extend(extra_args)
        command_kwargs = {k: v for k, v in kwargs.items() if k != "args"}
        return execute_redis_command(client, target, *args, **command_kwargs)

    raise TypeError(f"Tipo de cliente NoSQL no soportado: {type(client)}")


from typing import Any, Optional
from neo4j import Driver
from config import REFERENCE_DATE
from queries import execute_neo4j_query


def get_users_attending_artist_events(
    driver: Driver,
    artist_name: str,
    only_past: bool = True,
    reference_date: str = REFERENCE_DATE,
) -> list[dict[str, Any]]:
    """Consulta en Neo4j los usuarios con compras confirmadas para eventos de un artista.

    Args:
        driver: Driver de conexión a Neo4j.
        artist_name: Nombre del artista a buscar (resuelto dinámicamente).
        only_past: Si es True, filtra únicamente eventos pasados respecto a la fecha de referencia.
        reference_date: Fecha de corte en formato ISO (YYYY-MM-DD).

    Returns:
        Lista de diccionarios con el id, nombre de usuario, evento y fecha.
    """
    date_filter = "AND e.fecha < $ref_date" if only_past else ""
    query = f"""
    MATCH (u:Usuario)-[c:COMPRO]->(e:Evento)<-[:PARTICIPA_EN]-(a:Artista)
    WHERE a.nombre = $artist_name
      AND c.estado = 'confirmada'
      {date_filter}
    RETURN DISTINCT 
        u.id AS usuario_id,
        u.nombre AS usuario_nombre,
        e.nombre AS evento_nombre,
        e.fecha AS evento_fecha,
        c.cantidad AS entradas_compradas
    ORDER BY u.id ASC
    """
    parameters = {
        "artist_name": artist_name,
        "ref_date": reference_date,
    }
    return execute_neo4j_query(driver, query=query, parameters=parameters)
