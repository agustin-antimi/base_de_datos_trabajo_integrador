"""Módulo para la ejecución genérica y modular de consultas políglotas.

Provee funciones desacopladas para ejecutar consultas sobre Neo4j (Cypher),
MongoDB (agregaciones y búsquedas) y Redis (comandos en memoria) sin hardcodear
sentencias de dominio dentro de los módulos de estadísticas o visualización.
"""

import json
from typing import Any, Callable, Optional, Union
import redis
from neo4j import Driver
from pymongo.database import Database
from config import REFERENCE_DATE




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


def get_friends_following_same_artists(
    driver: Driver,
    user_name: str = "Juan López",
) -> list[dict[str, Any]]:
    """Obtiene amigos de un usuario que siguen al menos a un artista en común.
    Args:
        driver: Driver de conexión a Neo4j.
        user_name: Nombre completo del usuario objetivo. Por defecto 'Juan López'.
    Returns:
        Lista de diccionarios conteniendo 'amigo_nombre' y 'artista_nombre'.
    """
    query = """
    MATCH (u:Usuario)-[:AMIGO_DE]->(amigo:Usuario)-[:SIGUE]->(a:Artista)<-[:SIGUE]-(u)
    WHERE u.nombre = $user_name
    RETURN 
        amigo.nombre AS amigo_nombre,
        a.nombre AS artista_nombre
    ORDER BY amigo_nombre ASC, artista_nombre ASC
    """
    return execute_neo4j_query(driver, query=query, parameters={"user_name": user_name})


def recommend_artists_from_friends(
    driver: Driver,
    user_name: str = "Juan López",
) -> list[dict[str, Any]]:
    """Recomienda a un usuario artistas que siguen sus amigos pero que él aún no sigue.

    Los resultados se ordenan de forma descendente según la cantidad de amigos
    que siguen a cada artista recomendado (filtro colaborativo social).

    Args:
        driver: Driver de conexión a Neo4j.
        user_name: Nombre del usuario objetivo. Por defecto 'Juan López'.

    Returns:
        Lista de diccionarios con 'artista_id', 'artista_nombre', 'genero',
        'cantidad_amigos_seguidores' y 'amigos_que_siguen'.
    """
    query = """
    MATCH (u:Usuario)-[:AMIGO_DE]->(amigo:Usuario)-[:SIGUE]->(art:Artista)
    WHERE u.nombre = $user_name
      AND NOT (u)-[:SIGUE]->(art)
    RETURN 
        art.id AS artista_id,
        art.nombre AS artista_nombre,
        art.genero AS genero,
        count(DISTINCT amigo) AS cantidad_amigos_seguidores,
        collect(DISTINCT amigo.nombre) AS amigos_que_siguen
    ORDER BY cantidad_amigos_seguidores DESC, artista_nombre ASC
    """
    return execute_neo4j_query(driver, query=query, parameters={"user_name": user_name})


def get_future_events_for_artists(
    driver: Driver,
    artists: Union[list[int], list[str], list[dict[str, Any]]],
    redis_client: Optional[redis.Redis] = None,
    reference_date: str = REFERENCE_DATE,
) -> list[dict[str, Any]]:
    """Obtiene los eventos futuros de un conjunto de artistas integrando Neo4j y Redis.

    Recupera del grafo en Neo4j los eventos programados con sus recintos y ciudades,
    y enriquece cada evento con el stock de entradas disponibles en tiempo real desde Redis.

    Args:
        driver: Driver de conexión a Neo4j.
        artists: Lista de identificadores (int), nombres (str) o diccionarios retornados
            por la consulta de recomendación (con clave 'artista_id' o 'artista_nombre').
        redis_client: Cliente opcional de Redis para inyectar las entradas disponibles vigentes.
        reference_date: Fecha de referencia ISO para filtrar eventos futuros (por defecto 2026-10-01).

    Returns:
        Lista de diccionarios con 'artista', 'evento', 'lugar', 'ciudad',
        'fecha', 'precio' y 'entradas_disponibles'.
    """
    if not artists:
        return []

    # Extraer identificadores o nombres según la estructura provista
    first_item = artists[0]
    if isinstance(first_item, dict):
        artist_ids = [int(item["artista_id"]) for item in artists if "artista_id" in item]
        artist_names = [str(item["artista_nombre"]) for item in artists if "artista_nombre" in item]
    elif isinstance(first_item, int):
        artist_ids = [int(i) for i in artists]
        artist_names = []
    else:
        artist_ids = []
        artist_names = [str(i) for i in artists]

    if artist_ids:
        artist_filter = "art.id IN $artist_ids"
    else:
        artist_filter = "art.nombre IN $artist_names"

    query = f"""
    MATCH (art:Artista)-[:PARTICIPA_EN]->(ev:Evento)-[:SE_REALIZA_EN]->(lug:Lugar)
    WHERE {artist_filter}
      AND ev.fecha >= $ref_date
      AND ev.estado = 'activo'
    RETURN 
        art.nombre AS artista,
        ev.id AS evento_id,
        ev.nombre AS evento,
        lug.nombre AS lugar,
        lug.ciudad AS ciudad,
        ev.fecha AS fecha,
        ev.precio AS precio
    ORDER BY ev.fecha ASC, ev.nombre ASC
    """
    params = {
        "artist_ids": artist_ids,
        "artist_names": artist_names,
        "ref_date": reference_date,
    }
    raw_events = execute_neo4j_query(driver, query=query, parameters=params)

    # Enriquecer con disponibilidad en tiempo real desde Redis
    results: list[dict[str, Any]] = []
    for item in raw_events:
        ev_id = item["evento_id"]
        available_stock = None
        if redis_client is not None:
            stock_str = redis_client.get(f"event:{ev_id}:stock")
            available_stock = int(stock_str) if stock_str is not None else 0

        results.append({
            "artista": item["artista"],
            "evento": item["evento"],
            "lugar": item["lugar"],
            "ciudad": item["ciudad"],
            "fecha": item["fecha"],
            "precio": item["precio"],
            "entradas_disponibles": available_stock,
        })

    return results


