"""Download the Alameda County OSM street network and snap crashes to edges.

Uses osmnx 2.1 APIs (graph_from_polygon, nearest_edges, convert.graph_to_gdfs).
The 1.x names get_nearest_edges / graph_to_gdfs under utils_graph are gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import Point

from src.load import PROJECT_ROOT, TimsTables

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DRIVE_GRAPHML = PROCESSED_DIR / "alameda_drive.graphml"
BIKE_GRAPHML = PROCESSED_DIR / "alameda_bike.graphml"
COUNTY_GPKG = PROCESSED_DIR / "alameda_county.gpkg"
CACHE_DIR = PROCESSED_DIR / "cache"

COUNTY_QUERY = "Alameda County, California, USA"
SNAP_ACCEPT_M = 40.0  # beyond this, try the bike network; still farther → unsapped for corridors
RANDOM_SEED = 2023

BIKE_WAY_TAGS = (
    "cycleway",
    "cycleway:left",
    "cycleway:right",
    "cycleway:both",
    "bicycle",
)


class NetworkError(RuntimeError):
    """OSM download, projection, or snap failed in a way we should not hide."""


def configure_osmnx() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR)
    ox.settings.requests_timeout = 300
    ox.settings.log_console = True
    for tag in BIKE_WAY_TAGS:
        if tag not in ox.settings.useful_tags_way:
            ox.settings.useful_tags_way.append(tag)


def load_county_boundary() -> gpd.GeoDataFrame:
    configure_osmnx()
    if COUNTY_GPKG.exists():
        county = gpd.read_file(COUNTY_GPKG)
        if county.empty:
            raise NetworkError(f"{COUNTY_GPKG} exists but has no polygons.")
        return county.to_crs("EPSG:4326")
    try:
        county = ox.geocoder.geocode_to_gdf(COUNTY_QUERY)
    except Exception as exc:
        raise NetworkError(
            f"Nominatim could not find a polygon for {COUNTY_QUERY!r}."
        ) from exc
    if county.empty:
        raise NetworkError(f"Nominatim returned no geometry for {COUNTY_QUERY!r}.")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    county.to_file(COUNTY_GPKG, driver="GPKG")
    return county.to_crs("EPSG:4326")


def _download_graph(network_type: str, graphml_path: Path, county: gpd.GeoDataFrame):
    configure_osmnx()
    if graphml_path.exists():
        return ox.io.load_graphml(graphml_path)
    polygon = county.geometry.union_all()
    try:
        graph = ox.graph.graph_from_polygon(
            polygon,
            network_type=network_type,
            simplify=True,
            retain_all=True,
            truncate_by_edge=True,
        )
    except Exception as exc:
        raise NetworkError(
            f"Overpass download failed for network_type={network_type!r}. "
            "Re-run later; a cached graphml is written only after a full success."
        ) from exc
    ox.io.save_graphml(graph, graphml_path)
    return graph


def load_drive_graph(county: gpd.GeoDataFrame | None = None):
    county = county if county is not None else load_county_boundary()
    return _download_graph("drive", DRIVE_GRAPHML, county)


def load_bike_graph(county: gpd.GeoDataFrame | None = None):
    county = county if county is not None else load_county_boundary()
    return _download_graph("bike", BIKE_GRAPHML, county)


def county_union_4326(county: gpd.GeoDataFrame):
    return county.to_crs("EPSG:4326").geometry.union_all()


def repair_crash_coordinates(
    crashes: pd.DataFrame, county: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Prefer SafeTREC POINT_*; fall back to officer GPS when POINT is missing or outside the county."""
    out = crashes.copy()
    county_geom = county_union_4326(county)

    def _inside(lon, lat) -> bool:
        if pd.isna(lon) or pd.isna(lat):
            return False
        return bool(Point(float(lon), float(lat)).within(county_geom))

    snap_lons: list[float | None] = []
    snap_lats: list[float | None] = []
    sources: list[str] = []
    notes: list[str] = []

    for row in out.itertuples(index=False):
        px, py = row.POINT_X, row.POINT_Y
        ox_lon, ox_lat = row.LONGITUDE, row.LATITUDE
        point_ok = _inside(px, py)
        officer_ok = _inside(ox_lon, ox_lat)

        if point_ok:
            snap_lons.append(float(px))
            snap_lats.append(float(py))
            sources.append("safetrec_point")
            notes.append("")
        elif officer_ok:
            snap_lons.append(float(ox_lon))
            snap_lats.append(float(ox_lat))
            sources.append("officer_gps")
            notes.append(
                "SafeTREC POINT was missing or outside the county; used officer GPS."
            )
        elif pd.notna(px) and pd.notna(py):
            snap_lons.append(None)
            snap_lats.append(None)
            sources.append("unusable")
            notes.append("POINT exists but is outside the county; no usable officer GPS.")
        else:
            snap_lons.append(None)
            snap_lats.append(None)
            sources.append("unusable")
            notes.append("No SafeTREC POINT and no officer GPS inside the county.")

    out["snap_lon"] = snap_lons
    out["snap_lat"] = snap_lats
    out["coordinate_source"] = sources
    out["coordinate_note"] = notes
    return out


