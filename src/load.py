"""Read TIMS CSVs, check they are the tables we think they are, and join them.

Comments explain *why*. Column names were verified against the actual export
and the TIMS SWITRS codebook in Phase 1 — they are not assumed from memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
ALL_MODE_CRASHES_PATH = PROJECT_ROOT / "Crashes.csv"

# Verified headers from data/raw/*.csv (Phase 1).
CRASH_COLUMNS_REQUIRED = (
    "CASE_ID",
    "ACCIDENT_YEAR",
    "COLLISION_DATE",
    "COLLISION_SEVERITY",
    "NUMBER_KILLED",
    "NUMBER_INJURED",
    "PARTY_COUNT",
    "TYPE_OF_COLLISION",
    "BICYCLE_ACCIDENT",
    "PCF_VIOL_CATEGORY",
    "PRIMARY_RD",
    "SECONDARY_RD",
    "INTERSECTION",
    "CITY",
    "COUNTY",
    "POINT_X",
    "POINT_Y",
    "LATITUDE",
    "LONGITUDE",
    "COUNT_BICYCLIST_KILLED",
    "COUNT_BICYCLIST_INJURED",
)
PARTY_COLUMNS_REQUIRED = (
    "CASE_ID",
    "PARTY_NUMBER",
    "PARTY_TYPE",
    "MOVE_PRE_ACC",
    "DIR_OF_TRAVEL",
    "AT_FAULT",
    "STWD_VEHICLE_TYPE",
)
VICTIM_COLUMNS_REQUIRED = (
    "CASE_ID",
    "PARTY_NUMBER",
    "VICTIM_NUMBER",
    "VICTIM_ROLE",
    "VICTIM_DEGREE_OF_INJURY",
)

# Crash-level COLLISION_SEVERITY → KABCO. TIMS codebook; PDO is not in TIMS.
KABCO_FROM_COLLISION_SEVERITY = {
    1: "K",
    2: "A",
    3: "B",
    4: "C",
    0: "O",
}
COLLISION_SEVERITY_LABEL = {
    1: "fatal",
    2: "suspected_serious",
    3: "suspected_minor_visible",
    4: "possible_injury_pain",
    0: "pdo",
}

# Victim-level codes mixed old (2/3/4) and MMUCC (5/6/7) in the 2023 file.
# TIMS itself collapses 5→2, 6→3, 7→4 for multi-year analysis.
VICTIM_DEGREE_TO_LEGACY = {5: 2, 6: 3, 7: 4}

# Loose Alameda County box used only to *flag* likely-wrong geocodes.
# The real in-county test uses the OSM county polygon in network.py.
ALAMEDA_LON_MIN, ALAMEDA_LON_MAX = -122.40, -121.45
ALAMEDA_LAT_MIN, ALAMEDA_LAT_MAX = 37.44, 37.92


class SchemaError(ValueError):
    """Export is missing columns this analysis needs. Do not guess them."""


@dataclass
class TimsTables:
    crashes: pd.DataFrame
    parties: pd.DataFrame
    victims: pd.DataFrame
    crashes_all_mode: pd.DataFrame | None


def _require_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise SchemaError(
            f"{label} is missing columns {missing}. "
            f"Present columns: {list(frame.columns)}"
        )


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Expected TIMS export at {path}. "
            "Place Crashes.csv, Parties.csv, and Victims.csv in data/raw/."
        )
    return pd.read_csv(path, low_memory=False)


def load_crashes(path: Path | None = None) -> pd.DataFrame:
    path = path or (RAW_DIR / "Crashes.csv")
    crashes = _read_csv(path)
    _require_columns(crashes, CRASH_COLUMNS_REQUIRED, str(path))

    crashes["CASE_ID"] = crashes["CASE_ID"].astype("int64")
    crashes["COLLISION_DATE"] = pd.to_datetime(crashes["COLLISION_DATE"], errors="coerce")
    if crashes["COLLISION_DATE"].isna().any():
        bad = int(crashes["COLLISION_DATE"].isna().sum())
        raise SchemaError(f"{path} has {bad} unparseable COLLISION_DATE values.")

    # Codebook uses a dash for not-stated; this export pads it as '- '.
    crashes["PCF_VIOL_CATEGORY"] = (
        crashes["PCF_VIOL_CATEGORY"].astype(str).str.strip()
    )
    crashes["INTERSECTION"] = crashes["INTERSECTION"].astype(str).str.strip()
    crashes["TYPE_OF_COLLISION"] = crashes["TYPE_OF_COLLISION"].astype(str).str.strip()
    crashes["BICYCLE_ACCIDENT"] = crashes["BICYCLE_ACCIDENT"].astype(str).str.strip()
    crashes["PRIMARY_RD"] = crashes["PRIMARY_RD"].astype(str).str.strip()
    crashes["SECONDARY_RD"] = crashes["SECONDARY_RD"].astype(str).str.strip()
    crashes["CITY"] = crashes["CITY"].astype(str).str.strip()

    crashes["kabco"] = crashes["COLLISION_SEVERITY"].map(KABCO_FROM_COLLISION_SEVERITY)
    crashes["severity_label"] = crashes["COLLISION_SEVERITY"].map(COLLISION_SEVERITY_LABEL)
    unknown_sev = crashes["kabco"].isna()
    if unknown_sev.any():
        codes = sorted(crashes.loc[unknown_sev, "COLLISION_SEVERITY"].unique().tolist())
        raise SchemaError(f"Unexpected COLLISION_SEVERITY values: {codes}")

    crashes["point_missing"] = crashes["POINT_X"].isna() | crashes["POINT_Y"].isna()
    in_box = (
        crashes["POINT_X"].between(ALAMEDA_LON_MIN, ALAMEDA_LON_MAX)
        & crashes["POINT_Y"].between(ALAMEDA_LAT_MIN, ALAMEDA_LAT_MAX)
    )
    crashes["point_outside_bbox"] = ~crashes["point_missing"] & ~in_box
    crashes["officer_gps_present"] = crashes["LATITUDE"].notna() & crashes["LONGITUDE"].notna()
    return crashes


def load_parties(path: Path | None = None) -> pd.DataFrame:
    path = path or (RAW_DIR / "Parties.csv")
    # Keep PARTY_TYPE as text: one row is '-' (not stated). Integer parse would
    # turn that into NaN and silently drop it from type==1 / type==4 checks.
    parties = pd.read_csv(
        path,
        low_memory=False,
        dtype={"PARTY_TYPE": str, "MOVE_PRE_ACC": str, "DIR_OF_TRAVEL": str},
    )
    _require_columns(parties, PARTY_COLUMNS_REQUIRED, str(path))
    parties["CASE_ID"] = parties["CASE_ID"].astype("int64")
    for col in ("PARTY_TYPE", "MOVE_PRE_ACC", "DIR_OF_TRAVEL", "AT_FAULT"):
        parties[col] = parties[col].astype(str).str.strip()
    return parties


def load_victims(path: Path | None = None) -> pd.DataFrame:
    path = path or (RAW_DIR / "Victims.csv")
    victims = _read_csv(path)
    _require_columns(victims, VICTIM_COLUMNS_REQUIRED, str(path))
    victims["CASE_ID"] = victims["CASE_ID"].astype("int64")
    victims["victim_degree_legacy"] = victims["VICTIM_DEGREE_OF_INJURY"].replace(
        VICTIM_DEGREE_TO_LEGACY
    )
    return victims


def load_all_mode_crashes(path: Path | None = None) -> pd.DataFrame | None:
    """Optional parent extract: all Alameda fatal/injury crashes, same year.

    Used only as a crude activity proxy on the same OSM edges. It is not a
    second bicycle dataset.
    """
    path = path or ALL_MODE_CRASHES_PATH
    if not path.exists():
        return None
    all_mode = load_crashes(path)
    return all_mode


def validate_joins(crashes: pd.DataFrame, parties: pd.DataFrame, victims: pd.DataFrame) -> None:
    crash_ids = set(crashes["CASE_ID"])
    party_ids = set(parties["CASE_ID"])
    victim_ids = set(victims["CASE_ID"])

    if party_ids - crash_ids:
        raise SchemaError("Parties contain CASE_IDs that are not in Crashes.")
    if crash_ids - party_ids:
        raise SchemaError("Some crashes have no party rows.")
    if victim_ids - crash_ids:
        raise SchemaError("Victims contain CASE_IDs that are not in Crashes.")
    if crash_ids - victim_ids:
        raise SchemaError("Some crashes have no victim rows.")

    actual_counts = parties.groupby("CASE_ID").size()
    declared = crashes.set_index("CASE_ID")["PARTY_COUNT"]
    mismatched = actual_counts.reindex(declared.index) != declared
    if mismatched.any():
        n = int(mismatched.sum())
        raise SchemaError(f"{n} crashes have PARTY_COUNT ≠ actual party rows.")


def load_tims_tables(
    raw_dir: Path | None = None,
    all_mode_path: Path | None = None,
    include_all_mode: bool = True,
) -> TimsTables:
    raw_dir = raw_dir or RAW_DIR
    crashes = load_crashes(raw_dir / "Crashes.csv")
    parties = load_parties(raw_dir / "Parties.csv")
    victims = load_victims(raw_dir / "Victims.csv")
    validate_joins(crashes, parties, victims)
    all_mode = load_all_mode_crashes(all_mode_path) if include_all_mode else None
    return TimsTables(
        crashes=crashes,
        parties=parties,
        victims=victims,
        crashes_all_mode=all_mode,
    )


def summarize_load(tables: TimsTables) -> str:
    c = tables.crashes
    lines = [
        f"crashes={len(c)}",
        f"parties={len(tables.parties)}",
        f"victims={len(tables.victims)}",
        f"date_min={c['COLLISION_DATE'].min().date()}",
        f"date_max={c['COLLISION_DATE'].max().date()} (last crash in file, not the Query end date)",
        f"point_missing={int(c['point_missing'].sum())}",
        f"point_outside_bbox={int(c['point_outside_bbox'].sum())}",
        f"bicycle_flag_Y={int((c['BICYCLE_ACCIDENT']=='Y').sum())}",
    ]
    if tables.crashes_all_mode is not None:
        lines.append(f"all_mode_crashes={len(tables.crashes_all_mode)}")
    return "\n".join(lines)


if __name__ == "__main__":
    tables = load_tims_tables()
    print(summarize_load(tables))
    print("severity:")
    print(tables.crashes["COLLISION_SEVERITY"].value_counts().sort_index().to_string())
