"""Módulo de procesamiento estadístico y visualización gráfica con Matplotlib.

Este módulo implementa una arquitectura desacoplada en dos capas:
1. Capa de Estadísticas: Funciones puras que procesan, transforman y agregan los
   datos crudos retornados por las consultas de base de datos.
2. Capa de Visualización: Funciones gráficas puras que reciben las estadísticas
   procesadas y generan figuras de Matplotlib sin interactuar con las bases de datos.
"""

from pathlib import Path
from typing import Any, Optional, Union
import matplotlib.pyplot as plt

# ==============================================================================
# Paleta de Colores y Tokens de Estilo
# ==============================================================================
CHART_THEME: dict[str, str] = {
    "primary": "#3B82F6",    # Azul moderno (Seguidores)
    "secondary": "#10B981",  # Verde esmeralda (Recaudación)
    "accent": "#8B5CF6",     # Púrpura (Entradas por lugar)
    "warning": "#F59E0B",    # Ámbar (Búsquedas)
    "dark": "#1F2937",       # Texto / bordes
    "grid": "#E5E7EB",       # Líneas de guía
}


# ==============================================================================
# 1. CAPA DE ESTADÍSTICAS (Procesamiento y Agregación de Datos)
# ==============================================================================


def build_artist_followers_stats(
    raw_records: list[dict[str, Any]],
    sort_descending: bool = True,
) -> list[dict[str, Any]]:
    """Procesa los registros crudos de artistas y calcula estadísticas de seguidores.

    Args:
        raw_records: Lista de diccionarios retornados por la consulta a la base de datos
            (espera campos como 'artist_id', 'artist_name', 'followers_count' o variantes).
        sort_descending: Si es True, ordena los artistas de mayor a menor cantidad de seguidores.

    Returns:
        Lista de diccionarios con 'artist_id', 'artist_name', 'followers_count' y
        'percentage_share' calculados.
    """
    total_followers = 0
    formatted_items: list[dict[str, Any]] = []

    for item in raw_records:
        artist_id = item.get("artist_id") or item.get("id") or item.get("artista_id")
        artist_name = str(item.get("artist_name") or item.get("nombre") or f"Artista {artist_id}")
        count = int(item.get("followers_count") or item.get("seguidores") or item.get("count") or 0)
        total_followers += count
        formatted_items.append({
            "artist_id": artist_id,
            "artist_name": artist_name,
            "followers_count": count,
        })

    # Calcular participación porcentual y ordenar
    for item in formatted_items:
        share = (item["followers_count"] / total_followers * 100) if total_followers > 0 else 0.0
        item["percentage_share"] = round(share, 2)

    formatted_items.sort(key=lambda x: x["followers_count"], reverse=sort_descending)
    return formatted_items


def build_event_revenue_stats(
    raw_records: list[dict[str, Any]],
    sort_descending: bool = True,
) -> list[dict[str, Any]]:
    """Procesa los registros crudos de eventos y compras para calcular la recaudación total.

    Args:
        raw_records: Lista de diccionarios con datos de eventos y recaudación
            (espera campos como 'event_id', 'event_name', 'total_revenue' o variantes).
        sort_descending: Si es True, ordena de mayor a menor recaudación acumulada.

    Returns:
        Lista de diccionarios con 'event_id', 'event_name', 'total_revenue',
        'formatted_revenue' y 'percentage_share'.
    """
    total_revenue_all = 0
    formatted_items: list[dict[str, Any]] = []

    for item in raw_records:
        event_id = item.get("event_id") or item.get("evento_id") or item.get("id")
        event_name = str(item.get("event_name") or item.get("nombre") or f"Evento {event_id}")
        revenue = int(item.get("total_revenue") or item.get("recaudacion") or item.get("total") or 0)
        total_revenue_all += revenue
        formatted_items.append({
            "event_id": event_id,
            "event_name": event_name,
            "total_revenue": revenue,
            "formatted_revenue": f"${revenue:,.0f}",
        })

    for item in formatted_items:
        share = (item["total_revenue"] / total_revenue_all * 100) if total_revenue_all > 0 else 0.0
        item["percentage_share"] = round(share, 2)

    formatted_items.sort(key=lambda x: x["total_revenue"], reverse=sort_descending)
    return formatted_items


