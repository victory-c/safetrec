"""Classify right-hook and left-cross crashes from party pairs.

A right hook is a property of two parties in the same crash (a driver turning
right and a cyclist going straight). A left cross is the oncoming analogue
(driver turning left). Filtering party *rows* would count the wrong crashes.
Everything here is a CASE_ID groupby.

Strict right hook requires the same stated compass direction. Strict left
cross requires opposite headings (N↔S, E↔W), because the geometries differ.

Movement codes are the reporting officer's reconstruction, not ground truth.
AT_FAULT and PCF_VIOL_CATEGORY are not used to assign blame.
"""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from scipy.stats import fisher_exact

NEWS = frozenset({"N", "S", "E", "W"})
OPPOSITE_DIR = {"N": "S", "S": "N", "E": "W", "W": "E"}
NOT_STATED_MOVE = frozenset({"-", "", "nan", "None"})

Conflict = Literal["right_hook", "left_cross"]


def _party_masks(group: pd.DataFrame) -> dict[str, pd.Series]:
    ptype = group["PARTY_TYPE"]
    move = group["MOVE_PRE_ACC"]
    return {
        "driver": ptype == "1",
        "cyclist": ptype == "4",
        "driver_right": (ptype == "1") & (move == "D"),
        "driver_left": (ptype == "1") & (move == "E"),
        "cyclist_straight": (ptype == "4") & (move == "B"),
        "cyclist_move_unstated": (ptype == "4") & (move.isin(NOT_STATED_MOVE)),
    }


def _same_direction_pair(drivers: pd.DataFrame, cyclists: pd.DataFrame) -> bool:
    """True if some driver and some cyclist share a stated compass direction.

    Right-hook geometry: both parties travel the same way; the driver turns
    right across the cyclist.
    """
    for d_dir in drivers["DIR_OF_TRAVEL"]:
        if d_dir not in NEWS:
            continue
        for c_dir in cyclists["DIR_OF_TRAVEL"]:
            if c_dir == d_dir:
                return True
    return False


def _opposing_direction_pair(drivers: pd.DataFrame, cyclists: pd.DataFrame) -> bool:
    """True if some driver and some cyclist are on opposite compass headings.

    Left-cross geometry: the driver turns left across an oncoming cyclist.
    Pairing is explicit (N↔S, E↔W). A not-equal test would also admit N vs E,
    which is a crossing conflict, not a left cross.
    """
    for d_dir in drivers["DIR_OF_TRAVEL"]:
        opposite = OPPOSITE_DIR.get(d_dir)
        if opposite is None:
            continue
        for c_dir in cyclists["DIR_OF_TRAVEL"]:
            if c_dir == opposite:
                return True
    return False


def _classify_group(
    group: pd.DataFrame,
    driver_turn_col: str,
    direction_rule: Literal["same", "opposite"],
) -> dict[str, object]:
    masks = _party_masks(group)
    drivers_turning = group.loc[masks[driver_turn_col]]
    cyclists_straight = group.loc[masks["cyclist_straight"]]
    cyclists_unstated = group.loc[masks["cyclist_move_unstated"]]

    has_driver = bool(masks["driver"].any())
    has_cyclist = bool(masks["cyclist"].any())
    core = (len(drivers_turning) > 0) and (len(cyclists_straight) > 0)
    loose = (len(drivers_turning) > 0) and (
        len(cyclists_straight) > 0 or len(cyclists_unstated) > 0
    )
    if direction_rule == "same":
        aligned = _same_direction_pair(drivers_turning, cyclists_straight)
    elif direction_rule == "opposite":
        aligned = _opposing_direction_pair(drivers_turning, cyclists_straight)
    else:
        raise ValueError(f"Unknown direction_rule {direction_rule!r}")
    strict = core and aligned
    return {
        "bike_motor_vehicle": has_driver and has_cyclist,
        "core": core,
        "strict": strict,
        "loose": loose,
    }


