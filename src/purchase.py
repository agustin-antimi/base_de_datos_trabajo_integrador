"""Módulo para la gestión del flujo transaccional de compra y reservas.

Implementa la reserva temporal en Redis, la confirmación de compras en MongoDB y Neo4j,
la cancelación con restitución de cupos y las demostraciones de los tres casos requeridos.
"""

import json
from datetime import datetime
from typing import Any, Optional, Union

import redis
from neo4j import Driver
from pymongo.database import Database

try:
    from config import (
        REFERENCE_DATE,
        RESERVATION_TTL_SECONDS,
        SESSION_TTL_SECONDS,
    )
except ImportError:
    from src.config import (
        REFERENCE_DATE,
        RESERVATION_TTL_SECONDS,
        SESSION_TTL_SECONDS,
    )


# ==============================================================================
# CONSIGNAS: Sección 2 - Resolución Dinámica de Entidades (Sin Hardcoding)
# ==============================================================================


def resolve_user(db_mongo: Database, user: Union[int, str]) -> tuple[int, str]:
    """Resuelve dinámicamente el identificador y nombre de un usuario en MongoDB.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        user: Identificador numérico (usuario_id) o nombre completo del usuario.

    Returns:
        Tupla con (usuario_id, nombre).

    Raises:
        ValueError: Si el usuario no existe en la base de datos.
    """
    if isinstance(user, int):
        doc = db_mongo.usuarios.find_one({"usuario_id": user})
    else:
        doc = db_mongo.usuarios.find_one({"nombre": str(user)})

    if not doc:
        raise ValueError(f"Usuario no encontrado en el sistema: '{user}'.")

    return int(doc["usuario_id"]), str(doc["nombre"])


def resolve_event(
    db_mongo: Database,
    event: Union[int, str],
) -> tuple[int, str, int, str]:
    """Resuelve dinámicamente un evento en MongoDB y obtiene sus datos vigentes.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        event: Identificador numérico (evento_id) o nombre del evento.

    Returns:
        Tupla con (evento_id, nombre, precio_actual, estado).

    Raises:
        ValueError: Si el evento no existe en la base de datos.
    """
    if isinstance(event, int):
        doc = db_mongo.eventos.find_one({"evento_id": event})
    else:
        doc = db_mongo.eventos.find_one({"nombre": str(event)})

    if not doc:
        raise ValueError(f"Evento no encontrado en el sistema: '{event}'.")

    return (
        int(doc["evento_id"]),
        str(doc["nombre"]),
        int(doc.get("precio", 0)),
        str(doc.get("estado", "activo")),
    )


# ==============================================================================
# CONSIGNAS: Sección 2 - Gestión y Validación de Sesiones de Usuario
# Regla de negocio: "Una sesión de usuario vence a los 30 minutos."
# ==============================================================================


def create_user_session(
    user: Union[int, str],
    db_mongo: Database,
    redis_client: redis.Redis,
    session_ttl: int = SESSION_TTL_SECONDS,
) -> dict[str, Any]:
    """Crea o renueva la sesión de un usuario en Redis con tiempo de vencimiento.

    Args:
        user: Identificador numérico o nombre del usuario.
        db_mongo: Instancia de base de datos de MongoDB.
        redis_client: Cliente de conexión a Redis.
        session_ttl: Tiempo de vida de la sesión en segundos. Por defecto 1800s (30m).

    Returns:
        Diccionario con los detalles de la sesión creada.
    """
    user_id, user_name = resolve_user(db_mongo, user)
    payload = {
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "conectado_en": datetime.now().isoformat(),
        "estado": "activa",
    }
    redis_client.set(f"session:user:{user_id}", json.dumps(payload), ex=session_ttl)
    return {
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "ttl_restante": session_ttl,
        "mensaje": f"Sesión activa para {user_name} (ID {user_id}) por {session_ttl // 60} minutos.",
    }