def _edge_name(name_value) -> str | None:
    if name_value is None or (isinstance(name_value, float) and pd.isna(name_value)):
        return None
    if isinstance(name_value, list):
        parts = [str(p).strip() for p in name_value if str(p).strip()]
        return parts[0] if parts else None
    text = str(name_value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _facility_tag(data: dict) -> str:
    for key in BIKE_WAY_TAGS:
        val = data.get(key)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if isinstance(val, list):
            val = ",".join(str(v) for v in val if v)
        text = str(val).strip()
        if text and text.lower() not in {"nan", "no", "none"}:
            return f"{key}={text}"
    return "none"


def _lookup_edges(graph_proj, u_list, v_list, k_list) -> list[dict]:
    rows = []
    for u, v, k in zip(u_list, v_list, k_list):
        try:
            data = graph_proj.edges[u, v, k]
        except KeyError as exc:
            raise NetworkError(
                f"Snapped to edge ({u}, {v}, {k}) that is not in the projected graph."
            ) from exc
        rows.append(
            {
                "osm_u": int(u),
                "osm_v": int(v),
                "osm_key": int(k),
                "osm_name": _edge_name(data.get("name")),
                "osm_highway": data.get("highway"),
                "osm_length_m": float(data.get("length", np.nan)),
                "osm_bike_tag": _facility_tag(data),
            }
        )
    return rows


def _nearest_edge_table(graph_proj, lons: np.ndarray, lats: np.ndarray) -> pd.DataFrame:
    points = gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs="EPSG:4326")
    points_proj = points.to_crs(graph_proj.graph["crs"])
    nearest, distances = ox.distance.nearest_edges(
        graph_proj,
        X=points_proj.x.to_numpy(),
        Y=points_proj.y.to_numpy(),
        return_dist=True,
    )
    # osmnx returns an array of (u, v, k) tuples when X/Y are arrays.
    u = [int(edge[0]) for edge in nearest]
    v = [int(edge[1]) for edge in nearest]
    k = [int(edge[2]) for edge in nearest]
    attrs = _lookup_edges(graph_proj, u, v, k)
    table = pd.DataFrame(attrs)
    table["snap_dist_m"] = np.asarray(distances, dtype=float)
    return table


@dataclass
class SnapResult:
    crashes_snapped: gpd.GeoDataFrame
    county: gpd.GeoDataFrame
    drive_graph_proj: object
    bike_graph_proj: object
    drive_edges: gpd.GeoDataFrame