def classify_conflicts(parties: pd.DataFrame) -> pd.DataFrame:
    """One row per CASE_ID with nested right-hook and left-cross flags."""
    if parties.empty:
        raise ValueError("parties is empty; cannot classify conflicts.")

    rows: list[dict[str, object]] = []
    for case_id, group in parties.groupby("CASE_ID", sort=False):
        right = _classify_group(group, "driver_right", "same")
        left = _classify_group(group, "driver_left", "opposite")
        rows.append(
            {
                "CASE_ID": case_id,
                "bike_motor_vehicle": right["bike_motor_vehicle"],
                "right_hook_strict": right["strict"],
                "right_hook_core": right["core"],
                "right_hook_loose": right["loose"],
                "left_cross_strict": left["strict"],
                "left_cross_core": left["core"],
                "left_cross_loose": left["loose"],
            }
        )
    return pd.DataFrame(rows)


def cyclist_move_unstated(parties: pd.DataFrame) -> pd.DataFrame:
    """Count cyclist MOVE_PRE_ACC values treated as missing for the loose definition.

    Loose only admits `-` / blank / nan — not every non-B code. If this count is
    near zero, a 58→59 lift is expected, not a sign that the branch is dead.
    """
    cyclists = parties.loc[parties["PARTY_TYPE"].astype(str) == "4"].copy()
    move = cyclists["MOVE_PRE_ACC"].astype(str)
    unstated = move.isin(NOT_STATED_MOVE)
    counts = (
        cyclists["MOVE_PRE_ACC"]
        .astype(str)
        .value_counts(dropna=False)
        .rename_axis("MOVE_PRE_ACC")
        .reset_index(name="n_cyclist_parties")
    )
    n_unstated = int(unstated.sum())
    n_cyc = len(cyclists)
    if n_cyc == 0:
        print("cyclist MOVE_PRE_ACC: no cyclist parties")
    else:
        print(
            "cyclist MOVE_PRE_ACC: "
            f"n_cyclist_parties={n_cyc}; "
            f"unstated_for_loose={n_unstated} "
            f"({n_unstated / n_cyc:.1%} of cyclist rows)"
        )
    return counts


def attach_conflicts(crashes: pd.DataFrame, parties: pd.DataFrame) -> pd.DataFrame:
    flags = classify_conflicts(parties)
    merged = crashes.merge(flags, on="CASE_ID", how="left", validate="one_to_one")
    flag_cols = [
        "bike_motor_vehicle",
        "right_hook_strict",
        "right_hook_core",
        "right_hook_loose",
        "left_cross_strict",
        "left_cross_core",
        "left_cross_loose",
    ]
    missing = merged[flag_cols].isna().any(axis=1)
    if missing.any():
        raise RuntimeError(
            f"{int(missing.sum())} crashes did not get party-derived flags. "
            "Join should be one-to-one on CASE_ID."
        )
    for col in flag_cols:
        merged[col] = merged[col].astype(bool)
    return merged


