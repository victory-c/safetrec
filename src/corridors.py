"""Corridor scoring: sliding windows along named OSM streets.

Counts are observed crash concentrations, not risk. Length, ACS commute
share, OSM bike tags, and all-mode crash counts are weak denominators and
are reported beside the counts rather than replacing them.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union

from src.load import PROJECT_ROOT
from src.network import SNAP_ACCEPT_M, SnapResult

WINDOW_M = 800.0
STEP_M = 100.0
MIN_CRASHES = 3
NMS_IOU = 0.5
NEAR_INTERSECTION_M = 30.0

# Alameda CTC High Injury Corridor EPDO (judgment call; not a SafeTREC standard).
EPDO_WEIGHT = {"K": 10, "A": 10, "B": 5, "C": 5, "O": 1}

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ACS_API = (
    "https://api.census.gov/data/2023/acs/acs5"
    "?get=GEO_ID,B08006_001E,B08006_014E&for=tract:*&in=state:06+county:001"
)
ACS_SF_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2023/"
    "table-based-SF/data/5YRData/acsdt5y2023-b08006.dat"
)
ACS_CACHE = PROCESSED_DIR / "acs_b08006_alameda_tracts.csv"
TIGER_TRACTS = "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_06_tract.zip"
TIGER_CACHE = PROCESSED_DIR / "tl_2023_alameda_tracts.geojson"

_ABBREV = (
    (r"\bstreet\b", "st"),
    (r"\bavenue\b", "ave"),
    (r"\bboulevard\b", "blvd"),
    (r"\bdrive\b", "dr"),
    (r"\broad\b", "rd"),
    (r"\blane\b", "ln"),
    (r"\bcourt\b", "ct"),
    (r"\bplace\b", "pl"),
    (r"\bhighway\b", "hwy"),
    (r"\bparkway\b", "pkwy"),
    (r"\bcircle\b", "cir"),
)


class CorridorError(RuntimeError):
    pass


def normalize_street_name(name) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    if isinstance(name, list):
        parts = [str(p).strip() for p in name if str(p).strip()]
        name = parts[0] if parts else None
        if name is None:
            return None
    text = str(name).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    for pat, repl in _ABBREV:
        text = re.sub(pat, repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _as_lines(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [g for g in geom.geoms if not g.is_empty]
    lines = []
    for part in getattr(geom, "geoms", []):
        lines.extend(_as_lines(part))
    return lines


def _overlap_frac(a0: float, a1: float, b0: float, b1: float) -> float:
    """Shared length divided by the shorter window. 0.5 means 'mostly the same stretch'."""
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    shorter = min(a1 - a0, b1 - b0)
    return inter / shorter if shorter > 0 else 0.0


def _score_row(kabco_values: pd.Series) -> dict[str, float]:
    raw = float(len(kabco_values))
    fsi = float(kabco_values.isin(["K", "A"]).sum())
    epdo = float(sum(EPDO_WEIGHT[k] for k in kabco_values))
    return {"raw_count": raw, "fsi_count": fsi, "epdo": epdo}


def build_named_centerlines(drive_edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Merge connected OSM edges that share a normalized name into centerlines."""
    edges = drive_edges.copy()
    edges["name_norm"] = edges["name"].map(normalize_street_name)
    named = edges.dropna(subset=["name_norm"])
    if named.empty:
        raise CorridorError("Drive network has no named edges to build corridors from.")

    records = []
    line_id = 0
    for name_norm, group in named.groupby("name_norm"):
        geoms = [g for g in group.geometry if g is not None and not g.is_empty]
        if not geoms:
            continue
        # unary_union of a simple two-node street is already a LineString.
        # shapely.ops.linemerge refuses that type, so only merge when needed.
        try:
            unioned = unary_union(geoms)
        except (ValueError, TypeError) as exc:
            print(f"Skipping {name_norm!r}: union failed ({exc}).")
            continue
        if unioned.is_empty:
            continue
        if unioned.geom_type == "LineString":
            merged = unioned
        elif unioned.geom_type in {"MultiLineString", "GeometryCollection"}:
            try:
                merged = linemerge(unioned)
            except ValueError:
                merged = unioned
        else:
            print(f"Skipping {name_norm!r}: unexpected geometry {unioned.geom_type}.")
            continue
        for part in _as_lines(merged):
            if part.length < 20:
                continue
            records.append(
                {
                    "line_id": line_id,
                    "name_norm": name_norm,
                    "osm_name": group["name"].map(_first_name).mode().iat[0]
                    if not group["name"].map(_first_name).mode().empty
                    else name_norm,
                    "length_m": float(part.length),
                    "geometry": part,
                }
            )
            line_id += 1
    if not records:
        raise CorridorError("No mergeable named centerlines.")
    return gpd.GeoDataFrame(records, crs=drive_edges.crs)