def is_user_session_active(user_id: int, redis_client: redis.Redis) -> bool:
    """Verifica si el usuario tiene una sesión activa en Redis que no haya expirado.

    Args:
        user_id: Identificador numérico del usuario.
        redis_client: Cliente de conexión a Redis.

    Returns:
        True si la sesión existe y está vigente, False en caso contrario.
    """
    return bool(redis_client.exists(f"session:user:{user_id}"))


# ==============================================================================
# CONSIGNAS: Sección 2.1 - Reservar Entradas
# Reglas de negocio:
# - Solo se permite si el usuario tiene sesión activa y hay disponibilidad suficiente.
# - Una reserva no confirmada vence a los 10 minutos.
# ==============================================================================


def reserve_tickets(
    user: Union[int, str],
    event: Union[int, str],
    quantity: int,
    db_mongo: Database,
    redis_client: redis.Redis,
    reservation_ttl: int = RESERVATION_TTL_SECONDS,
) -> dict[str, Any]:
    """Crea una reserva temporal de entradas si el usuario tiene sesión activa y hay cupo.

    Args:
        user: Identificador numérico o nombre del usuario que realiza la reserva.
        event: Identificador numérico o nombre del evento para el cual se reservan entradas.
        quantity: Cantidad de entradas solicitadas (debe ser mayor a 0).
        db_mongo: Instancia de base de datos de MongoDB.
        redis_client: Cliente de conexión a Redis.
        reservation_ttl: Tiempo de vida en segundos de la reserva. Por defecto 600s (10 minutos).

    Returns:
        Diccionario con la información detallada de la reserva creada.

    Raises:
        ValueError: Si la cantidad de entradas no es positiva o el evento está inactivo.
        PermissionError: Si el usuario no tiene una sesión activa en Redis.
        RuntimeError: Si no hay disponibilidad suficiente de entradas para el evento.
    """
    if quantity <= 0:
        raise ValueError(f"La cantidad de entradas debe ser mayor a 0. Solicitada: {quantity}.")

    user_id, user_name = resolve_user(db_mongo, user)
    event_id, event_name, price, event_status = resolve_event(db_mongo, event)

    if event_status.lower() != "activo":
        raise ValueError(f"No se pueden reservar entradas: el evento '{event_name}' está '{event_status}'.")

    # Validar sesión activa en Redis
    if not is_user_session_active(user_id, redis_client):
        raise PermissionError(
            f"El usuario {user_name} (ID {user_id}) no tiene una sesión activa. "
            "Inicie sesión para poder reservar entradas."
        )

    # Validar disponibilidad atómica en Redis
    stock_raw = redis_client.get(f"event:{event_id}:stock")
    current_stock = int(stock_raw) if stock_raw is not None else 0

    if current_stock < quantity:
        raise RuntimeError(
            f"Disponibilidad insuficiente para '{event_name}'. "
            f"Entradas disponibles: {current_stock}, solicitadas: {quantity}."
        )

    # Descontar stock atómicamente en Redis
    redis_client.decrby(f"event:{event_id}:stock", quantity)

    # Generar identificador único de reserva
    reservation_id = int(redis_client.incr("reservation:next_id"))

    # Crear la reserva con TTL de 10 minutos
    reservation_payload = {
        "reservation_id": reservation_id,
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "evento_id": event_id,
        "evento_nombre": event_name,
        "cantidad": quantity,
        "precio_unitario": price,
        "creada_en": datetime.now().isoformat(),
    }
    redis_client.set(
        f"reservation:{reservation_id}",
        json.dumps(reservation_payload),
        ex=reservation_ttl,
    )

    remaining_ttl = int(redis_client.ttl(f"reservation:{reservation_id}"))

    return {
        "reserva_id": reservation_id,
        "usuario": user_name,
        "usuario_id": user_id,
        "evento": event_name,
        "evento_id": event_id,
        "cantidad": quantity,
        "precio_unitario": price,
        "total_estimado": price * quantity,
        "ttl_segundos": remaining_ttl,
        "estado": "vigente",
        "mensaje": (
            f"Reserva #{reservation_id} creada exitosamente. "
            f"Vence en {remaining_ttl} segundos ({remaining_ttl // 60} minutos)."
        ),
    }


