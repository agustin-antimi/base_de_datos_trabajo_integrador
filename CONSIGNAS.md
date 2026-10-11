# Trabajo Práctico Integrador – Bases de Datos 2026
## Sistema de Venta de Entradas y Recomendación de Eventos

* **Bases de datos:** MongoDB, Redis y Neo4j, usadas desde Python en un notebook de JupyterLab.
* **Publicado:** 30/09/2026 · **Entrega:** 23/10/2026 23:59
* **Integrantes:** Grupos de 2 personas (los grupos de 3 deben resolver además el Anexo).
* **Entrega:** Un archivo `.zip` con el apellido de los integrantes en: https://forms.gle/5SjuCiMch4FnFMpy5
* *Ver "Explicación herramientas para trabajo integrador" y usar las herramientas que allí se presentan.*

---

## Contexto

Una productora de espectáculos vende entradas para recitales en distintas ciudades. Necesita un sistema que cumpla tres funciones:
1. **Registrar** usuarios, artistas, lugares, eventos y compras.
2. **Manejar información de vida corta:** qué usuarios están conectados, qué entradas están reservadas pero todavía no se pagaron, y qué se buscó recientemente.
3. **Aprovechar las relaciones** entre usuarios y artistas (amistades, artistas seguidos, artistas similares) para recomendar eventos.

El grupo debe decidir qué información almacenar en cada una de las tres bases, cómo relacionarlas entre sí y justificar esas decisiones. Las tres bases deben usarse, y cada una para lo que mejor resuelve.

El dataset provisto es para MongoDB, es sólo de ayuda, se recomienda agregar más información.

---

## Reglas de Negocio

* **Tiempos de vencimiento:**
  * Una sesión de usuario vence a los **30 minutos**.
  * Una reserva de entradas no confirmada vence a los **10 minutos**, y sus entradas deben volver a estar disponibles.
  * Los resultados de una búsqueda pueden reutilizarse durante **5 minutos**.
* **Entradas disponibles de un evento futuro:**
  $$\text{Disponibles} = \text{cupo} - \text{entradas de compras confirmadas} - \text{entradas en reservas vigentes}$$
  *La disponibilidad nunca puede quedar negativa.*
* **Asistencia:** Un usuario asistió a un evento si tiene una compra confirmada de ese evento y el evento ya ocurrió. La asistencia debe surgir de las compras, **no cargarse por separado**.
* **Precio de las compras:** Cada compra conserva el precio al que se hizo. Si después cambia el precio del evento, las compras anteriores no se modifican.
* **Fecha de referencia (opcional):** Definir `FECHA_REFERENCIA = "2026-10-01"`. Un evento es pasado si su fecha es anterior a esa fecha y futuro en caso contrario. **No se debe guardar en ninguna base.**

---

## Requisitos Técnicos

* La primera sección del notebook debe **limpiar las tres bases**.
* El notebook completo debe **ejecutarse sin errores**.
* **Evitar la duplicación innecesaria de datos.** Si deciden duplicar algo, justificarlo e indicar cuál es la copia "oficial".
* Crear los **índices o restricciones de unicidad** que consideren necesarios, y justificarlos.
* **Toda consulta debe mostrar nombres, no solo IDs.**

---

## 1. Carga Inicial

Cargar el dataset del final distribuyendo la información entre las tres bases según su diseño. Los datos que existan en más de una base deben generarse a partir de los ya cargados, no volver a escribirse a mano.

---

## 2. Flujo de Compra

Implementar en Python estas operaciones:
1. **Reservar entradas** para un usuario y un evento. Solo se permite si el usuario tiene una sesión activa y hay disponibilidad suficiente.
2. **Confirmar una reserva vigente.** Se genera la compra con el precio actual del evento. Si la reserva venció, debe informarse el error.
3. **Cancelar una reserva**, liberando las entradas.

*Demostrar al menos tres casos: una compra exitosa, un intento sin disponibilidad suficiente y una cancelación.*

---

## 3. Consultas