def _first_name(name) -> str | None:
    if isinstance(name, list):
        return str(name[0]) if name else None
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    return str(name)


def locate_crashes_on_lines(
    crashes_snapped: gpd.GeoDataFrame, centerlines: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Project corridor-eligible crashes onto the nearest named centerline."""
    eligible = crashes_snapped.loc[
        crashes_snapped["snap_ok_for_corridor"]
        & crashes_snapped.geometry.notna()
        & crashes_snapped["osm_name"].notna()
    ].copy()
    if eligible.empty:
        raise CorridorError("No crashes both geocoded and snapped within 40 m of a named street.")

    eligible = eligible.to_crs(centerlines.crs)
    eligible["name_norm"] = eligible["osm_name"].map(normalize_street_name)

    along = []
    line_ids = []
    for row in eligible.itertuples():
        candidates = centerlines.loc[centerlines["name_norm"] == row.name_norm]
        if candidates.empty:
            along.append(np.nan)
            line_ids.append(pd.NA)
            continue
        point: Point = row.geometry
        best_id = None
        best_dist = np.inf
        best_along = np.nan
        for cand in candidates.itertuples():
            dist = cand.geometry.distance(point)
            if dist < best_dist:
                best_dist = dist
                best_id = cand.line_id
                best_along = cand.geometry.project(point)
        # Same 40 m rule: if the merged line is far from the crash, skip.
        if best_dist > SNAP_ACCEPT_M:
            along.append(np.nan)
            line_ids.append(pd.NA)
        else:
            along.append(float(best_along))
            line_ids.append(best_id)

    eligible["along_m"] = along
    eligible["line_id"] = line_ids
    return eligible.dropna(subset=["along_m", "line_id"])


def _all_mode_by_name(all_mode_located: gpd.GeoDataFrame | None) -> dict[str, gpd.GeoDataFrame]:
    if all_mode_located is None or all_mode_located.empty:
        return {}
    return {name: grp for name, grp in all_mode_located.groupby("name_norm")}


def _count_all_mode_near_window(
    pts: gpd.GeoDataFrame | None, window_geom, max_dist_m: float = SNAP_ACCEPT_M
) -> int:
    """All-mode crashes on any same-name fragment whose point is within max_dist of the window.

    Bicycle corridors live on one linemerged fragment. Dual carriageways and
    other same-name pieces get different line_ids, so counting only along_m on
    the bicycle fragment silently drops the opposite direction of the street.
    Distance to the window geometry is the activity proxy; we still require
    the snapped OSM name to match so freeway ramps 10 m away are not included.
    """
    if pts is None or pts.empty:
        return 0
    return int(pts.geometry.distance(window_geom).le(max_dist_m).sum())


def sliding_windows(
    located: gpd.GeoDataFrame,
    centerlines: gpd.GeoDataFrame,
    all_mode_located: gpd.GeoDataFrame | None = None,
) -> pd.DataFrame:
    all_mode_named = _all_mode_by_name(all_mode_located)
    street_totals = {name: len(grp) for name, grp in all_mode_named.items()}
    windows = []
    for line in centerlines.itertuples():
        line_crashes = located.loc[located["line_id"] == line.line_id]
        if line_crashes.empty:
            continue
        length = float(line.length_m)
        if length <= WINDOW_M:
            starts = [0.0]
            ends = [length]
        else:
            starts = list(np.arange(0.0, length - WINDOW_M + 1e-9, STEP_M))
            last = length - WINDOW_M
            if starts[-1] < last - 1e-6:
                starts.append(last)
            ends = [s + WINDOW_M for s in starts]

        same_name_pts = all_mode_named.get(line.name_norm)

        for start, end in zip(starts, ends):
            in_win = line_crashes[(line_crashes["along_m"] >= start) & (line_crashes["along_m"] < end)]
            if in_win.empty:
                continue
            scores = _score_row(in_win["kabco"])
            window_geom = _substring(line.geometry, start, end)
            all_mode_n = _count_all_mode_near_window(same_name_pts, window_geom)
            span = max(end - start, 1.0)
            windows.append(
                {
                    "line_id": int(line.line_id),
                    "name_norm": line.name_norm,
                    "osm_name": line.osm_name,
                    "start_m": float(start),
                    "end_m": float(end),
                    "window_m": float(span),
                    "raw_count": scores["raw_count"],
                    "fsi_count": scores["fsi_count"],
                    "epdo": scores["epdo"],
                    "crashes_per_km": scores["raw_count"] / (span / 1000.0),
                    "all_mode_count": all_mode_n,
                    "all_mode_street_count": int(street_totals.get(line.name_norm, 0)),
                    "case_ids": ",".join(in_win["CASE_ID"].astype(str)),
                    "geometry": window_geom,
                }
            )
    if not windows:
        raise CorridorError("No windows contained any snapped bicycle crashes.")
    return gpd.GeoDataFrame(windows, crs=centerlines.crs)


def _substring(line: LineString, start: float, end: float) -> LineString:
    # Densify so cut points exist, then slice. Why: shapely substring is in 2.0+
    # shapely.ops.substring; use it directly.
    from shapely.ops import substring

    cut = substring(line, start, end)
    if cut is None or cut.is_empty:
        return LineString([line.interpolate(start), line.interpolate(end)])
    if isinstance(cut, Point):
        return LineString([cut, cut])
    return cut


def nms_windows(windows: gpd.GeoDataFrame, score_col: str = "raw_count") -> gpd.GeoDataFrame:
    kept_idx: list[int] = []
    ordered = windows.sort_values(score_col, ascending=False)
    for idx, row in ordered.iterrows():
        overlap = False
        for kept in kept_idx:
            other = windows.loc[kept]
            if row["line_id"] != other["line_id"]:
                continue
            if _overlap_frac(row["start_m"], row["end_m"], other["start_m"], other["end_m"]) >= NMS_IOU:
                overlap = True
                break
        if not overlap:
            kept_idx.append(idx)
    return windows.loc[kept_idx].sort_values(score_col, ascending=False).reset_index(drop=True)


def intersection_baseline(crashes: pd.DataFrame) -> pd.DataFrame:
    ix = crashes.loc[crashes["INTERSECTION"] == "Y"].copy()
    grouped = (
        ix.groupby(["CITY", "PRIMARY_RD", "SECONDARY_RD"], dropna=False)
        .agg(
            raw_count=("CASE_ID", "size"),
            fsi_count=("kabco", lambda s: int(s.isin(["K", "A"]).sum())),
            epdo=("kabco", lambda s: float(sum(EPDO_WEIGHT[k] for k in s))),
        )
        .reset_index()
        .sort_values("raw_count", ascending=False)
    )
    return grouped


def osm_intersection_flag(
    located: gpd.GeoDataFrame, drive_graph_proj
) -> gpd.GeoDataFrame:
    """Flag crashes within 30 m of an OSM node with degree ≥ 4 (simplified intersections)."""
    import networkx as nx
    import osmnx as ox

    nodes = ox.convert.graph_to_gdfs(drive_graph_proj, nodes=True, edges=False)
    degree = dict(nx.degree(drive_graph_proj))
    nodes = nodes.copy()
    nodes["degree"] = [degree.get(i, 0) for i in nodes.index]
    xings = nodes.loc[nodes["degree"] >= 4, ["geometry"]].copy()
    if xings.empty:
        located = located.copy()
        located["near_osm_intersection"] = False
        return located
    crash_proj = located.to_crs(xings.crs)
    joined = crash_proj.sjoin_nearest(
        xings, how="left", max_distance=NEAR_INTERSECTION_M, distance_col="xing_dist_m"
    )
    # sjoin_nearest can duplicate if two nodes tie; keep first per CASE_ID.
    joined = joined[~joined.index.duplicated(keep="first")]
    located = located.copy()
    located["near_osm_intersection"] = joined.reindex(located.index)["xing_dist_m"].notna()
    return located


def load_acs_bike_commute(crs) -> gpd.GeoDataFrame | None:
    """Tract-level ACS 2019–2023 bike-to-work counts.

    Prefers CENSUS_API_KEY when set. Otherwise uses the Census FTP table-based
    summary file (no key) and caches Alameda tracts in ACS_CACHE.
    """
    import os

    if TIGER_CACHE.exists():
        tracts = gpd.read_file(TIGER_CACHE)
        print(f"TIGER tracts from cache {TIGER_CACHE}")
    else:
        tracts = gpd.read_file(TIGER_TRACTS)
        tracts = tracts.loc[tracts["COUNTYFP"] == "001", ["GEOID", "geometry"]].copy()
        TIGER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tracts.to_file(TIGER_CACHE, driver="GeoJSON")
        print(f"TIGER tracts downloaded and cached at {TIGER_CACHE}")
    if "COUNTYFP" in tracts.columns:
        tracts = tracts.loc[tracts["COUNTYFP"] == "001", ["GEOID", "geometry"]].copy()
    else:
        tracts = tracts[["GEOID", "geometry"]].copy()
    if tracts.empty:
        raise CorridorError("TIGER 2023 CA tracts downloaded but Alameda COUNTYFP=001 is empty.")

    key = os.environ.get("CENSUS_API_KEY")
    if key:
        url = ACS_API + f"&key={key}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        header, *rows = payload
        acs = pd.DataFrame(rows, columns=header)
        workers_col, bike_col = "B08006_001E", "B08006_014E"
        print("ACS from Census API (key present).")
    else:
        if not ACS_CACHE.exists() or ACS_CACHE.stat().st_size < 1000:
            print(
                "No CENSUS_API_KEY; downloading ACS 2019–2023 5-year B08006 "
                "from Census FTP summary file (no key required)."
            )
            ACS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            prefix = "1400000US06001"
            with urllib.request.urlopen(ACS_SF_URL, timeout=180) as resp, ACS_CACHE.open("w") as out:
                header_line = resp.readline().decode("utf-8")
                out.write(header_line.replace("|", ","))
                for raw in resp:
                    line = raw.decode("utf-8")
                    if line.startswith(prefix):
                        out.write(line.replace("|", ","))
        else:
            print(f"ACS from cached summary file {ACS_CACHE}")
        acs = pd.read_csv(ACS_CACHE)
        workers_col, bike_col = "B08006_E001", "B08006_E014"

    if "GEO_ID" not in acs.columns:
        raise CorridorError(f"ACS table missing GEO_ID. Columns: {list(acs.columns)}")
    acs["GEOID"] = (
        acs["GEO_ID"].astype(str).str.replace("1400000US", "", regex=False).str.zfill(11)
    )
    tracts["GEOID"] = tracts["GEOID"].astype(str).str.zfill(11)
    acs["workers"] = pd.to_numeric(acs[workers_col], errors="coerce")
    acs["bike_commuters"] = pd.to_numeric(acs[bike_col], errors="coerce")
    acs["bike_commute_share"] = np.where(
        acs["workers"] > 0, acs["bike_commuters"] / acs["workers"], np.nan
    )
    merged = tracts.merge(
        acs[["GEOID", "workers", "bike_commuters", "bike_commute_share"]], on="GEOID"
    )
    if merged.empty:
        raise CorridorError("ACS-TIGER GEOID join produced 0 Alameda tracts.")
    print(f"ACS tracts joined: {len(merged)}; county bike-commute share={acs['bike_commuters'].sum()/acs['workers'].sum():.4f}")
    return merged.to_crs(crs)


def attach_acs_share(windows: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame | None) -> gpd.GeoDataFrame:
    out = windows.copy()
    out["bike_commute_share"] = np.nan
    if tracts is None or out.empty:
        return out
    overlay = gpd.overlay(
        out[["geometry"]].reset_index().rename(columns={"index": "window_ix"}),
        tracts[["geometry", "bike_commute_share", "workers"]],
        how="intersection",
    )
    if overlay.empty:
        return out
    overlay["seg_m"] = overlay.geometry.length
    # Length-weighted average of tract commute share along the window.
    overlay["_weight_num"] = overlay["bike_commute_share"].fillna(0) * overlay["seg_m"].clip(lower=1e-6)
    agg = overlay.groupby("window_ix").agg(
        num=("_weight_num", "sum"),
        den=("seg_m", "sum"),
    )
    share = agg["num"] / agg["den"].clip(lower=1e-6)
    out.loc[share.index, "bike_commute_share"] = share
    return out


def corridor_overlap_with_intersections(
    corridors: gpd.GeoDataFrame, baseline: pd.DataFrame, top_n: int = 15
) -> pd.DataFrame:
    """How many top corridors share a street name with a top officer-flagged intersection."""
    top_c = corridors.head(top_n).copy()
    top_i = baseline.head(top_n).copy()
    top_i["primary_norm"] = top_i["PRIMARY_RD"].map(normalize_street_name)
    top_i["secondary_norm"] = top_i["SECONDARY_RD"].map(normalize_street_name)
    ix_names = set(top_i["primary_norm"].dropna()) | set(top_i["secondary_norm"].dropna())
    top_c["matches_top_intersection_street"] = top_c["name_norm"].isin(ix_names)
    return top_c[
        [
            "osm_name",
            "raw_count",
            "fsi_count",
            "epdo",
            "matches_top_intersection_street",
        ]
    ]


@dataclass
class CorridorOutputs:
    centerlines: gpd.GeoDataFrame
    windows_all: gpd.GeoDataFrame
    corridors: gpd.GeoDataFrame
    located_crashes: gpd.GeoDataFrame
    intersection_table: pd.DataFrame
    overlap: pd.DataFrame


def run_corridor_analysis(
    bike_snap: SnapResult,
    all_mode_snap: SnapResult | None = None,
    min_crashes: int = MIN_CRASHES,
    n_years: float = 1.0,
) -> CorridorOutputs:
    centerlines = build_named_centerlines(bike_snap.drive_edges)
    located = locate_crashes_on_lines(bike_snap.crashes_snapped, centerlines)
    located = osm_intersection_flag(located, bike_snap.drive_graph_proj)

    all_mode_located = None
    if all_mode_snap is not None:
        am = all_mode_snap.crashes_snapped
        n_src = len(am)
        n_geom = int(am.geometry.notna().sum())
        n_ok = int(am["snap_ok_for_corridor"].sum())
        n_named = int((am["snap_ok_for_corridor"] & am["osm_name"].notna()).sum())
        all_mode_located = locate_crashes_on_lines(
            all_mode_snap.crashes_snapped, centerlines
        )
        print(
            "all-mode funnel: "
            f"source={n_src} geocoded={n_geom} snapped≤40m={n_ok} "
            f"named_edge={n_named} located_on_centerline={len(all_mode_located)} "
            f"dropped_before_windows={n_src - len(all_mode_located)}"
        )

    windows = sliding_windows(located, centerlines, all_mode_located)
    if n_years <= 0:
        raise CorridorError(f"n_years must be positive, got {n_years}.")
    windows["crashes_per_year"] = windows["raw_count"] / n_years
    tracts = load_acs_bike_commute(windows.crs)
    windows = attach_acs_share(windows, tracts)
    corridors = nms_windows(windows, score_col="raw_count")
    corridors = corridors.loc[corridors["raw_count"] >= min_crashes].copy()
    intersection_table = intersection_baseline(bike_snap.crashes_snapped)
    overlap = corridor_overlap_with_intersections(corridors, intersection_table)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return CorridorOutputs(
        centerlines=centerlines,
        windows_all=windows,
        corridors=corridors,
        located_crashes=located,
        intersection_table=intersection_table,
        overlap=overlap,
    )