# ==============================================================================
# CONSIGNAS: Sección 2.2 - Confirmar una Reserva Vigente
# Reglas de negocio:
# - Se genera la compra con el precio actual del evento.
# - Si la reserva venció, debe informarse el error.
# - Cada compra conserva el precio al que se hizo.
# ==============================================================================


def confirm_reservation(
    reservation_id: int,
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
    purchase_date: Optional[str] = None,
) -> dict[str, Any]:
    """Confirma una reserva vigente, generando la compra en MongoDB y Neo4j.

    Args:
        reservation_id: Identificador de la reserva temporal en Redis.
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.
        purchase_date: Fecha opcional para la compra (formato YYYY-MM-DD).
            Si no se especifica, toma la fecha actual.

    Returns:
        Diccionario con la información de la compra confirmada.

    Raises:
        RuntimeError: Si la reserva no existe o ya venció por TTL.
    """
    res_key = f"reservation:{reservation_id}"
    raw_data = redis_client.get(res_key)

    if raw_data is None:
        raise RuntimeError(
            f"Error al confirmar: La reserva #{reservation_id} no existe o ya ha vencido. "
            "Las reservas no confirmadas vencen a los 10 minutos."
        )

    res_info: dict[str, Any] = json.loads(raw_data)
    user_id = int(res_info["usuario_id"])
    event_id = int(res_info["evento_id"])
    quantity = int(res_info["cantidad"])

    # Obtener el precio actual vigente del evento desde MongoDB
    event_doc = db_mongo.eventos.find_one({"evento_id": event_id})
    if not event_doc:
        raise RuntimeError(f"El evento ID {event_id} ya no existe en el sistema.")

    current_price = int(event_doc.get("precio", res_info.get("precio_unitario", 0)))
    total_amount = current_price * quantity
    date_str = purchase_date if purchase_date is not None else datetime.now().strftime("%Y-%m-%d")

    # Obtener próximo compra_id incremental
    last_purchase = db_mongo.compras.find_one(sort=[("compra_id", -1)])
    new_compra_id = (int(last_purchase["compra_id"]) + 1) if last_purchase else 1

    # 1. Registrar la compra en MongoDB
    purchase_document = {
        "compra_id": new_compra_id,
        "usuario_id": user_id,
        "evento_id": event_id,
        "cantidad": quantity,
        "precio_unitario": current_price,
        "total": total_amount,
        "fecha_compra": date_str,
        "estado": "confirmada",
    }
    db_mongo.compras.insert_one(purchase_document)

    # 2. Registrar la relación en Neo4j (:Usuario)-[:COMPRO]->(:Evento)
    with driver_neo4j.session(database="neo4j") as session:
        cypher_purchase = """
        MATCH (u:Usuario {id: $usuario_id})
        MATCH (e:Evento {id: $evento_id})
        CREATE (u)-[r:COMPRO {
            compra_id: $compra_id,
            cantidad: $cantidad,
            precio_unitario: $precio_unitario,
            total: $total,
            fecha_compra: $fecha_compra,
            estado: $estado
        }]->(e)
        RETURN r
        """
        session.run(
            cypher_purchase,
            usuario_id=user_id,
            evento_id=event_id,
            compra_id=new_compra_id,
            cantidad=quantity,
            precio_unitario=current_price,
            total=total_amount,
            fecha_compra=date_str,
            estado="confirmada",
        )

    # 3. Eliminar la reserva de Redis (las entradas ya quedan definitivamente compradas)
    redis_client.delete(res_key)

    return {
        "compra_id": new_compra_id,
        "usuario_id": user_id,
        "usuario_nombre": res_info.get("usuario_nombre"),
        "evento_id": event_id,
        "evento_nombre": res_info.get("evento_nombre"),
        "cantidad": quantity,
        "precio_unitario": current_price,
        "total": total_amount,
        "fecha_compra": date_str,
        "estado": "confirmada",
        "mensaje": f"Compra #{new_compra_id} confirmada exitosamente por un total de ${total_amount:,.0f}.",
    }


