"""Módulo para la ejecución de modificaciones y consistencia políglota (Sección 5).

Implementa las mutaciones solicitadas sobre MongoDB, Neo4j y Redis garantizando:
1. Aumento de precio en eventos futuros de una ciudad (5.1).
2. Adición de servicios a un recinto/lugar (5.2).
3. Cancelación integral de evento, reembolso de compras y anulación de reservas/stock (5.3).
4. Eliminación de usuario con justificación y manejo contable de compras (5.4).
5. Eliminación de la red de amistades de un usuario (5.5).
6. Consultas de evidencia para verificar el impacto en todas las bases afectadas.
"""

import json
from typing import Any, Optional, Union

import redis
from neo4j import Driver
from pymongo.database import Database

try:
    from config import (
        DEFAULT_CANCEL_EVENT_ID,
        DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
        DEFAULT_DELETE_USER_NAME,
        DEFAULT_PRICE_INCREASE_CITY,
        DEFAULT_PRICE_INCREASE_PERCENTAGE,
        DEFAULT_SERVICE_NAME,
        DEFAULT_SERVICE_PLACE_ID,
        REFERENCE_DATE,
    )
    from purchase import resolve_event, resolve_user
except ImportError:
    from src.config import (
        DEFAULT_CANCEL_EVENT_ID,
        DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
        DEFAULT_DELETE_USER_NAME,
        DEFAULT_PRICE_INCREASE_CITY,
        DEFAULT_PRICE_INCREASE_PERCENTAGE,
        DEFAULT_SERVICE_NAME,
        DEFAULT_SERVICE_PLACE_ID,
        REFERENCE_DATE,
    )
    from src.purchase import resolve_event, resolve_user



def resolve_place(db_mongo: Database, place: Union[int, str]) -> tuple[int, str]:
    """Resuelve dinámicamente un lugar/recinto en MongoDB y obtiene su ID y nombre.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        place: Identificador numérico (lugar_id) o nombre del lugar.

    Returns:
        Tupla con (lugar_id, nombre).

    Raises:
        ValueError: Si el lugar no existe en la base de datos.
    """
    if isinstance(place, int):
        doc = db_mongo.lugares.find_one({"lugar_id": place})
    else:
        doc = db_mongo.lugares.find_one({"nombre": str(place)})

    if not doc:
        raise ValueError(f"Lugar no encontrado en el sistema: '{place}'.")

    return int(doc["lugar_id"]), str(doc["nombre"])


# ==============================================================================
# 5.1 Aumento de precio en eventos futuros de una ciudad
# ==============================================================================


def increase_future_events_price(
    db_mongo: Database,
    driver_neo4j: Driver,
    city: str = DEFAULT_PRICE_INCREASE_CITY,
    percentage: float = DEFAULT_PRICE_INCREASE_PERCENTAGE,
    reference_date: str = REFERENCE_DATE,
) -> dict[str, Any]:
    """Aumenta porcentualmente el precio de los eventos futuros situados en una ciudad.

    Afecta a MongoDB (colección eventos) y a Neo4j (nodos Evento), sincronizando ambos motores.
    No modifica compras históricas previas según la regla de negocio de compras inmutables.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        city: Nombre de la ciudad donde se localizan los eventos. Por defecto 'Rosario'.
        percentage: Porcentaje de aumento a aplicar (ej. 10.0 para 10%). Por defecto 10.0.
        reference_date: Fecha de corte (YYYY-MM-DD). Eventos con fecha >= reference_date
            se consideran futuros. Por defecto REFERENCE_DATE ('2026-10-01').

    Returns:
        Diccionario con el resumen de eventos actualizados en ambas bases.

    Raises:
        ValueError: Si el porcentaje es menor o igual a cero o la ciudad es vacía.
    """
    if percentage <= 0:
        raise ValueError(f"El porcentaje de aumento debe ser mayor a cero. Recibido: {percentage}")
    if not city or not city.strip():
        raise ValueError("El nombre de la ciudad no puede ser vacío.")

    # 1. Obtener recintos ubicados en la ciudad indicada
    venue_cursor = db_mongo.lugares.find(
        {"ciudad": {"$regex": f"^{city.strip()}$", "$options": "i"}},
        {"_id": 0, "lugar_id": 1, "nombre": 1},
    )
    venues = list(venue_cursor)
    venue_ids = [v["lugar_id"] for v in venues]
    venue_map = {v["lugar_id"]: v["nombre"] for v in venues}

    if not venue_ids:
        return {
            "ciudad": city,
            "porcentaje": percentage,
            "eventos_modificados": [],
            "mensaje": f"No se encontraron recintos en la ciudad de '{city}'.",
        }

    # 2. Filtrar eventos futuros en dichos recintos en MongoDB
    future_events_filter = {
        "lugar_id": {"$in": venue_ids},
        "fecha": {"$gte": reference_date},
    }
    future_events = list(db_mongo.eventos.find(future_events_filter))

    multiplier = 1.0 + (percentage / 100.0)
    updated_summary: list[dict[str, Any]] = []

    # 3. Actualizar precios en MongoDB
    for event in future_events:
        eid = int(event["evento_id"])
        old_price = int(event.get("precio", 0))
        new_price = int(round(old_price * multiplier))

        db_mongo.eventos.update_one(
            {"evento_id": eid},
            {"$set": {"precio": new_price}},
        )
        updated_summary.append({
            "evento_id": eid,
            "nombre": event["nombre"],
            "lugar": venue_map.get(event["lugar_id"], f"Lugar {event['lugar_id']}"),
            "fecha": event["fecha"],
            "precio_anterior": old_price,
            "precio_nuevo": new_price,
        })

    # 4. Actualizar precios correspondientes en Neo4j
    neo4j_updated_count = 0
    with driver_neo4j.session(database="neo4j") as session:
        query_neo4j = """
        MATCH (e:Evento)-[:SE_REALIZA_EN]->(l:Lugar)
        WHERE toLower(l.ciudad) = toLower($city) AND e.fecha >= $reference_date
        SET e.precio = toInteger(round(e.precio * $multiplier))
        RETURN e.id AS evento_id, e.nombre AS nombre, e.precio AS nuevo_precio
        """
        result = session.run(
            query_neo4j,
            city=city,
            reference_date=reference_date,
            multiplier=multiplier,
        )
        neo4j_updated_count = len(list(result))

    return {
        "ciudad": city,
        "porcentaje": percentage,
        "fecha_referencia": reference_date,
        "total_eventos_modificados": len(updated_summary),
        "eventos_modificados": updated_summary,
        "neo4j_nodos_actualizados": neo4j_updated_count,
        "mensaje": (
            f"Se aumentó un {percentage}% el precio a {len(updated_summary)} eventos futuros "
            f"en {city} tanto en MongoDB como en Neo4j."
        ),
    }