def get_similar_artists_not_followed(
    driver: Driver,
    user_name: str = "Lucía Romero",
) -> list[dict[str, Any]]:
    """Encuentra artistas similares a los que sigue un usuario, excluyendo los que ya sigue.

    Aplica un filtro de recomendación basado en contenido en el grafo de Neo4j navegando
    a través de la relación de similitud (:SIMILAR_A) entre bandas o solistas.

    Args:
        driver: Driver de conexión a Neo4j.
        user_name: Nombre completo del usuario objetivo. Por defecto 'Lucía Romero'.

    Returns:
        Lista de diccionarios con 'artista_id', 'artista_nombre', 'genero' y
        'similar_a_artistas_que_sigue'.
    """
    query = """
    MATCH (u:Usuario)-[:SIGUE]->(art:Artista)-[:SIMILAR_A]->(sim:Artista)
    WHERE u.nombre = $user_name
      AND NOT (u)-[:SIGUE]->(sim)
    RETURN 
        sim.id AS artista_id,
        sim.nombre AS artista_nombre,
        sim.genero AS genero,
        collect(DISTINCT art.nombre) AS similar_a_artistas_que_sigue
    ORDER BY artista_nombre ASC
    """
    return execute_neo4j_query(driver, query=query, parameters={"user_name": user_name})


def get_future_events_by_city_and_price(
    driver: Driver,
    city: str = "La Plata",
    max_price: float = 40000.0,
    reference_date: str = REFERENCE_DATE,
) -> list[dict[str, Any]]:
    """Consulta en Neo4j eventos futuros en una ciudad con precio menor al umbral especificado.

    Traza la relación espacial (:SE_REALIZA_EN) entre el Evento y el Lugar filtrando
    por ciudad, fecha y rango de precio.

    Args:
        driver: Driver de conexión a Neo4j.
        city: Ciudad donde se realiza el evento. Por defecto 'La Plata'.
        max_price: Precio máximo de la entrada (excluyente). Por defecto 40000.0.
        reference_date: Fecha de corte ISO para eventos futuros. Por defecto 2026-10-01.

    Returns:
        Lista de diccionarios con 'evento_id', 'evento_nombre', 'lugar_nombre',
        'ciudad', 'fecha', 'precio' y 'genero'.
    """
    query = """
    MATCH (ev:Evento)-[:SE_REALIZA_EN]->(lug:Lugar)
    WHERE lug.ciudad = $city
      AND ev.fecha >= $ref_date
      AND ev.precio < $max_price
      AND ev.estado = 'activo'
    RETURN 
        ev.id AS evento_id,
        ev.nombre AS evento_nombre,
        lug.nombre AS lugar_nombre,
        lug.ciudad AS ciudad,
        ev.fecha AS fecha,
        ev.precio AS precio,
        ev.genero AS genero
    ORDER BY ev.fecha ASC, ev.precio ASC
    """
    parameters = {
        "city": city,
        "max_price": max_price,
        "ref_date": reference_date,
    }
    return execute_neo4j_query(driver, query=query, parameters=parameters)