def build_venue_tickets_stats(
    raw_records: list[dict[str, Any]],
    sort_descending: bool = True,
) -> list[dict[str, Any]]:
    """Procesa registros de recintos o lugares para calcular estadísticas de entradas vendidas.

    Args:
        raw_records: Lista de diccionarios retornados por la consulta de lugares
            (espera campos como 'venue_id', 'venue_name', 'tickets_sold' o variantes).
        sort_descending: Si es True, ordena de mayor a menor cantidad de entradas vendidas.

    Returns:
        Lista de diccionarios con 'venue_id', 'venue_name', 'tickets_sold' y 'percentage_share'.
    """
    total_tickets = 0
    formatted_items: list[dict[str, Any]] = []

    for item in raw_records:
        venue_id = item.get("venue_id") or item.get("lugar_id") or item.get("id")
        venue_name = str(item.get("venue_name") or item.get("nombre") or f"Lugar {venue_id}")
        tickets = int(item.get("tickets_sold") or item.get("entradas_vendidas") or item.get("cantidad") or 0)
        total_tickets += tickets
        formatted_items.append({
            "venue_id": venue_id,
            "venue_name": venue_name,
            "tickets_sold": tickets,
        })

    for item in formatted_items:
        share = (item["tickets_sold"] / total_tickets * 100) if total_tickets > 0 else 0.0
        item["percentage_share"] = round(share, 2)

    formatted_items.sort(key=lambda x: x["tickets_sold"], reverse=sort_descending)
    return formatted_items


def build_genre_searches_stats(
    raw_records: Union[list[tuple[Any, float]], list[dict[str, Any]]],
    sort_descending: bool = True,
) -> list[dict[str, Any]]:
    """Procesa tuplas o registros crudos de Redis y estructura estadísticas de búsquedas por género.

    Args:
        raw_records: Lista de tuplas (genero, count) provenientes de zrange con puntajes,
            o lista de diccionarios con claves 'genre' y 'search_count'.
        sort_descending: Si es True, ordena los géneros de mayor a menor cantidad de búsquedas.

    Returns:
        Lista de diccionarios con 'genre', 'search_count' y 'percentage_share'.
    """
    total_searches = 0
    formatted_items: list[dict[str, Any]] = []

    if raw_records and isinstance(raw_records[0], tuple):
        for tuple_itemb in raw_records:
            genre_name = str(tuple_item[0]).capitalize()
            count = int(tuple_item[1])
            total_searches += count
            formatted_items.append({
                "genre": genre_name,
                "search_count": count,
            })
    else:
        for dict_item in raw_records:  # type: ignore[union-attr]
            genre_name = str(dict_item.get("genre") or dict_item.get("genero") or "Otro").capitalize()
            count = int(dict_item.get("search_count") or dict_item.get("cantidad") or dict_item.get("score") or 0)
            total_searches += count
            formatted_items.append({
                "genre": genre_name,
                "search_count": count,
            })

    for item in formatted_items:
        share = (item["search_count"] / total_searches * 100) if total_searches > 0 else 0.0
        item["percentage_share"] = round(share, 2)

    formatted_items.sort(key=lambda x: x["search_count"], reverse=sort_descending)
    return formatted_items


# ==============================================================================
# 2. CAPA DE VISUALIZACIÓN GRÁFICA (Matplotlib Puro)
# ==============================================================================