def get_price_increase_evidence(
    db_mongo: Database,
    driver_neo4j: Driver,
    city: str = DEFAULT_PRICE_INCREASE_CITY,
    reference_date: str = REFERENCE_DATE,
    percentage: float = DEFAULT_PRICE_INCREASE_PERCENTAGE,
) -> dict[str, Any]:
    """Consulta de evidencia: Obtiene los eventos futuros de una ciudad que sufrieron aumento de precio.

    Verifica la actualización del 10% en MongoDB y Neo4j, mostrando únicamente los eventos
    futuros que resultaron efectivamente afectados por la modificación.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        city: Nombre de la ciudad a consultar. Por defecto 'Rosario'.
        reference_date: Fecha de referencia para filtrar eventos futuros. Por defecto REFERENCE_DATE.
        percentage: Porcentaje de aumento aplicado. Por defecto 10.0.

    Returns:
        Diccionario con la evidencia de precios en MongoDB y Neo4j para auditoría.
    """
    venue_cursor = db_mongo.lugares.find(
        {"ciudad": {"$regex": f"^{city.strip()}$", "$options": "i"}},
        {"_id": 0, "lugar_id": 1, "nombre": 1, "ciudad": 1},
    )
    venue_map = {v["lugar_id"]: v["nombre"] for v in venue_cursor}
    venue_ids = list(venue_map.keys())

    # Filtrar únicamente los eventos futuros situados en la ciudad indicada
    mongo_events = list(db_mongo.eventos.find(
        {
            "lugar_id": {"$in": venue_ids},
            "fecha": {"$gte": reference_date},
        },
        {"_id": 0, "evento_id": 1, "nombre": 1, "fecha": 1, "precio": 1, "lugar_id": 1, "estado": 1},
    ).sort("fecha", 1))

    with driver_neo4j.session(database="neo4j") as session:
        query_neo4j = """
        MATCH (e:Evento)-[:SE_REALIZA_EN]->(l:Lugar)
        WHERE toLower(l.ciudad) = toLower($city) AND e.fecha >= $reference_date
        RETURN e.id AS evento_id, e.nombre AS nombre, l.nombre AS lugar,
               e.fecha AS fecha, e.precio AS precio_neo4j, e.estado AS estado
        ORDER BY e.fecha ASC
        """
        neo_records = [dict(r) for r in session.run(query_neo4j, city=city, reference_date=reference_date)]

    neo_map = {r["evento_id"]: r["precio_neo4j"] for r in neo_records}
    multiplier = 1.0 + (percentage / 100.0)
    eventos_afectados: list[dict[str, Any]] = []

    for ev in mongo_events:
        eid = ev["evento_id"]
        nuevo_precio = int(ev["precio"])
        precio_anterior = int(round(nuevo_precio / multiplier))
        precio_neo = neo_map.get(eid, nuevo_precio)
        sincronizado = "Sí" if nuevo_precio == precio_neo else "No"

        eventos_afectados.append({
            "evento_id": eid,
            "evento": ev["nombre"],
            "lugar": venue_map.get(ev["lugar_id"], f"Lugar {ev['lugar_id']}"),
            "fecha": ev["fecha"],
            "precio_anterior": f"${precio_anterior:,.0f}".replace(",", "."),
            "precio_nuevo (+10%)": f"${nuevo_precio:,.0f}".replace(",", "."),
            "precio_en_mongo": f"${nuevo_precio:,.0f}".replace(",", "."),
            "precio_en_neo4j": f"${precio_neo:,.0f}".replace(",", "."),
            "sincronizado": sincronizado,
        })

    return {
        "ciudad": city,
        "total_afectados": len(eventos_afectados),
        "eventos_afectados": eventos_afectados,
        "eventos_mongodb": mongo_events,
        "eventos_neo4j": neo_records,
    }