1. Usuarios que asistieron a algún evento de "Los Cóndores Eléctricos".
2. Amigos de Juan López que siguen algún artista que también sigue Juan. Mostrar el nombre del amigo y el artista.
3. Recomendar a Juan artistas que siguen sus amigos y que él no sigue, ordenados por cantidad de amigos que los siguen.
4. Para los artistas del punto anterior, listar sus eventos futuros con lugar, ciudad, fecha, precio y entradas disponibles.
5. Artistas similares a los que sigue Lucía Romero y que ella no sigue.
6. Eventos futuros en La Plata con precio menor a $40.000.
7. Cantidad de eventos futuros por género.
8. Total gastado por cada usuario en compras confirmadas, ordenado de mayor a menor.
9. Entradas vendidas por evento, incluyendo los eventos sin ventas.
10. Usuarios conectados en este momento.
11. Reservas vigentes: usuario, evento, cantidad y tiempo restante antes de que venzan.
12. Los 3 géneros más buscados.

---

## 4. Estadísticas y Gráficos

Generar las siguientes estadísticas, mostrando el valor para cada elemento (no solo el máximo):
* Cantidad de seguidores por artista.
* Recaudación por evento (compras confirmadas).
* Entradas vendidas por lugar.
* Cantidad de búsquedas por género.

*Representar al menos dos de estas estadísticas con gráficos hechos con matplotlib. Los datos de los gráficos deben obtenerse consultando las bases, no desde las listas de Python del dataset.*

---

## 5. Modificaciones

1. Aumentar un 10% el precio de los eventos futuros en Rosario.
2. Agregar el servicio "accesibilidad" al lugar con id 2.
3. **Cancelar el evento 7:**
   * El evento queda cancelado.
   * Sus compras pasan a estado `reembolsada`.
   * No debe quedar disponibilidad ni reservas de ese evento.
   * No debe aparecer en recomendaciones.
4. **Eliminar al usuario Tomás Herrera (id 6) del sistema.** Decidir y justificar qué pasa con sus compras.
5. **Eliminar todas las amistades de un usuario a elección.**

*En los puntos 3 a 5, los cambios deben reflejarse en todas las bases donde haya datos afectados. Después de cada modificación, mostrar una consulta que evidencie el cambio.*

---

## 6. Informe

Puede ir en celdas markdown dentro del notebook o como PDF aparte. Debe incluir:
* Un diagrama o tabla de qué se guarda en cada base y por qué.
* Cómo se integran las bases: qué identificadores las vinculan y qué consultas combinan más de una.
* Respuestas a estas preguntas:
  * ¿Cómo implementaron el vencimiento de las reservas? ¿Las entradas se liberan solas al vencer?
  * ¿Qué datos quedaron en más de una base? ¿Cómo garantizan que no se desincronicen?
  * ¿Qué problemas de consistencia aparecieron al eliminar datos y cómo los resolvieron?
* Capturas o salidas de las consultas y los gráficos.

---

## Entrega

Un archivo `.zip` con:
* El notebook (`.ipynb`) ejecutado, con las salidas visibles.
* El informe, si no está dentro del notebook.
* Un `requirements.txt`.

---

## Anexo: Requisitos Adicionales para Grupos de 3

*Los grupos de 3 integrantes deben resolver todo lo anterior y además estos cuatro puntos:*

1. **Reseñas de eventos:**
   * Un usuario puede calificar (1 a 5) y comentar un evento pasado (para el cual tiene una compra confirmada) y una sola vez por evento. Implementar la operación validando ambas condiciones y demostrar un caso válido y uno rechazado.
   * Cargar al menos 6 reseñas de distintos usuarios.
   * Mostrar el promedio de calificación por evento y por artista (para un artista se consideran las reseñas de todos sus eventos).
2. **Historial de precios:**
   * Cada cambio de precio de un evento debe quedar registrado con su fecha. El precio del dataset se considera vigente desde el `2026-01-01`.
   * Registrar al menos 3 cambios de precio sobre un mismo evento.
   * Consultar el precio vigente de un evento en una fecha dada.
   * Graficar la evolución del precio de ese evento.