# ==============================================================================
# CONSIGNAS: Sección 2.3 - Cancelar una Reserva
# Regla de negocio: "Cancelar una reserva, liberando las entradas."
# ==============================================================================


def cancel_reservation(
    reservation_id: int,
    redis_client: redis.Redis,
) -> dict[str, Any]:
    """Cancela una reserva vigente y libera las entradas retenidas sumándolas al stock de Redis.

    Args:
        reservation_id: Identificador de la reserva a cancelar.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario con la confirmación de la cancelación y las entradas liberadas.

    Raises:
        RuntimeError: Si la reserva no existe o ya venció.
    """
    res_key = f"reservation:{reservation_id}"
    raw_data = redis_client.get(res_key)

    if raw_data is None:
        raise RuntimeError(f"No se puede cancelar: La reserva #{reservation_id} no existe o ya ha vencido.")

    res_info: dict[str, Any] = json.loads(raw_data)
    event_id = int(res_info["evento_id"])
    quantity = int(res_info["cantidad"])

    # 1. Restituir el stock disponible atómicamente en Redis
    restored_stock = int(redis_client.incrby(f"event:{event_id}:stock", quantity))

    # 2. Eliminar la reserva de Redis
    redis_client.delete(res_key)

    return {
        "reserva_id": reservation_id,
        "evento_id": event_id,
        "evento_nombre": res_info.get("evento_nombre"),
        "entradas_liberadas": quantity,
        "nuevo_stock_disponible": restored_stock,
        "estado": "cancelada",
        "mensaje": (
            f"Reserva #{reservation_id} cancelada. "
            f"Se liberaron {quantity} entradas. Nuevo stock disponible: {restored_stock}."
        ),
    }


# ==============================================================================
# CONSIGNAS: Sección 2 - Demostración de los 3 Casos Obligatorios
# "Demostrar al menos tres casos: una compra exitosa, un intento sin disponibilidad
#  suficiente y una cancelación."
# ==============================================================================


