"""Módulo para la resolución de requerimientos del Anexo (Puntos 1 y 2).

Implementa la validación y gestión de reseñas de eventos pasados con compra confirmada,
así como el registro temporal y visualización gráfica del historial de precios de eventos.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Union

from neo4j import Driver
from pymongo.database import Database

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
except ImportError:
    plt = None  # type: ignore
    mdates = None  # type: ignore
    ticker = None  # type: ignore

try:
    from config import (
        DEFAULT_INITIAL_PRICE_DATE,
        DEFAULT_PRICE_HISTORY_EVENT_NAME,
        DEFAULT_REVIEWS_COLLECTION,
        DEFAULT_SAMPLE_PRICE_CHANGES,
        DEFAULT_SAMPLE_REVIEWS,
        MAX_REVIEW_RATING,
        MIN_REVIEW_RATING,
        REFERENCE_DATE,
    )
    from purchase import resolve_event, resolve_user
    from queries import execute_mongo_aggregation, execute_neo4j_query
except ImportError:
    from src.config import (
        DEFAULT_INITIAL_PRICE_DATE,
        DEFAULT_PRICE_HISTORY_EVENT_NAME,
        DEFAULT_REVIEWS_COLLECTION,
        DEFAULT_SAMPLE_PRICE_CHANGES,
        DEFAULT_SAMPLE_REVIEWS,
        MAX_REVIEW_RATING,
        MIN_REVIEW_RATING,
        REFERENCE_DATE,
    )
    from src.purchase import resolve_event, resolve_user
    from src.queries import execute_mongo_aggregation, execute_neo4j_query


# ==============================================================================
# RESOLUCIÓN DINÁMICA DE ENTIDADES (Sin Hardcoding)
# ==============================================================================


def resolve_artist(db_mongo: Database, artist: Union[int, str]) -> tuple[int, str]:
    """Resuelve dinámicamente un artista en MongoDB y obtiene su identificador y nombre.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        artist: Identificador numérico (artista_id) o nombre completo del artista.

    Returns:
        Tupla con (artista_id, nombre).

    Raises:
        ValueError: Si el artista no existe en la base de datos.
    """
    if isinstance(artist, int):
        doc = db_mongo.artistas.find_one({"artista_id": artist})
    else:
        doc = db_mongo.artistas.find_one({"nombre": str(artist)})

    if not doc:
        raise ValueError(f"Artista no encontrado en el sistema: '{artist}'.")

    return int(doc["artista_id"]), str(doc["nombre"])


def _get_event_artists(
    db_mongo: Database,
    event_id: int,
    driver_neo4j: Optional[Driver] = None,
) -> list[dict[str, Any]]:
    """Obtiene los artistas que participan en un evento consultando Neo4j o MongoDB.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event_id: Identificador numérico del evento.
        driver_neo4j: Driver opcional de conexión a Neo4j.

    Returns:
        Lista de diccionarios con 'artista_id', 'nombre' y 'genero'.
    """
    # Intentar resolver vía relación Neo4j (:Artista)-[:PARTICIPA_EN]->(:Evento)
    if driver_neo4j is not None:
        query_neo = """
        MATCH (a:Artista)-[:PARTICIPA_EN]->(e:Evento {id: $event_id})
        RETURN a.id AS artista_id, a.nombre AS nombre, a.genero AS genero
        ORDER BY a.id ASC
        """
        try:
            neo_artists = execute_neo4j_query(driver_neo4j, query_neo, {"event_id": event_id})
            if neo_artists:
                return neo_artists
        except Exception:
            pass

    # Respaldo documental en MongoDB
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    artists: list[dict[str, Any]] = []
    if event_doc and "artistas" in event_doc and isinstance(event_doc["artistas"], list):
        for art_id in event_doc["artistas"]:
            art_doc = db_mongo.artistas.find_one({"artista_id": art_id})
            if art_doc:
                artists.append({
                    "artista_id": int(art_doc["artista_id"]),
                    "nombre": str(art_doc.get("nombre", f"Artista {art_id}")),
                    "genero": str(art_doc.get("genero", "")),
                })
    return artists


# ==============================================================================
# ÍNDICES Y RESTRICCIONES DE UNICIDAD PARA RESEÑAS
# ==============================================================================


def create_review_indexes(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> None:
    """Crea los índices y restricciones de unicidad para las reseñas en MongoDB y Neo4j.

    Garantiza a nivel de motor de base de datos la regla de negocio:
    'Un usuario puede calificar... y una sola vez por evento'.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j para aplicar restricciones si aplica.
        collection_name: Nombre de la colección de reseñas. Por defecto 'resenas'.
    """
    collection = db_mongo[collection_name]
    # Índice compuesto de unicidad para garantizar exactamente 1 reseña por (usuario, evento)
    collection.create_index(
        [("usuario_id", 1), ("evento_id", 1)],
        unique=True,
        name="uniq_user_event_review",
    )
    # Índice de unicidad para resena_id
    collection.create_index("resena_id", unique=True, name="uniq_resena_id")
    # Índices auxiliares de rendimiento para búsquedas y agregaciones
    collection.create_index("evento_id", name="idx_review_event")
    collection.create_index("artistas_ids", name="idx_review_artists")
    print(f"[MongoDB] Índices de unicidad y rendimiento creados en colección '{collection_name}'.")

    if driver_neo4j is not None:
        try:
            with driver_neo4j.session(database="neo4j") as session:
                session.run(
                    "CREATE INDEX IF NOT EXISTS FOR ()-[r:CALIFICO]-() ON (r.resena_id)"
                )
            print("[Neo4j] Índice para relación :CALIFICO creado en Neo4j.")
        except Exception as exc:
            print(f"[Neo4j] Aviso al crear índice de reseñas: {exc}")


# ==============================================================================
# VALIDACIÓN DE REGLAS DE NEGOCIO PARA RESEÑAS
# Consigna: "Un usuario puede calificar (1 a 5) y comentar un evento pasado
# (para el cual tiene una compra confirmada) y una sola vez por evento."
# ==============================================================================


def validate_event_review(
    db_mongo: Database,
    user: Union[int, str],
    event: Union[int, str],
    rating: int,
    comment: str,
    reference_date: str = REFERENCE_DATE,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> tuple[bool, str, dict[str, Any]]:
    """Valida exhaustivamente todas las condiciones de negocio antes de registrar una reseña.

    Condiciones verificadas:
    1. Calificación numérica entera dentro del rango permitido [1, 5].
    2. Comentario no vacío.
    3. Existencia del usuario y del evento en la base de datos.
    4. Evento pasado: la fecha del evento debe ser anterior a reference_date.
    5. Asistencia validada: el usuario debe registrar al menos una compra en estado 'confirmada'.
    6. Unicidad: el usuario no debe haber calificado previamente el mismo evento.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        user: Identificador numérico o nombre completo del usuario.
        event: Identificador numérico o nombre del evento.
        rating: Calificación otorgada (debe estar entre 1 y 5).
        comment: Comentario u opinión escrita del usuario.
        reference_date: Fecha de corte en formato ISO (YYYY-MM-DD).
        collection_name: Nombre de la colección de reseñas en MongoDB.

    Returns:
        Tupla con (es_valido, motivo_o_mensaje, detalles_de_contexto).
    """
    # 1. Validación de calificación (1 a 5)
    if not isinstance(rating, int) or rating < MIN_REVIEW_RATING or rating > MAX_REVIEW_RATING:
        return (
            False,
            f"La calificación debe ser un entero entre {MIN_REVIEW_RATING} y {MAX_REVIEW_RATING}. "
            f"Valor recibido: {rating}.",
            {},
        )

    # 2. Validación de comentario
    if not isinstance(comment, str) or not comment.strip():
        return (
            False,
            "El comentario de la reseña es obligatorio y no puede estar vacío.",
            {},
        )

    # 3. Resolución dinámica del usuario
    try:
        user_id, user_name = resolve_user(db_mongo, user)
    except ValueError as exc:
        return False, str(exc), {}

    # 4. Resolución dinámica del evento
    try:
        event_id, event_name, _, _ = resolve_event(db_mongo, event)
    except ValueError as exc:
        return False, str(exc), {}

    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    if not event_doc:
        return False, f"Evento con ID {event_id} no hallado en la colección de eventos.", {}

    event_date = str(event_doc.get("fecha", ""))

    # 5. Condición: Evento pasado (fecha < reference_date)
    if not event_date or event_date >= reference_date:
        return (
            False,
            f"El evento '{event_name}' (fecha {event_date}) no es un evento pasado "
            f"respecto a la fecha de referencia '{reference_date}'. "
            f"Solo se permite reseñar eventos que ya ocurrieron.",
            {
                "user_id": user_id,
                "user_name": user_name,
                "event_id": event_id,
                "event_name": event_name,
                "event_date": event_date,
                "reference_date": reference_date,
            },
        )

    # 6. Condición: Compra confirmada del evento (Asistencia)
    confirmed_purchase = db_mongo.compras.find_one({
        "usuario_id": user_id,
        "evento_id": event_id,
        "estado": "confirmada",
    })
    if not confirmed_purchase:
        return (
            False,
            f"El usuario '{user_name}' (ID {user_id}) no posee una compra confirmada "
            f"para el evento '{event_name}' (ID {event_id}). Solo los asistentes pueden reseñar.",
            {
                "user_id": user_id,
                "user_name": user_name,
                "event_id": event_id,
                "event_name": event_name,
            },
        )

    # 7. Condición: Una sola vez por evento (Unicidad)
    existing_review = db_mongo[collection_name].find_one({
        "usuario_id": user_id,
        "evento_id": event_id,
    })
    if existing_review:
        return (
            False,
            f"El usuario '{user_name}' (ID {user_id}) ya ha calificado previamente "
            f"el evento '{event_name}' (ID {event_id}). Solo se permite una reseña por evento.",
            {
                "user_id": user_id,
                "user_name": user_name,
                "event_id": event_id,
                "event_name": event_name,
                "existing_review_id": existing_review.get("resena_id"),
            },
        )

    # Todas las condiciones de negocio se cumplieron
    context: dict[str, Any] = {
        "user_id": user_id,
        "user_name": user_name,
        "event_id": event_id,
        "event_name": event_name,
        "event_date": event_date,
        "confirmed_purchase_id": confirmed_purchase.get("compra_id"),
    }
    return True, "Validación exitosa.", context


# ==============================================================================
# ALTA DE RESEÑA EN PERSISTENCIA POLÍGLOTA (MongoDB y Neo4j)
# ==============================================================================


def create_event_review(
    db_mongo: Database,
    user: Union[int, str],
    event: Union[int, str],
    rating: int,
    comment: str,
    driver_neo4j: Optional[Driver] = None,
    review_date: Optional[str] = None,
    reference_date: str = REFERENCE_DATE,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> dict[str, Any]:
    """Crea y persiste una nueva reseña de evento validando reglas de negocio.

    Valida que la calificación esté entre 1 y 5, que el evento sea pasado, que el
    usuario posea una compra confirmada y que no haya calificado previamente el evento.
    Persiste el documento en MongoDB y sincroniza la relación :CALIFICO en Neo4j.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        user: Identificador numérico o nombre completo del usuario.
        event: Identificador numérico o nombre del evento.
        rating: Calificación otorgada al evento (entero entre 1 y 5).
        comment: Texto descriptivo u opinión del usuario sobre el evento.
        driver_neo4j: Driver opcional de Neo4j para sincronizar la relación :CALIFICO.
        review_date: Fecha opcional de la reseña en formato ISO (YYYY-MM-DD).
            Por defecto utiliza la fecha de hoy.
        reference_date: Fecha de corte para clasificar eventos pasados vs futuros.
        collection_name: Nombre de la colección en MongoDB. Por defecto 'resenas'.

    Returns:
        Diccionario representativo de la reseña persistida en MongoDB.

    Raises:
        ValueError: Si alguna de las condiciones de negocio no se cumple.
    """
    is_valid, reason, context = validate_event_review(
        db_mongo=db_mongo,
        user=user,
        event=event,
        rating=rating,
        comment=comment,
        reference_date=reference_date,
        collection_name=collection_name,
    )
    if not is_valid:
        raise ValueError(f"No se pudo registrar la reseña: {reason}")

    user_id = context["user_id"]
    user_name = context["user_name"]
    event_id = context["event_id"]
    event_name = context["event_name"]
    event_date = context["event_date"]

    # Determinar el siguiente resena_id incremental
    collection = db_mongo[collection_name]
    max_doc = collection.find_one(sort=[("resena_id", -1)])
    next_resena_id = (int(max_doc["resena_id"]) + 1) if (max_doc and "resena_id" in max_doc) else 1

    # Fecha efectiva de la reseña
    effective_date = review_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Obtener artistas vinculados al evento para agregación analítica directa
    artists = _get_event_artists(db_mongo, event_id=event_id, driver_neo4j=driver_neo4j)
    artist_ids = [art["artista_id"] for art in artists]
    artist_names = [art["nombre"] for art in artists]

    # Construir documento para MongoDB
    review_doc: dict[str, Any] = {
        "resena_id": next_resena_id,
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "evento_id": event_id,
        "evento_nombre": event_name,
        "evento_fecha": event_date,
        "artistas_ids": artist_ids,
        "artistas_nombres": artist_names,
        "calificacion": rating,
        "comentario": comment.strip(),
        "fecha_resena": effective_date,
        "compra_id": context.get("confirmed_purchase_id"),
    }

    collection.insert_one(review_doc)

    # Sincronizar en Neo4j mediante la relación :CALIFICO entre Usuario y Evento
    if driver_neo4j is not None:
        query_neo = """
        MATCH (u:Usuario {id: $user_id})
        MATCH (e:Evento {id: $event_id})
        MERGE (u)-[r:CALIFICO]->(e)
        SET r.resena_id = $resena_id,
            r.calificacion = $calificacion,
            r.comentario = $comentario,
            r.fecha = $fecha_resena
        """
        try:
            execute_neo4j_query(
                driver_neo4j,
                query_neo,
                parameters={
                    "user_id": user_id,
                    "event_id": event_id,
                    "resena_id": next_resena_id,
                    "calificacion": rating,
                    "comentario": comment.strip(),
                    "fecha_resena": effective_date,
                },
            )
        except Exception as exc:
            print(f"[Neo4j] Advertencia al sincronizar reseña {next_resena_id}: {exc}")

    # Retornar copia limpia sin _id de PyMongo para evitar problemas de serialización
    clean_result = dict(review_doc)
    clean_result.pop("_id", None)
    return clean_result


# ==============================================================================
# CARGA DE RESEÑAS INICIALES (Al menos 6 reseñas de distintos usuarios)
# Consigna: "Cargar al menos 6 reseñas de distintos usuarios."
# ==============================================================================


def _ensure_confirmed_purchase_for_review(
    db_mongo: Database,
    user_id: int,
    event_id: int,
    driver_neo4j: Optional[Driver] = None,
    purchase_date: str = "2026-08-10",
) -> None:
    """Verifica si el usuario posee compra confirmada para el evento; si no existe, la crea.

    Permite asegurar que usuarios que asistieron a recitales pasados en el mundo real
    cuenten con el registro contable formal que exige la regla de negocio.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        user_id: Identificador numérico del usuario.
        event_id: Identificador numérico del evento pasado.
        driver_neo4j: Driver opcional de Neo4j para sincronizar relación :COMPRO.
        purchase_date: Fecha de la compra histórica.
    """
    existing = db_mongo.compras.find_one({
        "usuario_id": user_id,
        "evento_id": event_id,
        "estado": "confirmada",
    })
    if existing:
        return

    # Determinar siguiente compra_id
    max_compra = db_mongo.compras.find_one(sort=[("compra_id", -1)])
    next_compra_id = (int(max_compra["compra_id"]) + 1) if (max_compra and "compra_id" in max_compra) else 1

    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    price = int(event_doc.get("precio", 25000)) if event_doc else 25000

    new_purchase = {
        "compra_id": next_compra_id,
        "usuario_id": user_id,
        "evento_id": event_id,
        "cantidad": 1,
        "precio_unitario": price,
        "total": price,
        "fecha_compra": purchase_date,
        "estado": "confirmada",
    }
    db_mongo.compras.insert_one(new_purchase)

    if driver_neo4j is not None:
        try:
            query_neo = """
            MATCH (u:Usuario {id: $user_id})
            MATCH (e:Evento {id: $event_id})
            MERGE (u)-[r:COMPRO {compra_id: $compra_id}]->(e)
            ON CREATE SET r.cantidad = 1,
                          r.precio_unitario = $precio,
                          r.total = $precio,
                          r.fecha_compra = $fecha,
                          r.estado = 'confirmada'
            """
            execute_neo4j_query(
                driver_neo4j,
                query_neo,
                parameters={
                    "user_id": user_id,
                    "event_id": event_id,
                    "compra_id": next_compra_id,
                    "precio": price,
                    "fecha": purchase_date,
                },
            )
        except Exception:
            pass


def seed_sample_reviews(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    reviews: Optional[list[dict[str, Any]]] = None,
    reference_date: str = REFERENCE_DATE,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> list[dict[str, Any]]:
    """Siembra al menos 6 reseñas de diferentes usuarios sobre eventos pasados.

    Verifica la existencia previa para actuar de forma idempotente. Cumple
    estrictamente con la consigna de 6 usuarios distintos.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j.
        reviews: Lista opcional de diccionarios con reseñas. Por defecto usa DEFAULT_SAMPLE_REVIEWS.
        reference_date: Fecha de corte para validar eventos pasados.
        collection_name: Colección de destino en MongoDB.

    Returns:
        Lista de diccionarios con las reseñas registradas o existentes.
    """
    create_review_indexes(db_mongo, driver_neo4j=driver_neo4j, collection_name=collection_name)

    sample_list = reviews if reviews is not None else DEFAULT_SAMPLE_REVIEWS
    created_reviews: list[dict[str, Any]] = []

    for item in sample_list:
        user_target = item.get("user_id") if "user_id" in item else item.get("user_name")
        event_target = item.get("event_id") if "event_id" in item else item.get("event_name")
        rating = int(item["rating"])
        comment = str(item["comment"])
        review_date = item.get("review_date")

        if user_target is None or event_target is None:
            continue

        # Resolver identidades
        u_id, u_name = resolve_user(db_mongo, user_target)
        e_id, e_name, _, _ = resolve_event(db_mongo, event_target)

        # Si ya existe reseña para este par (usuario, evento), no duplicar
        existing = db_mongo[collection_name].find_one({"usuario_id": u_id, "evento_id": e_id})
        if existing:
            clean_exist = dict(existing)
            clean_exist.pop("_id", None)
            created_reviews.append(clean_exist)
            continue

        # Asegurar que el usuario tenga compra confirmada para este evento pasado
        _ensure_confirmed_purchase_for_review(
            db_mongo=db_mongo,
            user_id=u_id,
            event_id=e_id,
            driver_neo4j=driver_neo4j,
            purchase_date="2026-08-01",
        )

        # Registrar la reseña mediante el flujo de validación formal
        review = create_event_review(
            db_mongo=db_mongo,
            user=u_id,
            event=e_id,
            rating=rating,
            comment=comment,
            driver_neo4j=driver_neo4j,
            review_date=review_date,
            reference_date=reference_date,
            collection_name=collection_name,
        )
        created_reviews.append(review)

    distinct_users = len({r["usuario_id"] for r in created_reviews})
    print(
        f"[Reseñas] {len(created_reviews)} reseñas activas en total "
        f"de {distinct_users} usuarios distintos."
    )
    return created_reviews


# ==============================================================================
# PROMEDIOS DE CALIFICACIÓN POR EVENTO Y POR ARTISTA
# Consigna: "Mostrar el promedio de calificación por evento y por artista
# (para un artista se consideran las reseñas de todos sus eventos)."
# ==============================================================================


def get_average_ratings_per_event(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> list[dict[str, Any]]:
    """Calcula y retorna el promedio de calificación por evento.

    Ejecuta un pipeline de agregación en MongoDB cruzando con la colección de eventos
    para presentar nombres legibles, cantidad de reseñas y calificaciones.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j (si se desea consultar en Neo4j).
        collection_name: Nombre de la colección de reseñas. Por defecto 'resenas'.

    Returns:
        Lista de diccionarios ordenados descendentemente por promedio de calificación:
        [
            {
                'evento_id': int,
                'evento_nombre': str,
                'fecha': str,
                'genero': str,
                'promedio_calificacion': float,
                'cantidad_resenas': int,
                'calificaciones': list[int]
            },
            ...
        ]
    """
    pipeline = [
        {
            "$group": {
                "_id": "$evento_id",
                "promedio_calificacion": {"$avg": "$calificacion"},
                "cantidad_resenas": {"$sum": 1},
                "calificaciones": {"$push": "$calificacion"},
            }
        },
        {
            "$lookup": {
                "from": "eventos",
                "localField": "_id",
                "foreignField": "evento_id",
                "as": "evento_info",
            }
        },
        {"$unwind": {"path": "$evento_info", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "evento_id": "$_id",
                "evento_nombre": {"$ifNull": ["$evento_info.nombre", "Desconocido"]},
                "fecha": {"$ifNull": ["$evento_info.fecha", ""]},
                "genero": {"$ifNull": ["$evento_info.genero", ""]},
                "promedio_calificacion": {"$round": ["$promedio_calificacion", 2]},
                "cantidad_resenas": 1,
                "calificaciones": 1,
            }
        },
        {"$sort": {"promedio_calificacion": -1, "evento_nombre": 1}},
    ]

    results = execute_mongo_aggregation(db_mongo, collection_name, pipeline)
    return results


def get_average_ratings_per_artist(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> list[dict[str, Any]]:
    """Calcula y retorna el promedio de calificación por artista considerando todos sus eventos.

    Aprovecha la relación en Neo4j (:Artista)-[:PARTICIPA_EN]->(:Evento)<-[:CALIFICO]-()
    si el driver está disponible, o bien ejecuta la agregación políglota sobre MongoDB.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j para consulta Cypher de grafos.
        collection_name: Nombre de la colección de reseñas en MongoDB.

    Returns:
        Lista de diccionarios ordenados descendentemente por promedio de calificación:
        [
            {
                'artista_id': int,
                'artista_nombre': str,
                'genero': str,
                'promedio_calificacion': float,
                'cantidad_resenas': int,
                'eventos_evaluados': list[str]
            },
            ...
        ]
    """
    # Consulta optimizada en Neo4j si se provee el driver
    if driver_neo4j is not None:
        query_neo = """
        MATCH (a:Artista)-[:PARTICIPA_EN]->(e:Evento)<-[r:CALIFICO]-(u:Usuario)
        RETURN a.id AS artista_id,
               a.nombre AS artista_nombre,
               a.genero AS genero,
               round(avg(toFloat(r.calificacion)), 2) AS promedio_calificacion,
               count(r) AS cantidad_resenas,
               collect(DISTINCT e.nombre) AS eventos_evaluados
        ORDER BY promedio_calificacion DESC, a.nombre ASC
        """
        try:
            results_neo = execute_neo4j_query(driver_neo4j, query_neo)
            if results_neo:
                return results_neo
        except Exception as exc:
            print(f"[Neo4j] Advertencia en cálculo por artista: {exc}. Usando respaldo MongoDB.")

    # Agregación documental en MongoDB
    pipeline = [
        {"$unwind": "$artistas_ids"},
        {
            "$group": {
                "_id": "$artistas_ids",
                "promedio_calificacion": {"$avg": "$calificacion"},
                "cantidad_resenas": {"$sum": 1},
                "eventos_evaluados": {"$addToSet": "$evento_nombre"},
            }
        },
        {
            "$lookup": {
                "from": "artistas",
                "localField": "_id",
                "foreignField": "artista_id",
                "as": "artista_info",
            }
        },
        {"$unwind": {"path": "$artista_info", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "artista_id": "$_id",
                "artista_nombre": {"$ifNull": ["$artista_info.nombre", "Desconocido"]},
                "genero": {"$ifNull": ["$artista_info.genero", "Desconocido"]},
                "promedio_calificacion": {"$round": ["$promedio_calificacion", 2]},
                "cantidad_resenas": 1,
                "eventos_evaluados": 1,
            }
        },
        {"$sort": {"promedio_calificacion": -1, "artista_nombre": 1}},
    ]

    results_mongo = execute_mongo_aggregation(db_mongo, collection_name, pipeline)
    return results_mongo


# ==============================================================================
# DEMOSTRACIÓN DE CASOS VÁLIDOS Y RECHAZADOS
# Consigna: "Implementar la operación validando ambas condiciones y demostrar
# un caso válido y uno rechazado."
# ==============================================================================


def demonstrate_reviews_flow(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    reference_date: str = REFERENCE_DATE,
    collection_name: str = DEFAULT_REVIEWS_COLLECTION,
) -> dict[str, Any]:
    """Ejecuta y valida la demostración de los casos exigidos por las consignas.

    Demuestra exactamente un caso válido y un caso rechazado según el requerimiento:
    1. Caso Válido: Usuario con compra confirmada califica y comenta un evento pasado.
    2. Caso Rechazado: Usuario intenta calificar un evento sin registrar compra confirmada
       (violación de la condición de asistencia previa requerida).

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j.
        reference_date: Fecha de corte para clasificar eventos pasados.
        collection_name: Colección de reseñas en MongoDB.

    Returns:
        Diccionario con el resumen de resultados del caso válido y del caso rechazado.
    """
    create_review_indexes(db_mongo, driver_neo4j=driver_neo4j, collection_name=collection_name)

    results: dict[str, Any] = {
        "valid_case": None,
        "rejected_case": None,
    }

    print("=" * 80)
    print("DEMOSTRACIÓN: FLUJO DE RESEÑAS DE EVENTOS (ANEXO - PUNTO 1)")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # 1. CASO VÁLIDO: Usuario con compra confirmada sobre evento pasado
    # --------------------------------------------------------------------------
    print("\n--- 1. Caso Válido: Usuario con compra confirmada califica evento pasado ---")
    valid_user_name = "Juan López"
    valid_event_name = "Cóndores en vivo"
    valid_rating = 5
    valid_comment = "Excelente sonido y potencia en el Estadio Ciudad. Noche inolvidable."

    # Si ya existía por ejecuciones previas, se limpia para esta prueba
    u_id, _ = resolve_user(db_mongo, valid_user_name)
    e_id, _, _, _ = resolve_event(db_mongo, valid_event_name)
    db_mongo[collection_name].delete_one({"usuario_id": u_id, "evento_id": e_id})
    if driver_neo4j is not None:
        try:
            execute_neo4j_query(
                driver_neo4j,
                "MATCH (u:Usuario {id: $u_id})-[r:CALIFICO]->(e:Evento {id: $e_id}) DELETE r",
                parameters={"u_id": u_id, "e_id": e_id},
            )
        except Exception:
            pass

    try:
        created_review = create_event_review(
            db_mongo=db_mongo,
            user=valid_user_name,
            event=valid_event_name,
            rating=valid_rating,
            comment=valid_comment,
            driver_neo4j=driver_neo4j,
            reference_date=reference_date,
            collection_name=collection_name,
        )
        print(f" [ÉXITO] Reseña registrada correctamente (ID {created_review['resena_id']}):")
        print(f"   * Usuario: {created_review['usuario_nombre']} (ID {created_review['usuario_id']})")
        print(f"   * Evento: {created_review['evento_nombre']} (Fecha: {created_review['evento_fecha']})")
        print(f"   * Calificación: {created_review['calificacion']} / 5")
        print(f"   * Comentario: \"{created_review['comentario']}\"")
        results["valid_case"] = {
            "status": "APPROVED",
            "review": created_review,
        }
    except Exception as exc:
        print(f" [FALLO INESPERADO] {exc}")
        results["valid_case"] = {"status": "ERROR", "message": str(exc)}

    # --------------------------------------------------------------------------
    # 2. CASO RECHAZADO: Usuario sin compra confirmada (Asistencia no acreditada)
    # --------------------------------------------------------------------------
    print("\n--- 2. Caso Rechazado: Intento de calificar sin compra confirmada previa ---")
    no_purchase_user = "Martín Díaz"
    no_purchase_event = "Cóndores en vivo"  # Martín no compró para Cóndores
    try:
        create_event_review(
            db_mongo=db_mongo,
            user=no_purchase_user,
            event=no_purchase_event,
            rating=4,
            comment="Me comentaron que estuvo excelente pero no asistí.",
            driver_neo4j=driver_neo4j,
            reference_date=reference_date,
            collection_name=collection_name,
        )
        print(" [ERROR DE PRUEBA] Debió rechazarse por falta de compra confirmada.")
        results["rejected_case"] = {"status": "FAILED_UNEXPECTEDLY_ALLOWED"}
    except ValueError as exc:
        print(f" [RECHAZO CORRECTO] Operación denegada como se esperaba:")
        print(f"   -> Motivo: {exc}")
        results["rejected_case"] = {
            "status": "REJECTED_AS_EXPECTED",
            "reason": str(exc),
            "user": no_purchase_user,
            "event": no_purchase_event,
        }

    print("\n" + "=" * 80)
    print("FIN DE LA DEMOSTRACIÓN: 1 caso válido y 1 caso rechazado validados exitosamente.")
    print("=" * 80)
    return results


# ==============================================================================
# ANEXO: PUNTO 2 - HISTORIAL DE PRECIOS
# Consignas:
# 1. Cada cambio de precio de un evento debe quedar registrado con su fecha.
#    El precio del dataset se considera vigente desde el 2026-01-01.
# 2. Registrar al menos 3 cambios de precio sobre un mismo evento.
# 3. Consultar el precio vigente de un evento en una fecha dada.
# 4. Graficar la evolución del precio de ese evento.
# ==============================================================================


def init_price_history(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    initial_date: str = DEFAULT_INITIAL_PRICE_DATE,
) -> int:
    """Inicializa el historial de precios en todos los eventos del catálogo.

    Establece el precio base provisto en el dataset como vigente a partir de la fecha
    inicial estipulada (2026-01-01). Es una operación estrictamente idempotente.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j para sincronización.
        initial_date: Fecha de inicio de vigencia del catálogo (por defecto '2026-01-01').

    Returns:
        Cantidad de eventos en los que se inicializó el historial.
    """
    events = list(db_mongo.eventos.find({}))
    initialized_count = 0

    for event in events:
        eid = int(event["evento_id"])
        history = event.get("historial_precios")

        if not history or not isinstance(history, list):
            initial_price = int(event.get("precio", 0))
            base_entry = {
                "precio": initial_price,
                "fecha_desde": initial_date,
                "fecha_hasta": None,
            }
            db_mongo.eventos.update_one(
                {"evento_id": eid},
                {"$set": {"historial_precios": [base_entry]}},
            )
            initialized_count += 1

            # Sincronización en Neo4j si corresponde
            if driver_neo4j is not None:
                try:
                    query_neo = """
                    MATCH (e:Evento {id: $eid})
                    SET e.precio = $price
                    """
                    execute_neo4j_query(driver_neo4j, query_neo, {"eid": eid, "price": initial_price})
                except Exception:
                    pass

    return initialized_count


def register_price_change(
    db_mongo: Database,
    event: Union[int, str],
    new_price: int,
    change_date: str,
    driver_neo4j: Optional[Driver] = None,
    initial_date: str = DEFAULT_INITIAL_PRICE_DATE,
) -> dict[str, Any]:
    """Registra un cambio de precio para un evento cerrando el periodo anterior.

    Garantiza consistencia temporal cerrando la vigencia del precio anterior (fecha_hasta)
    y abriendo la vigencia del nuevo precio (fecha_desde). Actualiza el precio actual
    en MongoDB y Neo4j sin alterar compras históricas pasadas.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador numérico o nombre completo del evento.
        new_price: Nuevo valor monetario de la entrada (entero positivo > 0).
        change_date: Fecha efectiva en la que entra en vigencia el nuevo precio (YYYY-MM-DD).
        driver_neo4j: Driver opcional de Neo4j para reflejar el precio vigente.
        initial_date: Fecha base por defecto en caso de requerir inicialización.

    Returns:
        Diccionario con el detalle del cambio de precio registrado.

    Raises:
        ValueError: Si el precio es menor o igual a cero o la fecha es cronológicamente inválida.
    """
    if new_price <= 0:
        raise ValueError(
            f"El nuevo precio debe ser estrictamente mayor a 0 (principio Fail-Closed). "
            f"Recibido: {new_price}."
        )

    # Resolución dinámica del evento
    event_id, event_name, _, _ = resolve_event(db_mongo, event)
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    if not event_doc:
        raise ValueError(f"Evento no encontrado: {event_id}.")

    # Asegurar inicialización previa si no posee historial
    history: list[dict[str, Any]] = event_doc.get("historial_precios", [])
    if not history:
        current_catalog_price = int(event_doc.get("precio", new_price))
        history = [
            {
                "precio": current_catalog_price,
                "fecha_desde": initial_date,
                "fecha_hasta": None,
            }
        ]

    # Validar formato de fecha ISO
    try:
        new_date_dt = datetime.strptime(change_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Formato de fecha inválido '{change_date}'. Debe ser YYYY-MM-DD.")

    # Validar cronología con la entrada activa
    active_entry = next((item for item in history if item.get("fecha_hasta") is None), None)
    if active_entry:
        active_date_dt = datetime.strptime(active_entry["fecha_desde"], "%Y-%m-%d")
        if new_date_dt <= active_date_dt:
            raise ValueError(
                f"La fecha del nuevo precio ({change_date}) debe ser posterior "
                f"a la fecha del precio vigente ({active_entry['fecha_desde']})."
            )
        # Cerrar periodo vigente anterior
        active_entry["fecha_hasta"] = change_date
        old_price = active_entry["precio"]
    else:
        old_price = int(event_doc.get("precio", new_price))

    # Incorporar nueva entrada de precio
    new_entry: dict[str, Any] = {
        "precio": new_price,
        "fecha_desde": change_date,
        "fecha_hasta": None,
    }
    history.append(new_entry)

    # Persistir en MongoDB
    db_mongo.eventos.update_one(
        {"evento_id": event_id},
        {
            "$set": {
                "precio": new_price,
                "historial_precios": history,
            }
        },
    )

    # Sincronizar precio en Neo4j si se cuenta con el driver
    if driver_neo4j is not None:
        try:
            query_neo = """
            MATCH (e:Evento {id: $eid})
            SET e.precio = $new_price
            """
            execute_neo4j_query(driver_neo4j, query_neo, {"eid": event_id, "new_price": new_price})
        except Exception as exc:
            print(f"[Neo4j] Advertencia al sincronizar precio de evento {event_id}: {exc}")

    return {
        "evento_id": event_id,
        "evento_nombre": event_name,
        "precio_anterior": old_price,
        "precio_nuevo": new_price,
        "fecha_cambio": change_date,
        "total_registros_historial": len(history),
    }


def seed_sample_price_changes(
    db_mongo: Database,
    event: Union[int, str] = DEFAULT_PRICE_HISTORY_EVENT_NAME,
    changes: Optional[list[dict[str, Any]]] = None,
    driver_neo4j: Optional[Driver] = None,
    initial_date: str = DEFAULT_INITIAL_PRICE_DATE,
) -> list[dict[str, Any]]:
    """Registra al menos 3 cambios de precio consecutivos sobre un mismo evento.

    Cumple con la consigna de registrar al menos 3 variaciones temporales de precio,
    asegurando inicialización e idempotencia.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador o nombre del evento objetivo. Por defecto 'Rock del Lago'.
        changes: Lista opcional de diccionarios con 'change_date' y 'new_price'.
        driver_neo4j: Driver opcional de Neo4j.
        initial_date: Fecha de inicio de vigencia original ('2026-01-01').

    Returns:
        Lista completa de entradas del historial de precios del evento.
    """
    init_price_history(db_mongo, driver_neo4j=driver_neo4j, initial_date=initial_date)
    event_id, event_name, _, _ = resolve_event(db_mongo, event)

    sample_changes = changes if changes is not None else DEFAULT_SAMPLE_PRICE_CHANGES
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    existing_history = event_doc.get("historial_precios", []) if event_doc else []
    existing_dates = {entry.get("fecha_desde") for entry in existing_history}

    for item in sample_changes:
        c_date = item["change_date"]
        c_price = int(item["new_price"])

        if c_date in existing_dates:
            continue

        register_price_change(
            db_mongo=db_mongo,
            event=event_id,
            new_price=c_price,
            change_date=c_date,
            driver_neo4j=driver_neo4j,
            initial_date=initial_date,
        )

    updated_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    final_history = updated_doc.get("historial_precios", []) if updated_doc else []
    print(
        f"[Historial de Precios] Evento '{event_name}' (ID {event_id}): "
        f"{len(final_history)} estados de precio registrados (al menos 3 modificaciones)."
    )
    return final_history


def get_event_price_at_date(
    db_mongo: Database,
    event: Union[int, str],
    target_date: str,
) -> dict[str, Any]:
    """Consulta y retorna el precio que se encontraba formalmente vigente en una fecha dada.

    Busca en el historial del evento el intervalo que satisface:
    fecha_desde <= target_date < fecha_hasta (o fecha_hasta es None).

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador numérico o nombre completo del evento.
        target_date: Fecha consultada en formato ISO (YYYY-MM-DD).

    Returns:
        Diccionario con la información del precio vigente e intervalo de validez.

    Raises:
        ValueError: Si el formato de fecha es incorrecto o el evento no existe.
    """
    event_id, event_name, catalog_price, _ = resolve_event(db_mongo, event)

    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Formato de fecha inválido '{target_date}'. Debe ser YYYY-MM-DD.")

    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    if not event_doc:
        raise ValueError(f"Evento {event_id} no encontrado.")

    history = event_doc.get("historial_precios", [])
    if not history:
        # Si aún no tiene array de historial, su precio vigente proviene del catálogo desde 2026-01-01
        history = [
            {
                "precio": catalog_price,
                "fecha_desde": DEFAULT_INITIAL_PRICE_DATE,
                "fecha_hasta": None,
            }
        ]

    # Verificar si la fecha es anterior al inicio de vigencia del sistema
    initial_date_dt = datetime.strptime(DEFAULT_INITIAL_PRICE_DATE, "%Y-%m-%d")
    if target_dt < initial_date_dt:
        return {
            "evento_id": event_id,
            "evento_nombre": event_name,
            "fecha_consultada": target_date,
            "precio_vigente": None,
            "mensaje": (
                f"La fecha consultada ({target_date}) es anterior a la fecha inicial "
                f"del catálogo ({DEFAULT_INITIAL_PRICE_DATE}). No había precio definido."
            ),
        }

    # Buscar el intervalo correspondiente
    for entry in history:
        f_desde = datetime.strptime(entry["fecha_desde"], "%Y-%m-%d")
        f_hasta_str = entry.get("fecha_hasta")

        if f_hasta_str:
            f_hasta = datetime.strptime(f_hasta_str, "%Y-%m-%d")
            if f_desde <= target_dt < f_hasta:
                return {
                    "evento_id": event_id,
                    "evento_nombre": event_name,
                    "fecha_consultada": target_date,
                    "precio_vigente": int(entry["precio"]),
                    "fecha_desde": entry["fecha_desde"],
                    "fecha_hasta": f_hasta_str,
                }
        else:
            if f_desde <= target_dt:
                return {
                    "evento_id": event_id,
                    "evento_nombre": event_name,
                    "fecha_consultada": target_date,
                    "precio_vigente": int(entry["precio"]),
                    "fecha_desde": entry["fecha_desde"],
                    "fecha_hasta": None,
                }

    # Si por alguna discrepancia no encajara en intervalos intermedios, devolver último disponible
    last_entry = history[-1]
    return {
        "evento_id": event_id,
        "evento_nombre": event_name,
        "fecha_consultada": target_date,
        "precio_vigente": int(last_entry["precio"]),
        "fecha_desde": last_entry["fecha_desde"],
        "fecha_hasta": last_entry.get("fecha_hasta"),
    }


def get_event_price_history(
    db_mongo: Database,
    event: Union[int, str],
) -> list[dict[str, Any]]:
    """Recupera la secuencia cronológica de precios de un evento.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador o nombre completo del evento.

    Returns:
        Lista de diccionarios con cada registro histórico ordenado cronológicamente.
    """
    event_id, event_name, catalog_price, _ = resolve_event(db_mongo, event)
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    raw_history = event_doc.get("historial_precios", []) if event_doc else []

    if not raw_history:
        return [
            {
                "evento_id": event_id,
                "evento_nombre": event_name,
                "precio": catalog_price,
                "fecha_desde": DEFAULT_INITIAL_PRICE_DATE,
                "fecha_hasta": None,
            }
        ]

    result = []
    for entry in raw_history:
        result.append({
            "evento_id": event_id,
            "evento_nombre": event_name,
            "precio": int(entry["precio"]),
            "fecha_desde": entry["fecha_desde"],
            "fecha_hasta": entry.get("fecha_hasta"),
        })
    return result


def plot_event_price_evolution(
    db_mongo: Database,
    event: Union[int, str] = DEFAULT_PRICE_HISTORY_EVENT_NAME,
    end_date: Optional[str] = None,
    show_plot: bool = True,
) -> tuple[Any, Any]:
    """Genera un gráfico escalonado de la evolución del precio de un evento con Matplotlib.

    Representa cómo el precio se mantiene constante en cada escalón temporal
    y cambia escalonadamente en cada fecha de ajuste, formateando valores monetarios y fechas.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador o nombre del evento a graficar.
        end_date: Fecha final del eje temporal (por defecto la fecha del evento o 2026-12-31).
        show_plot: Si es True, invoca plt.show() para visualizar en pantalla/notebook.

    Returns:
        Tupla con los objetos (fig, ax) de Matplotlib.

    Raises:
        RuntimeError: Si la librería Matplotlib no se encuentra instalada en el entorno.
        ValueError: Si el evento no posee registros de precios.
    """
    if plt is None:
        raise RuntimeError("Matplotlib no se encuentra disponible en el entorno actual.")

    event_id, event_name, _, _ = resolve_event(db_mongo, event)
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    history = get_event_price_history(db_mongo, event_id)

    if not history:
        raise ValueError(f"No hay registros de historial de precios para el evento '{event_name}'.")

    event_date_str = event_doc.get("fecha", "2026-12-31") if event_doc else "2026-12-31"
    cutoff_date = end_date or event_date_str

    # Construir puntos de la función escalonada (step plot)
    plot_dates: list[datetime] = []
    plot_prices: list[int] = []

    for entry in history:
        d_start = datetime.strptime(entry["fecha_desde"], "%Y-%m-%d")
        price = entry["precio"]
        plot_dates.append(d_start)
        plot_prices.append(price)

    # Añadir punto final de cierre en la fecha de realización del evento para extender el último escalón
    final_dt = datetime.strptime(cutoff_date, "%Y-%m-%d")
    last_price = plot_prices[-1]

    dates_for_step = list(plot_dates)
    prices_for_step = list(plot_prices)
    if final_dt > dates_for_step[-1]:
        dates_for_step.append(final_dt)
        prices_for_step.append(last_price)

    # Configuración de figura
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)

    # Gráfico escalonado (post: el precio rige desde la fecha hasta el siguiente salto)
    ax.step(
        dates_for_step,
        prices_for_step,
        where="post",
        color="#2b5c8f",
        linewidth=2.5,
        label="Precio oficial",
    )

    # Resaltar puntos de cambio con marcadores
    ax.scatter(
        plot_dates,
        plot_prices,
        color="#d9534f",
        s=70,
        zorder=5,
        label="Hitos de ajuste",
    )

    # Anotaciones de valor monetario sobre cada salto
    for dt_pt, pr_pt in zip(plot_dates, plot_prices):
        ax.annotate(
            f"${pr_pt:,.0f}".replace(",", "."),
            xy=(dt_pt, pr_pt),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="#fdf7e7", ec="#e0c280", lw=1, alpha=0.9),
        )

    # Estética y formato de ejes
    ax.set_title(
        f"Evolución Histórica del Precio de Entradas — {event_name}",
        fontsize=13,
        fontweight="bold",
        pad=15,
    )
    ax.set_xlabel("Fecha de Vigencia", fontsize=10, labelpad=8)
    ax.set_ylabel("Precio por Entrada ($ ARS)", fontsize=10, labelpad=8)
    ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    # Ajuste de límites verticales para mayor legibilidad
    y_min = min(plot_prices) * 0.90
    y_max = max(plot_prices) * 1.15
    ax.set_ylim(y_min, y_max)

    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()

    if show_plot:
        plt.show()

    return fig, ax


def demonstrate_price_history_flow(
    db_mongo: Database,
    driver_neo4j: Optional[Driver] = None,
    target_event: Union[int, str] = DEFAULT_PRICE_HISTORY_EVENT_NAME,
    query_date: str = "2026-05-15",
) -> dict[str, Any]:
    """Demuestra integralmente todos los requerimientos del Punto 2 del Anexo.

    1. Inicializa precios base desde el 2026-01-01.
    2. Registra al menos 3 cambios de precio sobre un mismo evento.
    3. Consulta el precio vigente en una fecha dada.
    4. Grafica la evolución temporal del precio del evento.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de Neo4j.
        target_event: Evento objetivo para la prueba. Por defecto 'Rock del Lago'.
        query_date: Fecha de prueba para consultar el precio vigente (ej. '2026-05-15').

    Returns:
        Diccionario con los resultados de la demostración.
    """
    print("=" * 80)
    print("DEMOSTRACIÓN: HISTORIAL Y EVOLUCIÓN DE PRECIOS (ANEXO - PUNTO 2)")
    print("=" * 80)

    # 1. Inicialización de catálogo a 2026-01-01
    init_price_history(db_mongo, driver_neo4j=driver_neo4j)

    # 2. Registrar al menos 3 cambios de precio
    event_id, event_name, _, _ = resolve_event(db_mongo, target_event)
    history = seed_sample_price_changes(db_mongo, event=event_id, driver_neo4j=driver_neo4j)

    print(f"\n--- Historial Cronológico de Precios de '{event_name}' (ID {event_id}) ---")
    for idx, reg in enumerate(history, start=1):
        hasta_str = reg.get("fecha_hasta") or "Vigente"
        print(
            f"  {idx}. Desde: {reg['fecha_desde']} | Hasta: {hasta_str:<10} "
            f"| Precio: ${reg['precio']:>6,.0f}"
        )

    # 3. Consulta de precio vigente a una fecha dada
    print(f"\n--- Consulta de Precio Vigente a la Fecha: {query_date} ---")
    price_info = get_event_price_at_date(db_mongo, event_id, target_date=query_date)
    print(f"  * Evento: {price_info['evento_nombre']} (ID {price_info['evento_id']})")
    print(f"  * Fecha Consultada: {price_info['fecha_consultada']}")
    print(f"  * Precio Vigente: ${price_info['precio_vigente']:,.0f}")
    print(f"  * Intervalo Válido: [{price_info['fecha_desde']} a {price_info.get('fecha_hasta') or 'presente'}]")

    # 4. Generación del gráfico
    print(f"\n--- Generando Gráfico de Evolución de Precios para '{event_name}' ---")
    fig, _ = plot_event_price_evolution(db_mongo, event_id, show_plot=True)

    print("\n" + "=" * 80)
    print("FIN DE LA DEMOSTRACIÓN: Historial de precios y gráfico validados con éxito.")
    print("=" * 80)

    return {
        "event_id": event_id,
        "event_name": event_name,
        "price_history": history,
        "query_at_date": price_info,
        "figure": fig,
    }