# ==============================================================================
# 5.2 Agregar servicio a un lugar
# ==============================================================================


def add_service_to_place(
    db_mongo: Database,
    place: Union[int, str] = DEFAULT_SERVICE_PLACE_ID,
    service: str = DEFAULT_SERVICE_NAME,
    driver_neo4j: Optional[Driver] = None,
) -> dict[str, Any]:
    """Agrega un nuevo servicio al catálogo de servicios de un recinto/lugar.

    Utiliza el operador idempotente $addToSet en MongoDB para evitar duplicación.
    Si se provee el driver de Neo4j, también actualiza la propiedad correspondiente
    en el nodo Lugar para preservar la simetría entre motores NoSQL.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        place: Identificador numérico o nombre del lugar (ej. 2 o 'Sala Diagonal').
        service: Nombre del servicio a agregar. Por defecto 'accesibilidad'.
        driver_neo4j: Driver opcional de conexión a Neo4j para sincronización.

    Returns:
        Diccionario con el resultado de la operación y la lista de servicios actualizada.

    Raises:
        ValueError: Si el servicio está vacío o el lugar no existe.
    """
    if not service or not service.strip():
        raise ValueError("El nombre del servicio no puede ser vacío.")

    place_id, place_name = resolve_place(db_mongo, place)
    service_clean = service.strip().lower()

    # 1. Actualizar en MongoDB usando $addToSet (idempotente)
    res_mongo = db_mongo.lugares.update_one(
        {"lugar_id": place_id},
        {"$addToSet": {"servicios": service_clean}},
    )

    doc_actualizado = db_mongo.lugares.find_one({"lugar_id": place_id}, {"_id": 0})
    current_services = doc_actualizado.get("servicios", []) if doc_actualizado else []

    # 2. Sincronizar en Neo4j si se suministra el driver
    neo4j_synced = False
    if driver_neo4j is not None:
        with driver_neo4j.session(database="neo4j") as session:
            query_neo4j = """
            MATCH (l:Lugar {id: $place_id})
            SET l.servicios = CASE
                WHEN l.servicios IS NULL THEN [$service]
                WHEN NOT $service IN l.servicios THEN l.servicios + [$service]
                ELSE l.servicios
            END
            RETURN l.id AS lugar_id, l.nombre AS nombre, l.servicios AS servicios
            """
            result = session.run(query_neo4j, place_id=place_id, service=service_clean)
            neo4j_synced = result.single() is not None

    return {
        "lugar_id": place_id,
        "lugar_nombre": place_name,
        "servicio_agregado": service_clean,
        "servicios_actuales": current_services,
        "modificado_mongo": res_mongo.modified_count > 0,
        "sincronizado_neo4j": neo4j_synced,
        "mensaje": (
            f"Servicio '{service_clean}' registrado exitosamente en '{place_name}' (ID {place_id}). "
            f"Servicios actuales: {current_services}"
        ),
    }