def demonstrate_purchase_flow(
    db_mongo: Database,
    driver_neo4j: Driver,
    redis_client: redis.Redis,
) -> dict[str, Any]:
    """Ejecuta y demuestra los tres casos exigidos por las consignas:

    1. Una compra exitosa completa (reserva -> confirmación).
    2. Un intento sin disponibilidad suficiente (rechazo por cupo).
    3. Una cancelación con liberación y restitución de stock en Redis.

    Args:
        db_mongo: Instancia de base de datos de MongoDB.
        driver_neo4j: Driver de conexión a Neo4j.
        redis_client: Cliente de conexión a Redis.

    Returns:
        Diccionario con los resultados detallados de cada uno de los tres casos.
    """
    results: dict[str, Any] = {}

    print("\n=======================================================")
    print(" DEMOSTRACIÓN DEL FLUJO DE COMPRA (CONSIGNAS: SECCIÓN 2)")
    print("=======================================================")

    # Asegurar sesión activa para el usuario de prueba
    test_user_name = "Juan López"
    create_user_session(test_user_name, db_mongo, redis_client)

    # ------------------------------------------------------------------
    # CASO 1: Compra exitosa completa
    # ------------------------------------------------------------------
    print("\n--- CASO 1: Demostración de Compra Exitosa ---")
    test_event_name = "Fiesta Satelital"  # Evento 6
    stock_before = int(redis_client.get("event:6:stock") or 0)
    print(f"Stock inicial para '{test_event_name}': {stock_before}")

    # Paso 1.1: Reservar 2 entradas
    res_1 = reserve_tickets(
        user=test_user_name,
        event=test_event_name,
        quantity=2,
        db_mongo=db_mongo,
        redis_client=redis_client,
    )
    print(f"[Paso 1 - Reserva] {res_1['mensaje']}")
    stock_after_res = int(redis_client.get("event:6:stock") or 0)
    print(f"Stock luego de reservar 2 entradas: {stock_after_res}")

    # Paso 1.2: Confirmar la reserva
    purchase_1 = confirm_reservation(
        reservation_id=res_1["reserva_id"],
        db_mongo=db_mongo,
        driver_neo4j=driver_neo4j,
        redis_client=redis_client,
    )
    print(f"[Paso 2 - Confirmación] {purchase_1['mensaje']}")
    results["caso_1_exitoso"] = {
        "reserva": res_1,
        "compra": purchase_1,
        "stock_final": stock_after_res,
    }

    # ------------------------------------------------------------------
    # CASO 2: Intento sin disponibilidad suficiente
    # ------------------------------------------------------------------
    print("\n--- CASO 2: Demostración de Intento Sin Disponibilidad Suficiente ---")
    current_avail = int(redis_client.get("event:6:stock") or 0)
    excessive_qty = current_avail + 500  # Más de lo que existe
    print(f"Stock disponible: {current_avail}. Se intentarán reservar: {excessive_qty}.")

    try:
        reserve_tickets(
            user=test_user_name,
            event=test_event_name,
            quantity=excessive_qty,
            db_mongo=db_mongo,
            redis_client=redis_client,
        )
        results["caso_2_sin_disponibilidad"] = {"error": "No falló como se esperaba"}
    except RuntimeError as err:
        print(f"[Rechazo Correcto]: {err}")
        stock_unchanged = int(redis_client.get("event:6:stock") or 0)
        print(f"Verificación de stock intacto: {stock_unchanged}")
        results["caso_2_sin_disponibilidad"] = {
            "error_capturado": str(err),
            "stock_mantenido": stock_unchanged,
            "exito_demostracion": True,
        }

    # ------------------------------------------------------------------
    # CASO 3: Cancelación liberando entradas
    # ------------------------------------------------------------------
    print("\n--- CASO 3: Demostración de Cancelación Liberando Entradas ---")
    stock_pre_cancel = int(redis_client.get("event:6:stock") or 0)
    print(f"Stock antes de reservar: {stock_pre_cancel}")

    # Paso 3.1: Crear reserva temporal
    res_cancel = reserve_tickets(
        user=test_user_name,
        event=test_event_name,
        quantity=3,
        db_mongo=db_mongo,
        redis_client=redis_client,
    )
    stock_during = int(redis_client.get("event:6:stock") or 0)
    print(f"[Reserva Creada] ID #{res_cancel['reserva_id']} por 3 entradas. Stock actual: {stock_during}")

    # Paso 3.2: Cancelar la reserva
    cancel_res = cancel_reservation(
        reservation_id=res_cancel["reserva_id"],
        redis_client=redis_client,
    )
    print(f"[Cancelación] {cancel_res['mensaje']}")
    stock_post_cancel = int(redis_client.get("event:6:stock") or 0)
    print(f"Stock restituido: {stock_post_cancel} (igual al inicial: {stock_post_cancel == stock_pre_cancel})")

    results["caso_3_cancelacion"] = {
        "reserva": res_cancel,
        "cancelacion": cancel_res,
        "stock_restituido": stock_post_cancel,
        "exito_demostracion": stock_post_cancel == stock_pre_cancel,
    }

    print("\n=======================================================")
    print(" DEMOSTRACIÓN FINALIZADA CON ÉXITO")
    print("=======================================================\n")

    return results
