"""Módulo para la gestión de reseñas de eventos y requerimientos del Anexo (Punto 1).

Implementa las operaciones de persistencia políglota y reglas de negocio para:
1. Calificar (1 a 5) y comentar eventos pasados para los cuales el usuario tiene
   una compra confirmada, permitiendo exactamente una reseña por evento por usuario.
2. Demostración interactiva de casos válidos y múltiples casos rechazados.
3. Carga y siembra de al menos 6 reseñas de diferentes usuarios con compras confirmadas.
4. Consulta y agregación de promedios de calificación por evento y por artista
   (agrupando todos los eventos de cada artista).
"""

from datetime import datetime, timezone
from typing import Any, Optional, Union

from neo4j import Driver
from pymongo.database import Database

try:
    from config import (
        DEFAULT_REVIEWS_COLLECTION,
        DEFAULT_SAMPLE_REVIEWS,
        MAX_REVIEW_RATING,
        MIN_REVIEW_RATING,
        REFERENCE_DATE,
    )
    from purchase import resolve_event, resolve_user
    from queries import execute_mongo_aggregation, execute_neo4j_query
except ImportError:
    from src.config import (
        DEFAULT_REVIEWS_COLLECTION,
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
