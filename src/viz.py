"""Maps and charts. The matplotlib PNG is the offline map (no tiles, no API key).

Folium HTML is easier to pan around; opening it still fetches OSM tiles unless
you are already viewing cached tiles. Use the PNG when you need a fully
offline figure.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from src.load import PROJECT_ROOT

FIGURES_DIR = PROJECT_ROOT / "report" / "figures"

SEVERITY_COLORS = {
    "K": "#7f0000",
    "A": "#d94801",
    "B": "#fdae6b",
    "C": "#fee6ce",
}
SEVERITY_LABELS = {
    "K": "Fatal",
    "A": "Suspected serious",
    "B": "Visible / minor",
    "C": "Complaint of pain",
}


def _ensure_figures_dir() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return FIGURES_DIR


def _draw_crash_layers(
    ax,
    county: gpd.GeoDataFrame,
    top: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    *,
    line_width: float,
    marker_size: float,
    boundary: bool,
) -> None:
    if boundary:
        county.boundary.plot(ax=ax, color="#666666", linewidth=0.6)
    if not top.empty:
        top.plot(ax=ax, color="#08519c", linewidth=line_width, alpha=0.95)
    for kabco, color in SEVERITY_COLORS.items():
        subset = crashes.loc[crashes["kabco"] == kabco]
        if subset.empty:
            continue
        subset.plot(
            ax=ax, color=color, markersize=marker_size, alpha=0.85, edgecolors="none"
        )
    ax.set_axis_off()


def _set_padded_bounds(ax, geom: gpd.GeoSeries, pad: float = 0.012) -> None:
    minx, miny, maxx, maxy = geom.total_bounds
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)


def _label_corridors(ax, top: gpd.GeoDataFrame) -> None:
    """One label per street name, at the window centroid."""
    seen: set[str] = set()
    for _, row in top.iterrows():
        name = str(row.osm_name)
        if name in seen or row.geometry is None:
            continue
        seen.add(name)
        c = row.geometry.centroid
        ax.annotate(
            name,
            xy=(c.x, c.y),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=7,
            color="#08306b",
        )


def plot_corridor_map(
    county: gpd.GeoDataFrame,
    corridors: gpd.GeoDataFrame,
    located_crashes: gpd.GeoDataFrame,
    path: Path | None = None,
    top_n: int = 20,
    year: str = "2023",
) -> Path:
    """Offline map: county overview plus zooms so the blue stretches are readable."""
    out = path or (_ensure_figures_dir() / "corridors.png")
    county_p = county.to_crs("EPSG:4326")
    top = corridors.head(top_n).to_crs("EPSG:4326")
    crashes = located_crashes.to_crs("EPSG:4326")

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 6.4), width_ratios=[1.05, 1, 1])
    _draw_crash_layers(
        axes[0], county_p, top, crashes, line_width=2.0, marker_size=8, boundary=True
    )
    axes[0].set_title("County")

    if not top.empty:
        # bounds maxy is longitude-safe enough to split Berkeley from Fremont
        north = top.loc[top.geometry.bounds["maxy"] >= 37.75]
        south = top.loc[top.geometry.bounds["maxy"] < 37.75]
    else:
        north = top
        south = top

    _draw_crash_layers(
        axes[1], county_p, north, crashes, line_width=3.2, marker_size=18, boundary=True
    )
    if not north.empty:
        _set_padded_bounds(axes[1], north.geometry, pad=0.018)
        _label_corridors(axes[1], north)
    axes[1].set_title("Berkeley / north cluster")

    _draw_crash_layers(
        axes[2], county_p, south, crashes, line_width=3.2, marker_size=18, boundary=True
    )
    if not south.empty:
        _set_padded_bounds(axes[2], south.geometry, pad=0.03)
        _label_corridors(axes[2], south)
    axes[2].set_title("Fremont / south cluster")

    n_shown = min(top_n, len(corridors))
    if n_shown == 0:
        headline = (
            f"Alameda County bicycle crashes, {year} · no 800 m window reached 3 crashes\n"
            "Points colored by crash-level KABCO. Observed counts, not risk."
        )
    else:
        headline = (
            f"Alameda County bicycle crashes, {year} · top {n_shown} corridors by raw count (blue)\n"
            "Points colored by crash-level KABCO. Observed counts, not risk."
        )
    fig.suptitle(headline, fontsize=11)
    handles = [
        Line2D([0], [0], color="#08519c", lw=2.2, label="Top corridors"),
        *[
            Patch(facecolor=color, edgecolor="none", label=SEVERITY_LABELS[k])
            for k, color in SEVERITY_COLORS.items()
        ],
    ]
    axes[0].legend(
        handles=handles, loc="lower left", frameon=True, fontsize=7, framealpha=0.92
    )
    fig.text(
        0.5,
        0.02,
        f"TIMS/SWITRS {year} · SafeTREC geocodes. No basemap tiles — this figure renders offline.",
        ha="center",
        fontsize=8,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def plot_severity_bars(
    summary: pd.DataFrame, path: Path | None = None, year: str = "2023"
) -> Path:
    out = path or (_ensure_figures_dir() / "right_hook_counts.png")
    right = summary.loc[summary["conflict"] == "right hook"]
    left = summary.loc[summary["conflict"] == "left cross"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    x = range(len(right))
    width = 0.35
    ax.bar([i - width / 2 for i in x], right["count"], width, label="Right hook", color="#08519c")
    ax.bar([i + width / 2 for i in x], left["count"], width, label="Left cross", color="#9ecae1")
    ax.set_xticks(list(x))
    ax.set_xticklabels(right["definition"])
    ax.set_ylabel(f"Crashes ({year})")
    ax.set_xlabel("Definition")
    ax.set_title(f"Bicycle–motor-vehicle turning conflicts, Alameda County {year}")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def write_folium_map(
    county: gpd.GeoDataFrame,
    corridors: gpd.GeoDataFrame,
    located_crashes: gpd.GeoDataFrame,
    path: Path | None = None,
    top_n: int = 20,
) -> Path:
    import folium

    out = path or (_ensure_figures_dir() / "corridors.html")
    county_4326 = county.to_crs("EPSG:4326")
    center = county_4326.geometry.union_all().centroid
    fmap = folium.Map(
        location=[center.y, center.x],
        zoom_start=11,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.GeoJson(
        county_4326.__geo_interface__,
        name="Alameda County",
        style_function=lambda _: {
            "fillOpacity": 0,
            "color": "#444444",
            "weight": 1,
        },
    ).add_to(fmap)

    top = corridors.head(top_n).to_crs("EPSG:4326")
    for _, row in top.iterrows():
        folium.GeoJson(
            row.geometry.__geo_interface__,
            name=str(row.osm_name),
            style_function=lambda _: {"color": "#08519c", "weight": 5, "opacity": 0.85},
            tooltip=(
                f"{row.osm_name}: {int(row.raw_count)} crashes, "
                f"{int(row.fsi_count)} FSI, EPDO {int(row.epdo)}"
            ),
        ).add_to(fmap)

    crashes = located_crashes.to_crs("EPSG:4326")
    for _, row in crashes.iterrows():
        if row.geometry is None:
            continue
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            color=SEVERITY_COLORS.get(row.kabco, "#888888"),
            fill=True,
            fill_opacity=0.85,
            weight=0,
            tooltip=f"{row.CITY} · {row.severity_label} · {row.PRIMARY_RD}",
        ).add_to(fmap)

    folium.LayerControl().add_to(fmap)
    fmap.save(str(out))
    return out


def write_right_hook_folium(
    crashes_snapped: gpd.GeoDataFrame,
    path: Path | None = None,
) -> Path | None:
    """Dot map of core right-hook crashes. Skip if none are mappable."""
    import folium

    subset = crashes_snapped.loc[
        crashes_snapped.get("right_hook_core", False)
        & crashes_snapped.geometry.notna()
    ]
    if subset.empty:
        return None
    out = path or (_ensure_figures_dir() / "right_hooks.html")
    subset = subset.to_crs("EPSG:4326")
    fmap = folium.Map(
        location=[subset.geometry.y.mean(), subset.geometry.x.mean()],
        zoom_start=11,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    for _, row in subset.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=5,
            color="#08519c",
            fill=True,
            fill_opacity=0.8,
            weight=0,
            tooltip=f"{row.CITY} · {row.PRIMARY_RD} & {row.SECONDARY_RD} · {row.severity_label}",
        ).add_to(fmap)
    fmap.save(str(out))
    return out