def count_future_events_by_genre(
    db_mongo: Database,
    reference_date: str = REFERENCE_DATE,
) -> list[dict[str, Any]]:
    """Agrupa y cuenta los eventos futuros por género musical utilizando MongoDB.

    Aplica el aggregation framework de MongoDB sobre la colección 'eventos'
    filtrando aquellos cuya fecha es mayor o igual a la de referencia.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        reference_date: Fecha de corte en formato ISO (YYYY-MM-DD). Por defecto 2026-10-01.

    Returns:
        Lista de diccionarios con 'genero', 'cantidad_eventos' y la lista de 'eventos'.
    """
    pipeline = [
        {
            "$match": {
                "fecha": {"$gte": reference_date},
                "estado": "activo",
            }
        },
        {
            "$group": {
                "_id": "$genero",
                "cantidad_eventos": {"$sum": 1},
                "eventos": {"$push": "$nombre"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "genero": "$_id",
                "cantidad_eventos": 1,
                "eventos": 1,
            }
        },
        {"$sort": {"cantidad_eventos": -1, "genero": 1}},
    ]
    return execute_mongo_aggregation(db_mongo, collection_name="eventos", pipeline=pipeline)


def get_total_spent_by_user(
    db_mongo: Database,
    purchase_status: str = "confirmada",
) -> list[dict[str, Any]]:
    """Calcula el monto total gastado por cada usuario en compras confirmadas en MongoDB.

    Agrupa la colección 'compras' por usuario, acumula el total facturado y cruza
    mediante $lookup con la colección 'usuarios' para obtener el nombre de cada persona.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        purchase_status: Estado de la compra a contabilizar. Por defecto 'confirmada'.

    Returns:
        Lista de diccionarios con 'usuario_id', 'usuario_nombre', 'total_gastado' y
        'cantidad_compras', ordenada de mayor a menor gasto.
    """
    pipeline = [
        {"$match": {"estado": purchase_status}},
        {
            "$group": {
                "_id": "$usuario_id",
                "total_gastado": {"$sum": "$total"},
                "cantidad_compras": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "usuarios",
                "localField": "_id",
                "foreignField": "usuario_id",
                "as": "usuario",
            }
        },
        {"$unwind": "$usuario"},
        {
            "$project": {
                "_id": 0,
                "usuario_id": "$_id",
                "usuario_nombre": "$usuario.nombre",
                "total_gastado": 1,
                "cantidad_compras": 1,
            }
        },
        {"$sort": {"total_gastado": -1, "usuario_nombre": 1}},
    ]
    return execute_mongo_aggregation(db_mongo, collection_name="compras", pipeline=pipeline)


def get_tickets_sold_per_event(
    db_mongo: Database,
) -> list[dict[str, Any]]:
    """Calcula las entradas vendidas por evento en MongoDB, incluyendo eventos con 0 ventas.

    Inicia la agregación en la colección 'eventos' y realiza un $lookup correlacionado
    hacia 'compras' filtrando exclusivamente las confirmadas. Si un evento no registra
    ventas, la suma sobre el arreglo vacío devuelve 0 de manera transparente.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.

    Returns:
        Lista de diccionarios con 'evento_id', 'evento_nombre', 'entradas_vendidas'
        y 'total_recaudado', ordenada de mayor a menor cantidad vendida.
    """
    pipeline = [
        {
            "$lookup": {
                "from": "compras",
                "let": {"eid": "$evento_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$evento_id", "$$eid"]},
                                    {"$eq": ["$estado", "confirmada"]},
                                ]
                            }
                        }
                    }
                ],
                "as": "compras_confirmadas",
            }
        },
        {
            "$project": {
                "_id": 0,
                "evento_id": 1,
                "evento_nombre": "$nombre",
                "entradas_vendidas": {"$sum": "$compras_confirmadas.cantidad"},
                "total_recaudado": {"$sum": "$compras_confirmadas.total"},
            }
        },
        {"$sort": {"entradas_vendidas": -1, "evento_id": 1}},
    ]
    return execute_mongo_aggregation(db_mongo, collection_name="eventos", pipeline=pipeline)


def get_online_users(
    redis_client: redis.Redis,
    db_mongo: Optional[Database] = None,
) -> list[dict[str, Any]]:
    """Obtiene los usuarios con sesión activa en este momento consultando Redis.

    Escanea las claves de sesión ('session:user:*') en Redis, recupera su tiempo de vida
    restante (TTL) y opcionalmente enriquece los datos del usuario con MongoDB.

    Args:
        redis_client: Cliente de conexión a Redis.
        db_mongo: Instancia opcional de MongoDB para resolver nombres si no están en la sesión.

    Returns:
        Lista de diccionarios con 'usuario_id', 'usuario_nombre', 'ttl_segundos'
        y 'minutos_restantes', ordenada por identificador de usuario.
    """
    online_users: list[dict[str, Any]] = []
    for raw_key in redis_client.scan_iter("session:user:*"):
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
        user_id_str = key.split(":")[-1]
        try:
            user_id = int(user_id_str)
        except ValueError:
            continue

        ttl = redis_client.ttl(key)
        raw_val = redis_client.get(key)
        if isinstance(raw_val, bytes):
            raw_val = raw_val.decode("utf-8")

        user_name = None
        if raw_val:
            try:
                data = json.loads(raw_val)
                user_name = (
                    data.get("usuario_nombre")
                    or data.get("user_name")
                    or data.get("nombre")
                )
            except (json.JSONDecodeError, TypeError):
                pass

        if not user_name and db_mongo is not None:
            user_doc = db_mongo.usuarios.find_one({"usuario_id": user_id})
            if user_doc:
                user_name = user_doc.get("nombre")

        online_users.append({
            "usuario_id": user_id,
            "usuario_nombre": user_name or f"Usuario {user_id}",
            "estado": "activa",
            "ttl_segundos": max(0, ttl),
            "minutos_restantes": round(max(0, ttl) / 60, 1),
        })

    online_users.sort(key=lambda x: x["usuario_id"])
    return online_users