3. **Recomendación de dos saltos:**
   * Recomendar a un usuario eventos futuros de artistas similares a los que siguen sus amigos.
   * Excluir los artistas que el usuario ya sigue y los eventos para los que ya tiene una compra confirmada.
   * Mostrar evento, artista y fecha.
   * Ejecutarla antes de la sección 5 (Modificaciones), o con un usuario que conserve sus amistades.
4. **Historial de búsquedas por usuario:**
   * Guardar las últimas 5 búsquedas de cada usuario; las más viejas se descartan.
   * Usar ese historial para ordenar las recomendaciones del punto anterior: primero los eventos cuyo género coincida con alguna búsqueda reciente del usuario.

*En el informe, explicar qué estructura y qué base eligieron para cada punto y por qué.*

---

## Dataset

```python
usuarios = [
    {"usuario_id": 1, "nombre": "Sofía Martínez", "email": "sofia.martinez@example.com", "ciudad": "La Plata", "amigos": [2, 3], "sigue": [2, 5]},
    {"usuario_id": 2, "nombre": "Juan López", "email": "juan.lopez@example.com", "ciudad": "La Plata", "amigos": [1, 4, 5], "sigue": [1, 3]},
    {"usuario_id": 3, "nombre": "Lucía Romero", "email": "lucia.romero@example.com", "ciudad": "CABA", "amigos": [1, 6], "sigue": [2, 4]},
    {"usuario_id": 4, "nombre": "Martín Díaz", "email": "martin.diaz@example.com", "ciudad": "Rosario", "amigos": [2], "sigue": [3, 6]},
    {"usuario_id": 5, "nombre": "Valentina Ruiz", "email": "valentina.ruiz@example.com", "ciudad": "Córdoba", "amigos": [2], "sigue": [1, 4, 6]},
    {"usuario_id": 6, "nombre": "Tomás Herrera", "email": "tomas.herrera@example.com", "ciudad": "La Plata", "amigos": [3], "sigue": [3, 6]}
]

artistas = [
    {"artista_id": 1, "nombre": "Los Cóndores Eléctricos", "genero": "rock", "similares": [6]},
    {"artista_id": 2, "nombre": "La Marea Sur", "genero": "folk", "similares": [5]},
    {"artista_id": 3, "nombre": "Pulso Nocturno", "genero": "electrónica", "similares": [4]},
    {"artista_id": 4, "nombre": "Cumbia Satelital", "genero": "cumbia", "similares": [3]},
    {"artista_id": 5, "nombre": "Viento Norte", "genero": "folk", "similares": [2]},
    {"artista_id": 6, "nombre": "Radio Neón", "genero": "rock", "similares": [1]}
]

lugares = [
    {"lugar_id": 1, "nombre": "Estadio Ciudad", "ciudad": "La Plata", "capacidad": 40000, "servicios": ["estacionamiento", "accesibilidad"]},
    {"lugar_id": 2, "nombre": "Sala Diagonal", "ciudad": "La Plata", "capacidad": 800, "servicios": ["bar"]},
    {"lugar_id": 3, "nombre": "Anfiteatro del Lago", "ciudad": "Córdoba", "capacidad": 5000, "servicios": ["bar", "accesibilidad"]},
    {"lugar_id": 4, "nombre": "Club Río", "ciudad": "Rosario", "capacidad": 2000, "servicios": ["bar", "guardarropa"]}
]

eventos = [
    {"evento_id": 1, "nombre": "Cóndores en vivo", "artistas": [1], "lugar_id": 1, "fecha": "2026-05-10", "genero": "rock", "precio": 45000, "cupo": 500, "estado": "activo"},
    {"evento_id": 2, "nombre": "Marea acústica", "artistas": [2], "lugar_id": 2, "fecha": "2026-06-20", "genero": "folk", "precio": 18000, "cupo": 150, "estado": "activo"},
    {"evento_id": 3, "nombre": "Noche Pulso", "artistas": [3], "lugar_id": 4, "fecha": "2026-08-15", "genero": "electrónica", "precio": 25000, "cupo": 200, "estado": "activo"},
    {"evento_id": 4, "nombre": "Rock del Lago", "artistas": [1, 6], "lugar_id": 3, "fecha": "2026-11-14", "genero": "rock", "precio": 38000, "cupo": 300, "estado": "activo"},
    {"evento_id": 5, "nombre": "Viento Norte en sala", "artistas": [5], "lugar_id": 2, "fecha": "2026-10-24", "genero": "folk", "precio": 20000, "cupo": 150, "estado": "activo"},
    {"evento_id": 6, "nombre": "Fiesta Satelital", "artistas": [4], "lugar_id": 1, "fecha": "2026-12-05", "genero": "cumbia", "precio": 30000, "cupo": 500, "estado": "activo"},
    {"evento_id": 7, "nombre": "Radio Neón Tour", "artistas": [6], "lugar_id": 4, "fecha": "2026-10-10", "genero": "rock", "precio": 22000, "cupo": 200, "estado": "activo"},
    {"evento_id": 8, "nombre": "Pulso Estadio", "artistas": [3], "lugar_id": 1, "fecha": "2026-12-19", "genero": "electrónica", "precio": 42000, "cupo": 400, "estado": "activo"}
]

compras = [
    {"compra_id": 1, "usuario_id": 2, "evento_id": 1, "cantidad": 2, "precio_unitario": 45000, "total": 90000, "fecha_compra": "2026-04-02", "estado": "confirmada"},
    {"compra_id": 2, "usuario_id": 5, "evento_id": 1, "cantidad": 1, "precio_unitario": 45000, "total": 45000, "fecha_compra": "2026-04-10", "estado": "confirmada"},
    {"compra_id": 3, "usuario_id": 3, "evento_id": 1, "cantidad": 2, "precio_unitario": 45000, "total": 90000, "fecha_compra": "2026-04-15", "estado": "cancelada"},
    {"compra_id": 4, "usuario_id": 1, "evento_id": 2, "cantidad": 2, "precio_unitario": 18000, "total": 36000, "fecha_compra": "2026-06-01", "estado": "confirmada"},
    {"compra_id": 5, "usuario_id": 3, "evento_id": 2, "cantidad": 1, "precio_unitario": 18000, "total": 18000, "fecha_compra": "2026-06-05", "estado": "confirmada"},
    {"compra_id": 6, "usuario_id": 4, "evento_id": 3, "cantidad": 3, "precio_unitario": 25000, "total": 75000, "fecha_compra": "2026-07-20", "estado": "confirmada"},
    {"compra_id": 7, "usuario_id": 2, "evento_id": 3, "cantidad": 1, "precio_unitario": 25000, "total": 25000, "fecha_compra": "2026-08-01", "estado": "confirmada"},
    {"compra_id": 8, "usuario_id": 1, "evento_id": 4, "cantidad": 2, "precio_unitario": 38000, "total": 76000, "fecha_compra": "2026-09-10", "estado": "confirmada"},
    {"compra_id": 9, "usuario_id": 5, "evento_id": 6, "cantidad": 4, "precio_unitario": 30000, "total": 120000, "fecha_compra": "2026-09-12", "estado": "confirmada"},
    {"compra_id": 10, "usuario_id": 6, "evento_id": 7, "cantidad": 1, "precio_unitario": 22000, "total": 22000, "fecha_compra": "2026-09-15", "estado": "confirmada"},
    {"compra_id": 11, "usuario_id": 2, "evento_id": 8, "cantidad": 2, "precio_unitario": 42000, "total": 84000, "fecha_compra": "2026-09-18", "estado": "cancelada"},
    {"compra_id": 12, "usuario_id": 4, "evento_id": 5, "cantidad": 2, "precio_unitario": 20000, "total": 40000, "fecha_compra": "2026-09-20", "estado": "confirmada"}
]
```

### Situación al momento de la carga inicial (en Redis):

* **Usuarios conectados:** Sofía Martínez (1), Juan López (2) y Tomás Herrera (6).
* **Reservas sin confirmar:**
  * Lucía Romero (3) tiene 2 entradas para el evento 5.
  * Tomás Herrera (6) tiene 3 entradas para el evento 4.
* **Búsquedas realizadas hasta el momento:**

| Género | Cantidad |
| :--- | :--- |
| Rock | 7 |
| Electrónica | 5 |
| Folk | 3 |
| Cumbia | 2 |