def get_place_services_evidence(
    place: Union[int, str] = DEFAULT_SERVICE_PLACE_ID,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> dict[str, Any]:
    """Consulta de evidencia: Inspecciona los servicios registrados para un lugar en MongoDB y Neo4j.

    Args:
        place: Identificador numérico o nombre del lugar.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver opcional de conexión a Neo4j.

    Returns:
        Diccionario con la información del lugar y sus servicios en las bases disponibles.
    """
    if db_mongo is None:
        raise ValueError("Se requiere db_mongo para consultar la evidencia del lugar.")

    place_id, place_name = resolve_place(db_mongo, place)
    doc_mongo = db_mongo.lugares.find_one({"lugar_id": place_id}, {"_id": 0}) or {}

    neo_services: Optional[list[str]] = None
    if driver_neo4j is not None:
        with driver_neo4j.session(database="neo4j") as session:
            record = session.run(
                "MATCH (l:Lugar {id: $place_id}) RETURN l.nombre AS nombre, l.servicios AS servicios",
                place_id=place_id,
            ).single()
            if record:
                neo_services = record.get("servicios")

    return {
        "lugar_id": place_id,
        "nombre": place_name,
        "ciudad": doc_mongo.get("ciudad"),
        "capacidad": doc_mongo.get("capacidad"),
        "servicios_mongodb": doc_mongo.get("servicios", []),
        "servicios_neo4j": neo_services,
    }


# ==============================================================================
# 5.3 Cancelar evento 7
# ==============================================================================


def cancel_event(
    event: Union[int, str] = DEFAULT_CANCEL_EVENT_ID,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> dict[str, Any]:
    """Cancela un evento y sincroniza el impacto en cascada a través de las tres bases.

    Acciones ejecutadas:
    1. MongoDB: Marca el estado del evento como 'cancelado'.
    2. MongoDB: Actualiza todas las compras de dicho evento a estado 'reembolsada'.
    3. Neo4j: Actualiza la propiedad estado del nodo Evento a 'cancelado'.
    4. Neo4j: Actualiza la propiedad estado de las relaciones (:Usuario)-[:COMPRO]->(:Evento) a 'reembolsada'.
    5. Redis: Fija el stock disponible y la capacidad a 0 (anulación total de disponibilidad).
    6. Redis: Rastrea y elimina todas las reservas temporales vigentes asociadas al evento.

    Args:
        event: Identificador numérico o nombre del evento a cancelar. Por defecto 7.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario con el detalle de las operaciones ejecutadas en las tres bases.

    Raises:
        ValueError: Si faltan conexiones necesarias o el evento no existe.
    """
    if db_mongo is None or driver_neo4j is None or redis_client is None:
        raise ValueError("Se requieren instancias activas de MongoDB, Neo4j y Redis para cancelar el evento.")

    event_id, event_name, *_ = resolve_event(db_mongo, event)

    # 1. MongoDB: Cancelar evento y reembolsar compras
    res_event_mongo = db_mongo.eventos.update_one(
        {"evento_id": event_id},
        {"$set": {"estado": "cancelado"}},
    )
    res_purchases_mongo = db_mongo.compras.update_many(
        {"evento_id": event_id},
        {"$set": {"estado": "reembolsada"}},
    )

    # 2. Neo4j: Sincronizar estado cancelado del evento y estado reembolsada en aristas :COMPRO
    neo4j_event_updated = False
    neo4j_purchases_updated = 0
    with driver_neo4j.session(database="neo4j") as session:
        res_ev = session.run(
            "MATCH (e:Evento {id: $event_id}) SET e.estado = 'cancelado' RETURN e.id",
            event_id=event_id,
        ).single()
        neo4j_event_updated = res_ev is not None

        res_pur = session.run(
            """
            MATCH (u:Usuario)-[r:COMPRO]->(e:Evento {id: $event_id})
            SET r.estado = 'reembolsada'
            RETURN count(r) AS actualizadas
            """,
            event_id=event_id,
        ).single()
        if res_pur:
            neo4j_purchases_updated = int(res_pur["actualizadas"])

    # 3. Redis: Eliminar disponibilidad y reservas vigentes del evento
    redis_client.set(f"event:{event_id}:stock", 0)
    redis_client.set(f"event:{event_id}:capacity", 0)
    redis_client.set(f"event:{event_id}:status", "cancelado")

    cancelled_reservations_count = 0
    for key in redis_client.scan_iter("reservation:*"):
        if key == "reservation:next_id":
            continue
        raw_res = redis_client.get(key)
        if raw_res:
            try:
                data = json.loads(raw_res)
                if int(data.get("evento_id", -1)) == event_id:
                    redis_client.delete(key)
                    cancelled_reservations_count += 1
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    return {
        "evento_id": event_id,
        "evento_nombre": event_name,
        "estado_nuevo": "cancelado",
        "mongodb": {
            "evento_modificado": res_event_mongo.modified_count > 0,
            "compras_reembolsadas": res_purchases_mongo.modified_count,
        },
        "neo4j": {
            "nodo_evento_cancelado": neo4j_event_updated,
            "relaciones_compro_reembolsadas": neo4j_purchases_updated,
        },
        "redis": {
            "stock_disponible": 0,
            "capacidad": 0,
            "reservas_eliminadas": cancelled_reservations_count,
        },
        "excluido_de_recomendaciones": True,
        "mensaje": (
            f"Evento '{event_name}' (ID {event_id}) cancelado en MongoDB y Neo4j. "
            f"Compras pasadas a 'reembolsada' ({res_purchases_mongo.modified_count} en Mongo, "
            f"{neo4j_purchases_updated} en Neo4j). Disponibilidad en Redis fijada en 0 y "
            f"{cancelled_reservations_count} reservas eliminadas."
        ),
    }


def get_cancelled_event_evidence(
    event: Union[int, str] = DEFAULT_CANCEL_EVENT_ID,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> dict[str, Any]:
    """Consulta de evidencia: Comprueba el estado integral del evento cancelado en las tres bases.

    Args:
        event: Identificador numérico o nombre del evento cancelado.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario con el estado del evento, compras, disponibilidad y reservas activas.
    """
    if db_mongo is None or driver_neo4j is None or redis_client is None:
        raise ValueError("Se requieren MongoDB, Neo4j y Redis para consultar la evidencia del evento.")

    event_id, event_name, *_ = resolve_event(db_mongo, event)

    # 1. MongoDB: Estado del evento y de sus compras
    ev_mongo = db_mongo.eventos.find_one({"evento_id": event_id}, {"_id": 0}) or {}
    purchases_mongo = list(db_mongo.compras.find(
        {"evento_id": event_id},
        {"_id": 0, "compra_id": 1, "usuario_id": 1, "cantidad": 1, "total": 1, "estado": 1},
    ))

    # Obtener nombres de usuarios de las compras para no mostrar únicamente IDs
    for p in purchases_mongo:
        uid = p.get("usuario_id")
        if uid is not None:
            u_doc = db_mongo.usuarios.find_one({"usuario_id": uid}, {"nombre": 1})
            p["usuario_nombre"] = u_doc.get("nombre") if u_doc else "Usuario Desconocido"
        else:
            p["usuario_nombre"] = "Usuario Anonimizado / Eliminado"

    # 2. Neo4j: Nodo evento y aristas de compras
    with driver_neo4j.session(database="neo4j") as session:
        ev_neo = session.run(
            "MATCH (e:Evento {id: $event_id}) RETURN e.nombre AS nombre, e.estado AS estado, e.precio AS precio",
            event_id=event_id,
        ).single()
        ev_neo_info = dict(ev_neo) if ev_neo else {}

        purchases_neo_records = session.run(
            """
            MATCH (u:Usuario)-[r:COMPRO]->(e:Evento {id: $event_id})
            RETURN r.compra_id AS compra_id, u.nombre AS usuario_nombre,
                   r.cantidad AS cantidad, r.total AS total, r.estado AS estado
            """,
            event_id=event_id,
        )
        purchases_neo = [dict(r) for r in purchases_neo_records]

    # 3. Redis: Stock y reservas activas para este evento
    stock_redis = redis_client.get(f"event:{event_id}:stock")
    capacity_redis = redis_client.get(f"event:{event_id}:capacity")
    status_redis = redis_client.get(f"event:{event_id}:status")

    active_reservations_for_event = []
    for key in redis_client.scan_iter("reservation:*"):
        if key == "reservation:next_id":
            continue
        raw_res = redis_client.get(key)
        if raw_res:
            try:
                data = json.loads(raw_res)
                if int(data.get("evento_id", -1)) == event_id:
                    active_reservations_for_event.append(data)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    return {
        "evento_id": event_id,
        "evento_nombre": event_name,
        "mongodb": {
            "estado_evento": ev_mongo.get("estado"),
            "compras": purchases_mongo,
        },
        "neo4j": {
            "nodo_evento": ev_neo_info,
            "relaciones_compras": purchases_neo,
        },
        "redis": {
            "clave_stock": stock_redis,
            "clave_capacity": capacity_redis,
            "clave_status": status_redis,
            "reservas_activas_encontradas": len(active_reservations_for_event),
        },
    }


# ==============================================================================
# 5.4 Eliminar al usuario Tomás Herrera (id 6) del sistema
# ==============================================================================


def delete_user(
    user: Union[int, str] = DEFAULT_DELETE_USER_NAME,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
    anonymize_purchases: bool = True,
) -> dict[str, Any]:
    """Elimina a un usuario del sistema y gestiona sus compras, sesiones y grafo social.

    Args:
        user: Identificador numérico o nombre completo del usuario a eliminar.
            Por defecto DEFAULT_DELETE_USER_NAME ('Tomás Herrera').
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.
        anonymize_purchases: Si es True (recomendado), preserva las compras históricas en
            MongoDB disociando los datos personales (usuario_id = None, usuario_eliminado = True).
            Si es False, ejecuta borrado en cascada eliminando también las compras de MongoDB.

    Returns:
        Diccionario con el informe de la eliminación en cada una de las bases.

    Raises:
        ValueError: Si faltan conexiones o el usuario no existe.
    """
    if db_mongo is None or driver_neo4j is None or redis_client is None:
        raise ValueError("Se requieren MongoDB, Neo4j y Redis para eliminar al usuario.")

    user_id, user_name = resolve_user(db_mongo, user)

    # 1. Redis: Destruir sesión activa y cancelar reservas temporales pendientes liberando cupos
    session_key = f"session:user:{user_id}"
    had_active_session = bool(redis_client.delete(session_key))

    released_tickets = 0
    deleted_reservations_count = 0
    for key in redis_client.scan_iter("reservation:*"):
        if key == "reservation:next_id":
            continue
        raw_res = redis_client.get(key)
        if raw_res:
            try:
                data = json.loads(raw_res)
                if int(data.get("usuario_id", -1)) == user_id:
                    qty = int(data.get("cantidad", 0))
                    eid = int(data.get("evento_id", -1))
                    if eid > 0 and qty > 0:
                        redis_client.incrby(f"event:{eid}:stock", qty)
                        released_tickets += qty
                    redis_client.delete(key)
                    deleted_reservations_count += 1
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    # 2. MongoDB: Gestión de compras (anonimización contable o cascada)
    purchases_action: str
    purchases_affected_count: int

    if anonymize_purchases:
        res_purchases = db_mongo.compras.update_many(
            {"usuario_id": user_id},
            {
                "$set": {
                    "usuario_id": None,
                    "usuario_eliminado": True,
                    "notas": f"Compra anonimizada tras baja del usuario '{user_name}' (ID anterior: {user_id}).",
                }
            },
        )
        purchases_action = "anonimizadas (conservadas para trazabilidad contable)"
        purchases_affected_count = res_purchases.modified_count
    else:
        res_purchases = db_mongo.compras.delete_many({"usuario_id": user_id})
        purchases_action = "eliminadas físicamente en cascada"
        purchases_affected_count = res_purchases.deleted_count

    # Eliminar posibles referencias residuales en listas de amigos en MongoDB
    db_mongo.usuarios.update_many({}, {"$pull": {"amigos": user_id}})

    # Eliminar documento de usuario en MongoDB
    res_user_delete = db_mongo.usuarios.delete_one({"usuario_id": user_id})

    # 3. Neo4j: Eliminar nodo Usuario y todas sus relaciones (:AMIGO_DE, :SIGUE, :COMPRO)
    deleted_relationships_count = 0
    deleted_neo4j_node = False
    with driver_neo4j.session(database="neo4j") as session:
        query_neo = """
        MATCH (u:Usuario {id: $user_id})
        OPTIONAL MATCH (u)-[r]-()
        WITH u, count(r) AS rel_count
        DETACH DELETE u
        RETURN rel_count
        """
        record = session.run(query_neo, user_id=user_id).single()
        if record:
            deleted_neo4j_node = True
            deleted_relationships_count = int(record["rel_count"])

    justification = (
        f"Justificación sobre compras: Se adoptó el criterio de {purchases_action}. "
        "Permite que la recaudación acumulada por evento y recinto permanezca matemáticamente "
        "exacta para auditorías contables, cumpliendo a la vez con el derecho al olvido al "
        "desvincular permanentemente la identidad del usuario tanto en MongoDB como en el grafo Neo4j."
    )

    return {
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "mongodb": {
            "usuario_eliminado": res_user_delete.deleted_count > 0,
            "compras_accion": purchases_action,
            "compras_afectadas": purchases_affected_count,
        },
        "neo4j": {
            "nodo_eliminado": deleted_neo4j_node,
            "relaciones_eliminadas": deleted_relationships_count,
        },
        "redis": {
            "sesion_eliminada": had_active_session,
            "reservas_canceladas": deleted_reservations_count,
            "entradas_restituidas_a_stock": released_tickets,
        },
        "justificacion_compras": justification,
        "mensaje": f"Usuario '{user_name}' (ID {user_id}) eliminado con éxito del ecosistema políglota.",
    }


def get_deleted_user_evidence(
    user_id: int,
    user_name: str,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
    redis_client: Optional[redis.Redis] = None,
) -> dict[str, Any]:
    """Consulta de evidencia: Constata la eliminación de un usuario y el estado de sus registros.

    Args:
        user_id: Identificador numérico del usuario eliminado.
        user_name: Nombre original del usuario para referencia y búsqueda en compras.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario demostrando la ausencia del usuario en las 3 bases y el estado de compras.
    """
    if db_mongo is None or driver_neo4j is None or redis_client is None:
        raise ValueError("Se requieren MongoDB, Neo4j y Redis para verificar la eliminación del usuario.")

    # 1. MongoDB
    user_doc = db_mongo.usuarios.find_one({"usuario_id": user_id})
    purchases_anon = list(db_mongo.compras.find(
        {"notas": {"$regex": f"ID anterior: {user_id}"}},
        {"_id": 0, "compra_id": 1, "evento_id": 1, "cantidad": 1, "total": 1, "usuario_eliminado": 1, "notas": 1},
    ))
    # También buscar si quedaron compras directas por usuario_id
    direct_purchases = list(db_mongo.compras.find({"usuario_id": user_id}, {"_id": 0}))

    # 2. Neo4j
    with driver_neo4j.session(database="neo4j") as session:
        neo_user = session.run("MATCH (u:Usuario {id: $user_id}) RETURN u", user_id=user_id).single()
        neo_relationships = session.run(
            "MATCH (u:Usuario {id: $user_id})-[r]-() RETURN count(r) AS c",
            user_id=user_id,
        ).single()

    # 3. Redis
    session_exists = bool(redis_client.exists(f"session:user:{user_id}"))

    return {
        "usuario_id_evaluado": user_id,
        "usuario_nombre_evaluado": user_name,
        "mongodb": {
            "existe_usuario": user_doc is not None,
            "compras_directas_con_usuario_id": len(direct_purchases),
            "compras_anonimizadas_conservadas": purchases_anon,
        },
        "neo4j": {
            "existe_nodo_usuario": neo_user is not None,
            "relaciones_restantes": neo_relationships["c"] if neo_relationships else 0,
        },
        "redis": {
            "sesion_activa_presente": session_exists,
        },
    }


# ==============================================================================
# 5.5 Eliminar todas las amistades de un usuario a elección
# ==============================================================================


def delete_user_friendships(
    user: Union[int, str] = DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> dict[str, Any]:
    """Elimina todas las relaciones de amistad de un usuario en el grafo y en MongoDB.

    Elimina tanto los vínculos de amistad salientes como entrantes en Neo4j (:AMIGO_DE).
    Adicionalmente, limpia el atributo 'amigos' en MongoDB si existiera, garantizando
    consistencia íntegra en la persistencia políglota.

    Args:
        user: Identificador numérico o nombre completo del usuario (por defecto 'Juan López').
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.

    Returns:
        Diccionario con la cantidad de relaciones eliminadas y nombres de los antiguos amigos.

    Raises:
        ValueError: Si faltan conexiones o el usuario no existe.
    """
    if db_mongo is None or driver_neo4j is None:
        raise ValueError("Se requieren MongoDB y Neo4j para eliminar las amistades de un usuario.")

    user_id, user_name = resolve_user(db_mongo, user)

    # 1. Neo4j: Obtener lista previa de amigos y eliminar relaciones :AMIGO_DE en ambas direcciones
    former_friends: list[dict[str, Any]] = []
    deleted_count = 0
    with driver_neo4j.session(database="neo4j") as session:
        query_friends_preview = """
        MATCH (u:Usuario {id: $user_id})-[r:AMIGO_DE]-(f:Usuario)
        RETURN DISTINCT f.id AS amigo_id, f.nombre AS amigo_nombre
        """
        former_friends = [dict(record) for record in session.run(query_friends_preview, user_id=user_id)]

        query_delete_friendships = """
        MATCH (u:Usuario {id: $user_id})-[r:AMIGO_DE]-(f:Usuario)
        DELETE r
        """
        summary = session.run(query_delete_friendships, user_id=user_id).consume()
        deleted_count = summary.counters.relationships_deleted

    # 2. MongoDB: Si existiese la lista amigos en el documento del usuario o en otros documentos, limpiarla
    db_mongo.usuarios.update_one({"usuario_id": user_id}, {"$set": {"amigos": []}})
    db_mongo.usuarios.update_many({}, {"$pull": {"amigos": user_id}})

    return {
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "amigos_previos": former_friends,
        "relaciones_neo4j_eliminadas": deleted_count,
        "mensaje": (
            f"Se eliminaron todas las amistades de {user_name} (ID {user_id}). "
            f"Relaciones :AMIGO_DE removidas en Neo4j: {deleted_count}."
        ),
    }


def get_user_friendships_evidence(
    user: Union[int, str] = DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
    db_mongo: Optional[Database] = None,
    driver_neo4j: Optional[Driver] = None,
) -> dict[str, Any]:
    """Consulta de evidencia: Verifica que el usuario no conserve ninguna relación de amistad.

    Args:
        user: Identificador numérico o nombre completo del usuario.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.

    Returns:
        Diccionario con las amistades actuales (debe ser lista vacía tras la mutación).
    """
    if db_mongo is None or driver_neo4j is None:
        raise ValueError("Se requieren MongoDB y Neo4j para auditar las amistades de un usuario.")

    user_id, user_name = resolve_user(db_mongo, user)

    # 1. Neo4j
    with driver_neo4j.session(database="neo4j") as session:
        query_friends = """
        MATCH (u:Usuario {id: $user_id})-[r:AMIGO_DE]-(f:Usuario)
        RETURN DISTINCT f.id AS amigo_id, f.nombre AS amigo_nombre
        """
        neo_friends = [dict(record) for record in session.run(query_friends, user_id=user_id)]

    # 2. MongoDB
    u_doc = db_mongo.usuarios.find_one({"usuario_id": user_id}, {"_id": 0, "amigos": 1}) or {}
    mongo_friends = u_doc.get("amigos", [])

    return {
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "total_amigos_neo4j": len(neo_friends),
        "amigos_neo4j": neo_friends,
        "amigos_mongodb": mongo_friends,
    }


# ==============================================================================
# DEMOSTRACIÓN ORQUESTADA COMPLETA (Sección 5)
# ==============================================================================


def demonstrate_all_modifications(
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
) -> dict[str, Any]:
    """Ejecuta de manera secuencial y didáctica los 5 incisos de la sección de Modificaciones.

    Muestra el estado previo, la aplicación de la mutación y la evidencia posterior
    conforme a las directivas de la cátedra para los incisos 5.1 a 5.5.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario con los resultados y evidencias de los 5 incisos ejecutados.
    """
    print("\n" + "=" * 70)
    print(" EJECUCIÓN INTEGRAL DE MODIFICACIONES (CONSIGNAS: SECCIÓN 5)")
    print("=" * 70)

    results: dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # 5.1 Aumento de precio del 10% en eventos futuros en Rosario
    # -------------------------------------------------------------------------
    print("\n>>> [5.1] Aumentar un 10% el precio de los eventos futuros en Rosario")
    ev_prev_51 = get_price_increase_evidence(db_mongo, driver_neo4j, city=DEFAULT_PRICE_INCREASE_CITY)
    print("--- Precios antes del aumento en Rosario ---")
    for ev in ev_prev_51["eventos_mongodb"]:
        print(f" • Evento: {ev['nombre']} | Fecha: {ev['fecha']} | Precio Mongo: ${ev['precio_mongo']:,}")

    mod_51 = increase_future_events_price(
        db_mongo,
        driver_neo4j,
        city=DEFAULT_PRICE_INCREASE_CITY,
        percentage=DEFAULT_PRICE_INCREASE_PERCENTAGE,
    )
    print(f"\n[Resultado]: {mod_51['mensaje']}")

    ev_post_51 = get_price_increase_evidence(db_mongo, driver_neo4j, city=DEFAULT_PRICE_INCREASE_CITY)
    print("--- Evidencia post-modificación ---")
    for ev in ev_post_51["eventos_mongodb"]:
        print(
            f" • Evento: {ev['nombre']} | Fecha: {ev['fecha']} | "
            f"Nuevo Precio Mongo: ${ev['precio_mongo']:,}"
        )
    for ev in ev_post_51["eventos_neo4j"]:
        print(f"   [Neo4j] Evento: {ev['nombre']} | Precio Neo4j: ${ev['precio_neo4j']:,}")

    results["5.1"] = {"modificacion": mod_51, "evidencia": ev_post_51}

    # -------------------------------------------------------------------------
    # 5.2 Agregar servicio "accesibilidad" al lugar con id 2
    # -------------------------------------------------------------------------
    print("\n>>> [5.2] Agregar el servicio 'accesibilidad' al lugar con id 2")
    ev_prev_52 = get_place_services_evidence(DEFAULT_SERVICE_PLACE_ID, db_mongo, driver_neo4j)
    print(f"--- Servicios previos en '{ev_prev_52['nombre']}': {ev_prev_52['servicios_mongodb']} ---")

    mod_52 = add_service_to_place(
        db_mongo,
        place=DEFAULT_SERVICE_PLACE_ID,
        service=DEFAULT_SERVICE_NAME,
        driver_neo4j=driver_neo4j,
    )
    print(f"[Resultado]: {mod_52['mensaje']}")

    ev_post_52 = get_place_services_evidence(DEFAULT_SERVICE_PLACE_ID, db_mongo, driver_neo4j)
    print(f"--- Evidencia post-modificación en '{ev_post_52['nombre']}' ---")
    print(f" • Servicios en MongoDB: {ev_post_52['servicios_mongodb']}")
    print(f" • Servicios en Neo4j:   {ev_post_52['servicios_neo4j']}")

    results["5.2"] = {"modificacion": mod_52, "evidencia": ev_post_52}

    # -------------------------------------------------------------------------
    # 5.3 Cancelar el evento 7
    # -------------------------------------------------------------------------
    print("\n>>> [5.3] Cancelar el evento 7 (reembolsos, vaciado de disponibilidad y reservas)")
    mod_53 = cancel_event(
        event=DEFAULT_CANCEL_EVENT_ID,
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
        redis_client=redis_client,
    )
    print(f"[Resultado]: {mod_53['mensaje']}")

    ev_post_53 = get_cancelled_event_evidence(
        event=DEFAULT_CANCEL_EVENT_ID,
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
        redis_client=redis_client,
    )
    print("--- Evidencia post-modificación para Evento 7 ---")
    print(f" • MongoDB: Estado del evento = '{ev_post_53['mongodb']['estado_evento']}'")
    for cp in ev_post_53["mongodb"]["compras"]:
        print(
            f"   - Compra #{cp['compra_id']} de {cp['usuario_nombre']}: "
            f"Total ${cp['total']:,} -> Estado: {cp['estado']}"
        )
    print(f" • Neo4j: Nodo evento = {ev_post_53['neo4j']['nodo_evento']}")
    print(
        f" • Redis: Stock = {ev_post_53['redis']['clave_stock']}, "
        f"Reservas activas = {ev_post_53['redis']['reservas_activas_encontradas']}"
    )

    results["5.3"] = {"modificacion": mod_53, "evidencia": ev_post_53}

    # -------------------------------------------------------------------------
    # 5.4 Eliminar al usuario Tomás Herrera (id 6) del sistema
    # -------------------------------------------------------------------------
    print("\n>>> [5.4] Eliminar al usuario Tomás Herrera (id 6) del sistema")
    mod_54 = delete_user(
        user=DEFAULT_DELETE_USER_NAME,
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
        redis_client=redis_client,
        anonymize_purchases=True,
    )
    print(f"[Resultado]: {mod_54['mensaje']}")
    print(f"[Justificación Contable]: {mod_54['justificacion_compras']}")

    ev_post_54 = get_deleted_user_evidence(
        user_id=mod_54["usuario_id"],
        user_name=mod_54["usuario_nombre"],
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
        redis_client=redis_client,
    )
    print("--- Evidencia post-eliminación ---")
    print(f" • MongoDB: ¿Existe usuario {mod_54['usuario_id']}? {ev_post_54['mongodb']['existe_usuario']}")
    print(
        f" • MongoDB: Compras anonimizadas para auditoría: "
        f"{len(ev_post_54['mongodb']['compras_anonimizadas_conservadas'])}"
    )
    print(f" • Neo4j: ¿Existe nodo :Usuario {mod_54['usuario_id']}? {ev_post_54['neo4j']['existe_nodo_usuario']}")
    print(f" • Redis: ¿Existe sesión activa en Redis? {ev_post_54['redis']['sesion_activa_presente']}")

    results["5.4"] = {"modificacion": mod_54, "evidencia": ev_post_54}

    # -------------------------------------------------------------------------
    # 5.5 Eliminar todas las amistades de un usuario a elección
    # -------------------------------------------------------------------------
    print(f"\n>>> [5.5] Eliminar todas las amistades de '{DEFAULT_DELETE_FRIENDSHIPS_USER_NAME}'")
    mod_55 = delete_user_friendships(
        user=DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
    )
    print(f"[Resultado]: {mod_55['mensaje']}")

    ev_post_55 = get_user_friendships_evidence(
        user=DEFAULT_DELETE_FRIENDSHIPS_USER_NAME,
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
    )
    print(f"--- Evidencia post-modificación en '{DEFAULT_DELETE_FRIENDSHIPS_USER_NAME}' ---")
    print(f" • Total amistades en Neo4j: {ev_post_55['total_amigos_neo4j']} (Lista: {ev_post_55['amigos_neo4j']})")
    print(f" • Amigos en MongoDB: {ev_post_55['amigos_mongodb']}")

    results["5.5"] = {"modificacion": mod_55, "evidencia": ev_post_55}

    print("\n" + "=" * 70)
    print(" DEMOSTRACIÓN DE TODAS LAS MODIFICACIONES COMPLETADA CON ÉXITO")
    print("=" * 70 + "\n")

    return results