def plot_artist_followers(
    stats: list[dict[str, Any]],
    ax: Optional[plt.Axes] = None,
    color: str = CHART_THEME["primary"],
    show_labels: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Genera un gráfico de barras con la cantidad de seguidores por artista.

    Args:
        stats: Lista de estadísticas procesadas por build_artist_followers_stats.
        ax: Objeto Axes de Matplotlib opcional. Si es None, crea una nueva figura.
        color: Código de color hexadecimal para las barras.
        show_labels: Si es True, renderiza la cifra exacta sobre cada barra.
        save_path: Ruta de archivo opcional para guardar el gráfico.

    Returns:
        Tupla (Figure, Axes) de Matplotlib.
    """
    created_fig = False
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
        created_fig = True
    else:
        fig = ax.figure

    names = [s["artist_name"] for s in stats]
    counts = [s["followers_count"] for s in stats]

    bars = ax.bar(names, counts, color=color, edgecolor=CHART_THEME["dark"], linewidth=0.8, alpha=0.9)

    ax.set_title("Cantidad de Seguidores por Artista", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Artista", fontsize=11, labelpad=8)
    ax.set_ylabel("Seguidores", fontsize=11, labelpad=8)
    ax.grid(axis="y", linestyle="--", alpha=0.5, color=CHART_THEME["grid"])
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", rotation=25)

    max_val = max(counts) if counts else 1
    ax.set_ylim(0, max_val + 1)

    if show_labels:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{int(height)}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    if created_fig:
        fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, ax


def plot_event_revenue(
    stats: list[dict[str, Any]],
    ax: Optional[plt.Axes] = None,
    color: str = CHART_THEME["secondary"],
    show_labels: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Genera un gráfico de barras horizontales con la recaudación por evento en compras confirmadas.

    Args:
        stats: Lista de estadísticas procesadas por build_event_revenue_stats.
        ax: Objeto Axes de Matplotlib opcional. Si es None, crea una nueva figura.
        color: Código de color hexadecimal para las barras.
        show_labels: Si es True, renderiza el monto en formato moneda junto a cada barra.
        save_path: Ruta de archivo opcional para guardar el gráfico.

    Returns:
        Tupla (Figure, Axes) de Matplotlib.
    """
    created_fig = False
    if ax is None:
        fig, ax = plt.subplots(figsize=(9, 6))
        created_fig = True
    else:
        fig = ax.figure

    # Invertir para que el evento con mayor recaudación aparezca arriba
    reversed_stats = list(reversed(stats))
    names = [s["event_name"] for s in reversed_stats]
    revenues = [s["total_revenue"] for s in reversed_stats]

    bars = ax.barh(names, revenues, color=color, edgecolor=CHART_THEME["dark"], linewidth=0.8, alpha=0.9)

    ax.set_title("Recaudación por Evento (Compras Confirmadas)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Recaudación ($ ARS)", fontsize=11, labelpad=8)
    ax.set_ylabel("Evento", fontsize=11, labelpad=8)
    ax.grid(axis="x", linestyle="--", alpha=0.5, color=CHART_THEME["grid"])
    ax.set_axisbelow(True)

    max_val = max(revenues) if revenues else 1000
    ax.set_xlim(0, max_val * 1.18)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    if show_labels:
        for bar in bars:
            width = bar.get_width()
            ax.annotate(
                f"${width:,.0f}",
                xy=(width, bar.get_y() + bar.get_height() / 2),
                xytext=(6, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=9,
                fontweight="bold",
            )

    if created_fig:
        fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, ax


def plot_tickets_by_venue(
    stats: list[dict[str, Any]],
    ax: Optional[plt.Axes] = None,
    color: str = CHART_THEME["accent"],
    show_labels: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Genera un gráfico de barras con la cantidad de entradas vendidas por lugar o recinto.

    Args:
        stats: Lista de estadísticas procesadas por build_venue_tickets_stats.
        ax: Objeto Axes de Matplotlib opcional. Si es None, crea una nueva figura.
        color: Código de color hexadecimal para las barras.
        show_labels: Si es True, renderiza la cantidad numérica sobre cada barra.
        save_path: Ruta de archivo opcional para guardar el gráfico.

    Returns:
        Tupla (Figure, Axes) de Matplotlib.
    """
    created_fig = False
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
        created_fig = True
    else:
        fig = ax.figure

    names = [s["venue_name"] for s in stats]
    tickets = [s["tickets_sold"] for s in stats]

    bars = ax.bar(names, tickets, color=color, edgecolor=CHART_THEME["dark"], linewidth=0.8, alpha=0.9)

    ax.set_title("Entradas Vendidas por Lugar", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Lugar / Recinto", fontsize=11, labelpad=8)
    ax.set_ylabel("Entradas Vendidas", fontsize=11, labelpad=8)
    ax.grid(axis="y", linestyle="--", alpha=0.5, color=CHART_THEME["grid"])
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", rotation=15)

    max_val = max(tickets) if tickets else 1
    ax.set_ylim(0, max_val + 2)

    if show_labels:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{int(height)}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    if created_fig:
        fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, ax


def plot_genre_searches(
    stats: list[dict[str, Any]],
    ax: Optional[plt.Axes] = None,
    color: str = CHART_THEME["warning"],
    show_labels: bool = True,
    save_path: Optional[Union[str, Path]] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Genera un gráfico de barras con la cantidad de búsquedas por género musical.

    Args:
        stats: Lista de estadísticas procesadas por build_genre_searches_stats.
        ax: Objeto Axes de Matplotlib opcional. Si es None, crea una nueva figura.
        color: Código de color hexadecimal para las barras.
        show_labels: Si es True, renderiza la cantidad numérica sobre cada barra.
        save_path: Ruta de archivo opcional para guardar el gráfico.

    Returns:
        Tupla (Figure, Axes) de Matplotlib.
    """
    created_fig = False
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
        created_fig = True
    else:
        fig = ax.figure

    genres = [s["genre"] for s in stats]
    counts = [s["search_count"] for s in stats]

    bars = ax.bar(genres, counts, color=color, edgecolor=CHART_THEME["dark"], linewidth=0.8, alpha=0.9)

    ax.set_title("Cantidad de Búsquedas por Género Musical", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Género", fontsize=11, labelpad=8)
    ax.set_ylabel("Búsquedas Registradas", fontsize=11, labelpad=8)
    ax.grid(axis="y", linestyle="--", alpha=0.5, color=CHART_THEME["grid"])
    ax.set_axisbelow(True)

    max_val = max(counts) if counts else 1
    ax.set_ylim(0, max_val + 2)

    if show_labels:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{int(height)}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    if created_fig:
        fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, ax


def plot_combined_dashboard(
    followers_stats: list[dict[str, Any]],
    revenue_stats: list[dict[str, Any]],
    venue_stats: list[dict[str, Any]],
    genre_stats: list[dict[str, Any]],
    figsize: tuple[int, int] = (16, 12),
    save_path: Optional[Union[str, Path]] = None,
) -> tuple[plt.Figure, Any]:
    """Genera un dashboard integrado de 2x2 con los cuatro gráficos estadísticos.

    Recibe las cuatro estadísticas ya calculadas, manteniendo completo desacoplamiento
    respecto a las bases de datos.

    Args:
        followers_stats: Estadísticas de seguidores por artista.
        revenue_stats: Estadísticas de recaudación por evento.
        venue_stats: Estadísticas de entradas por lugar.
        genre_stats: Estadísticas de búsquedas por género.
        figsize: Dimensiones de la figura (ancho, alto).
        save_path: Ruta de archivo opcional para guardar el dashboard.

    Returns:
        Tupla (Figure, matriz_de_Axes) de Matplotlib.
    """
    fig, axes = plt.subplots(2, 2, figsize=figsize)

    plot_artist_followers(followers_stats, ax=axes[0, 0])
    plot_event_revenue(revenue_stats, ax=axes[0, 1])
    plot_tickets_by_venue(venue_stats, ax=axes[1, 0])
    plot_genre_searches(genre_stats, ax=axes[1, 1])

    fig.suptitle(
        "Panel Estadístico de Espectáculos y Recitales (Persistencia Políglota)",
        fontsize=16,
        fontweight="bold",
        y=0.99,
    )
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, axes