def conflict_summary(crashes_with_flags: pd.DataFrame) -> pd.DataFrame:
    """Counts and shares. Denominator is bicycle–motor-vehicle crashes, not all crashes."""
    n_all = len(crashes_with_flags)
    n_bmv = int(crashes_with_flags["bike_motor_vehicle"].sum())
    if n_bmv == 0:
        raise ValueError("No bicycle–motor-vehicle crashes; shares would be undefined.")

    records = []
    for side, label in (("right_hook", "right hook"), ("left_cross", "left cross")):
        for level in ("strict", "core", "loose"):
            col = f"{side}_{level}"
            n = int(crashes_with_flags[col].sum())
            records.append(
                {
                    "conflict": label,
                    "definition": level,
                    "count": n,
                    "share_of_bike_mv": n / n_bmv,
                    "share_of_all_bike_crashes": n / n_all,
                    "bike_mv_denominator": n_bmv,
                    "all_bike_denominator": n_all,
                }
            )
    return pd.DataFrame(records)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. z=1.96 → ~95%."""
    if n <= 0:
        raise ValueError("Wilson interval is undefined for n=0.")
    if k < 0 or k > n:
        raise ValueError(f"Success count k={k} is outside 0..{n}.")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return max(0.0, center - half), min(1.0, center + half)


def severity_split(crashes_with_flags: pd.DataFrame, flag_col: str) -> pd.DataFrame:
    """Crash-level KABCO for a conflict vs other bicycle–motor-vehicle crashes.

    Both sides are restricted to `bike_motor_vehicle`. The complement is
    bike_mv minus the flagged set. Using all bicycle crashes, or the full
    bike_mv set including the flagged rows, is the wrong comparison.
    """
    if flag_col not in crashes_with_flags.columns:
        raise KeyError(f"{flag_col} is not a column on crashes_with_flags.")
    if "bike_motor_vehicle" not in crashes_with_flags.columns:
        raise KeyError("bike_motor_vehicle is missing; run attach_conflicts first.")
    universe = crashes_with_flags.loc[crashes_with_flags["bike_motor_vehicle"]]
    flagged = universe[flag_col]

    def _dist(frame: pd.DataFrame, group: str) -> pd.DataFrame:
        counts = (
            frame.groupby(["kabco", "severity_label"], dropna=False)
            .size()
            .reset_index(name="count")
        )
        counts["group"] = group
        counts["n_crashes"] = len(frame)
        counts["share"] = counts["count"] / counts["n_crashes"] if len(frame) else 0.0
        return counts

    return pd.concat(
        [
            _dist(universe.loc[flagged], flag_col),
            _dist(universe.loc[~flagged], f"not_{flag_col}"),
        ],
        ignore_index=True,
    )


def fsi_contrast(crashes_with_flags: pd.DataFrame, flag_col: str) -> pd.DataFrame:
    """Killed-or-serious share for a conflict vs other bike–MV crashes.

    Returns one row per group plus a Fisher exact test on the 2×2 table
    (K+A vs B/C/O) × (flagged vs complement). The p-value is reported; this
    function does not decide significance.
    """
    if flag_col not in crashes_with_flags.columns:
        raise KeyError(f"{flag_col} is not a column on crashes_with_flags.")
    universe = crashes_with_flags.loc[crashes_with_flags["bike_motor_vehicle"]]
    flagged = universe.loc[universe[flag_col]]
    complement = universe.loc[~universe[flag_col]]
    if flagged.empty or complement.empty:
        raise ValueError(
            f"FSI contrast for {flag_col} needs a non-empty flagged set and complement "
            f"inside bike_motor_vehicle (n_flagged={len(flagged)}, n_complement={len(complement)})."
        )

    def _row(frame: pd.DataFrame, group: str) -> dict[str, object]:
        ka = int(frame["kabco"].isin(["K", "A"]).sum())
        n = len(frame)
        lo, hi = wilson_interval(ka, n)
        return {
            "group": group,
            "n_crashes": n,
            "k_plus_a": ka,
            "share": ka / n,
            "wilson_lo": lo,
            "wilson_hi": hi,
        }

    flag_row = _row(flagged, flag_col)
    comp_row = _row(complement, f"not_{flag_col}")
    table = [
        [flag_row["k_plus_a"], flag_row["n_crashes"] - flag_row["k_plus_a"]],
        [comp_row["k_plus_a"], comp_row["n_crashes"] - comp_row["k_plus_a"]],
    ]
    odds, pvalue = fisher_exact(table, alternative="two-sided")
    flag_row["fisher_odds_ratio"] = float(odds)
    flag_row["fisher_p_two_sided"] = float(pvalue)
    comp_row["fisher_odds_ratio"] = float(odds)
    comp_row["fisher_p_two_sided"] = float(pvalue)
    return pd.DataFrame([flag_row, comp_row])


def pcf_distribution(crashes_with_flags: pd.DataFrame, flag_col: str) -> pd.DataFrame:
    """Officer PCF category among flagged crashes. Descriptive only — not fault."""
    subset = crashes_with_flags.loc[crashes_with_flags[flag_col]]
    counts = subset["PCF_VIOL_CATEGORY"].value_counts(dropna=False).rename_axis(
        "PCF_VIOL_CATEGORY"
    ).reset_index(name="count")
    counts["share"] = counts["count"] / len(subset) if len(subset) else 0.0
    counts["flag"] = flag_col
    return counts


if __name__ == "__main__":
    from src.load import load_tims_tables

    tables = load_tims_tables()
    crashes = attach_conflicts(tables.crashes, tables.parties)
    summary = conflict_summary(crashes)
    print(summary.to_string(index=False))
    print("\nseverity, right_hook_core vs other bike–MV:")
    print(severity_split(crashes, "right_hook_core").to_string(index=False))
    print("\nFSI contrast:")
    print(fsi_contrast(crashes, "right_hook_core").to_string(index=False))