def get_active_reservations(
    redis_client: redis.Redis,
    db_mongo: Optional[Database] = None,
) -> list[dict[str, Any]]:
    """Consulta en Redis las reservas vigentes con su tiempo restante de vencimiento.

    Escanea las claves de reserva ('reservation:*'), excluyendo el contador de secuencia,
    y obtiene el usuario, evento, cantidad de entradas y tiempo restante (TTL).

    Args:
        redis_client: Cliente de conexión a Redis.
        db_mongo: Instancia opcional de MongoDB para enriquecer nombres si faltasen.

    Returns:
        Lista de diccionarios con 'reserva_id', 'usuario', 'evento', 'cantidad',
        'ttl_segundos' y 'tiempo_restante' (formateado).
    """
    active_reservations: list[dict[str, Any]] = []

    for raw_key in redis_client.scan_iter("reservation:*"):
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
        if key == "reservation:next_id":
            continue

        raw_val = redis_client.get(key)
        if not raw_val:
            continue
        if isinstance(raw_val, bytes):
            raw_val = raw_val.decode("utf-8")

        ttl = redis_client.ttl(key)
        if ttl <= 0:
            continue

        try:
            data = json.loads(raw_val)
        except (json.JSONDecodeError, TypeError):
            continue

        res_id = data.get("reservation_id")
        if res_id is None:
            try:
                res_id = int(key.split(":")[-1])
            except ValueError:
                res_id = 0

        user_name = data.get("usuario_nombre") or data.get("usuario") or data.get("user_name")
        user_id = data.get("usuario_id")
        if not user_name and user_id is not None and db_mongo is not None:
            user_doc = db_mongo.usuarios.find_one({"usuario_id": user_id})
            if user_doc:
                user_name = user_doc.get("nombre")

        event_name = data.get("evento_nombre") or data.get("evento") or data.get("event_name")
        event_id = data.get("evento_id")
        if not event_name and event_id is not None and db_mongo is not None:
            ev_doc = db_mongo.eventos.find_one({"evento_id": event_id})
            if ev_doc:
                event_name = ev_doc.get("nombre")

        minutes = ttl // 60
        seconds = ttl % 60
        active_reservations.append({
            "reserva_id": res_id,
            "usuario": user_name or f"Usuario {user_id}",
            "evento": event_name or f"Evento {event_id}",
            "cantidad": int(data.get("cantidad", 0)),
            "ttl_segundos": ttl,
            "tiempo_restante": f"{minutes}m {seconds:02d}s",
        })

    active_reservations.sort(key=lambda x: x["reserva_id"])
    return active_reservations


def get_top_searched_genres(
    redis_client: redis.Redis,
    top_n: int = 3,
    key: str = "searches:genre",
) -> list[dict[str, Any]]:
    """Obtiene los géneros musicales más buscados consultando un Sorted Set en Redis.

    Aprovecha la estructura de datos ZSET (Skip List en memoria) de Redis para
    recuperar los elementos con mayor puntuación en tiempo O(log(N) + M) mediante ZREVRANGE.

    Args:
        redis_client: Cliente de conexión a Redis.
        top_n: Cantidad de géneros a retornar en el ranking. Por defecto 3.
        key: Clave del Sorted Set en Redis. Por defecto 'searches:genre'.

    Returns:
        Lista de diccionarios con 'puesto', 'genero' y 'cantidad_busquedas',
        ordenada de mayor a menor frecuencia.
    """
    if top_n <= 0:
        return []

    # ZREVRANGE devuelve tuplas (miembro, score) ordenadas descendentemente
    raw_results = redis_client.zrevrange(key, 0, top_n - 1, withscores=True)

    top_genres: list[dict[str, Any]] = []
    for rank, (genre, score) in enumerate(raw_results, start=1):
        genre_name = genre.decode("utf-8") if isinstance(genre, bytes) else str(genre)
        top_genres.append({
            "puesto": rank,
            "genero": genre_name,
            "cantidad_busquedas": int(score),
        })

    return top_genres