def snap_crashes(
    crashes: pd.DataFrame,
    county: gpd.GeoDataFrame | None = None,
    drive_graph=None,
    bike_graph=None,
) -> SnapResult:
    county = county if county is not None else load_county_boundary()
    repaired = repair_crash_coordinates(crashes, county)

    drive_graph = drive_graph if drive_graph is not None else load_drive_graph(county)
    drive_proj = ox.projection.project_graph(drive_graph)
    bike_proj = ox.projection.project_graph(bike_graph) if bike_graph is not None else None
    drive_edges = ox.convert.graph_to_gdfs(drive_proj, nodes=False, edges=True)

    usable = repaired["snap_lon"].notna() & repaired["snap_lat"].notna()
    snapped_rows = repaired.copy()
    empty_cols = {
        "osm_u": pd.NA,
        "osm_v": pd.NA,
        "osm_key": pd.NA,
        "osm_name": pd.NA,
        "osm_highway": pd.NA,
        "osm_length_m": np.nan,
        "osm_bike_tag": pd.NA,
        "snap_dist_m": np.nan,
        "snap_network": pd.NA,
        "snap_ok_for_corridor": False,
    }
    for col, val in empty_cols.items():
        snapped_rows[col] = val

    if usable.any():
        idx = snapped_rows.index[usable]
        lons = snapped_rows.loc[idx, "snap_lon"].to_numpy(dtype=float)
        lats = snapped_rows.loc[idx, "snap_lat"].to_numpy(dtype=float)
        drive_snap = _nearest_edge_table(drive_proj, lons, lats)
        use_bike = drive_snap["snap_dist_m"] > SNAP_ACCEPT_M
        chosen = drive_snap.copy()
        network = np.where(use_bike.to_numpy(), "bike", "drive")
        if bool(use_bike.any()):
            if bike_graph is None:
                bike_graph = load_bike_graph(county)
                bike_proj = ox.projection.project_graph(bike_graph)
            bike_snap = _nearest_edge_table(bike_proj, lons, lats)
            chosen.loc[use_bike] = bike_snap.loc[use_bike]
        ok = chosen["snap_dist_m"].to_numpy() <= SNAP_ACCEPT_M

        chosen.index = idx
        for col in chosen.columns:
            snapped_rows.loc[idx, col] = chosen[col]
        snapped_rows.loc[idx, "snap_network"] = network
        snapped_rows.loc[idx, "snap_ok_for_corridor"] = ok

    geometry = [
        Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
        for lon, lat in zip(snapped_rows["snap_lon"], snapped_rows["snap_lat"])
    ]
    crashes_gdf = gpd.GeoDataFrame(snapped_rows, geometry=geometry, crs="EPSG:4326")
    return SnapResult(
        crashes_snapped=crashes_gdf,
        county=county,
        drive_graph_proj=drive_proj,
        bike_graph_proj=bike_proj,
        drive_edges=drive_edges,
    )


def snap_tims_tables(tables: TimsTables) -> tuple[SnapResult, SnapResult | None]:
    county = load_county_boundary()
    drive = load_drive_graph(county)
    # Bike graph is downloaded only if a drive snap is farther than 40 m.
    bike_snap = snap_crashes(tables.crashes, county=county, drive_graph=drive, bike_graph=None)
    all_mode_snap = None
    if tables.crashes_all_mode is not None:
        all_mode_snap = snap_crashes(
            tables.crashes_all_mode,
            county=county,
            drive_graph=drive,
            bike_graph=None,
        )
    return bike_snap, all_mode_snap


if __name__ == "__main__":
    from src.load import load_tims_tables

    np.random.seed(RANDOM_SEED)
    tables = load_tims_tables()
    result, _ = snap_tims_tables(tables)
    gdf = result.crashes_snapped
    print(f"snappable={int(gdf.geometry.notna().sum())} of {len(gdf)}")
    print(f"corridor_ok={int(gdf['snap_ok_for_corridor'].sum())}")
    print(gdf["coordinate_source"].value_counts(dropna=False).to_string())
    print(gdf["snap_network"].value_counts(dropna=False).to_string())
    print("snap_dist_m describe:")
    print(gdf.loc[gdf["snap_ok_for_corridor"], "snap_dist_m"].describe().to_string())
