"""Run the Alameda bicycle crash analyses and write outputs.

Usage, from the repo root:

    python3 -m src.run
    python3 -m src.run --year 2026 --raw-dir data/raw/tims_2026 --no-all-mode
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.corridors import PROCESSED_DIR as DEFAULT_PROCESSED
from src.corridors import run_corridor_analysis
from src.load import PROJECT_ROOT, load_tims_tables, summarize_load
from src.network import RANDOM_SEED, snap_tims_tables
from src.righthook import (
    attach_conflicts,
    conflict_summary,
    cyclist_move_unstated,
    fsi_contrast,
    pcf_distribution,
    severity_split,
)
from src.viz import (
    FIGURES_DIR as DEFAULT_FIGURES,
)
from src.viz import (
    plot_corridor_map,
    plot_severity_bars,
    write_folium_map,
    write_right_hook_folium,
)


def _write_csv(frame: pd.DataFrame, processed_dir: Path, name: str) -> None:
    path = processed_dir / name
    frame.to_csv(path, index=False)
    print(f"wrote {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alameda bicycle crash corridor/right-hook run")
    parser.add_argument("--year", default="2023")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=None,
        help="Defaults to data/processed, or data/processed/<year> when year is not 2023.",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=None,
        help="Defaults to report/figures, or report/figures/<year> when year is not 2023.",
    )
    parser.add_argument(
        "--no-all-mode",
        action="store_true",
        help="Do not join the repo-root all-mode Crashes.csv (use for 2026; that file is 2023).",
    )
    parser.add_argument(
        "--min-crashes",
        type=int,
        default=3,
        help="Minimum bicycle crashes in an 800 m window after NMS. Default 3 (one-year floor). Use 15 for a five-year pool (3/year × 5).",
    )
    parser.add_argument(
        "--n-years",
        type=float,
        default=1.0,
        help="Span of the extract in years. Divides raw_count into crashes_per_year. Default 1.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    year = str(args.year)
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else PROJECT_ROOT / args.raw_dir
    if args.processed_dir is not None:
        processed_dir = (
            args.processed_dir
            if args.processed_dir.is_absolute()
            else PROJECT_ROOT / args.processed_dir
        )
    elif year == "2023":
        processed_dir = DEFAULT_PROCESSED
    else:
        processed_dir = DEFAULT_PROCESSED / year
    if args.figures_dir is not None:
        figures_dir = (
            args.figures_dir
            if args.figures_dir.is_absolute()
            else PROJECT_ROOT / args.figures_dir
        )
    elif year == "2023":
        figures_dir = DEFAULT_FIGURES
    else:
        figures_dir = DEFAULT_FIGURES / year

    np.random.seed(RANDOM_SEED)
    processed_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    include_all_mode = not args.no_all_mode
    tables = load_tims_tables(raw_dir=raw_dir, include_all_mode=include_all_mode)
    print(summarize_load(tables))
    print(f"year={year} raw={raw_dir} processed={processed_dir} figures={figures_dir}")

    crashes = attach_conflicts(tables.crashes, tables.parties)
    tables.crashes = crashes
    print("\nCyclist movement codes (loose definition uses only blank / '-' ):")
    print(cyclist_move_unstated(tables.parties).to_string(index=False))
    summary = conflict_summary(crashes)
    sev = severity_split(crashes, "right_hook_core")
    pcf = pcf_distribution(crashes, "right_hook_core")
    contrast = fsi_contrast(crashes, "right_hook_core")
    _write_csv(summary, processed_dir, "right_hook_summary.csv")
    _write_csv(sev, processed_dir, "right_hook_severity.csv")
    _write_csv(pcf, processed_dir, "right_hook_pcf.csv")
    _write_csv(contrast, processed_dir, "right_hook_fsi_contrast.csv")
    print(summary.to_string(index=False))
    print("\nFSI contrast (K+A, bike–MV complement):")
    print(contrast.to_string(index=False))

    print("\nDownloading / loading OSM network and snapping crashes…")
    bike_snap, all_mode_snap = snap_tims_tables(tables)
    snapped = bike_snap.crashes_snapped
    _write_csv(
        snapped.drop(columns="geometry", errors="ignore"),
        processed_dir,
        "crashes_snapped.csv",
    )
    print(
        "snapped "
        f"{int(snapped.geometry.notna().sum())}/{len(snapped)}; "
        f"corridor-eligible {int(snapped['snap_ok_for_corridor'].sum())}"
    )
    print(snapped["coordinate_source"].value_counts(dropna=False).to_string())

    print("\nScoring corridors…")
    corridor_out = run_corridor_analysis(
        bike_snap,
        all_mode_snap,
        min_crashes=args.min_crashes,
        n_years=args.n_years,
    )
    corridors = corridor_out.corridors
    _write_csv(
        corridors.drop(columns="geometry", errors="ignore"),
        processed_dir,
        "corridors.csv",
    )
    _write_csv(corridor_out.intersection_table, processed_dir, "intersection_baseline.csv")
    _write_csv(corridor_out.overlap, processed_dir, "corridor_vs_intersection.csv")
    print(f"corridors with ≥{args.min_crashes} crashes after NMS (n_years={args.n_years}): {len(corridors)}")
    if not corridors.empty:
        cols = [
            "osm_name",
            "raw_count",
            "crashes_per_year",
            "fsi_count",
            "epdo",
            "crashes_per_km",
            "all_mode_count",
            "all_mode_street_count",
            "bike_commute_share",
        ]
        present = [c for c in cols if c in corridors.columns]
        print(corridors[present].head(15).to_string(index=False))

    png = plot_corridor_map(
        bike_snap.county,
        corridors,
        corridor_out.located_crashes,
        path=figures_dir / "corridors.png",
        year=year,
    )
    html = write_folium_map(
        bike_snap.county,
        corridors,
        corridor_out.located_crashes,
        path=figures_dir / "corridors.html",
    )
    bars = plot_severity_bars(
        summary, path=figures_dir / "right_hook_counts.png", year=year
    )
    rh_html = write_right_hook_folium(
        snapped, path=figures_dir / "right_hooks.html"
    )
    print(f"wrote {png}")
    print(f"wrote {html}")
    print(f"wrote {bars}")
    if rh_html is not None:
        print(f"wrote {rh_html}")


if __name__ == "__main__":
    main()
