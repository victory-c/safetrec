# Alameda County bicycle crash analysis (TIMS / SWITRS, 2023)

Independent student analysis. Not an official SafeTREC, UC Berkeley, CHP, or OTS product. Crash extracts are not in this repository; you download your own TIMS Query & Map files to reproduce.

Two analyses of police-reported bicycle-involved crashes in Alameda County, California, using TIMS exports from UC Berkeley SafeTREC.

- **Analysis A** — where crashes concentrate along continuous stretches of street (corridors), not only at isolated intersections.
- **Analysis B** — how many crashes match a party-coded right hook (driver turning right, cyclist proceeding straight), under three nested definitions.

Counts are **observed concentrations**, not risk. There is no bicycle-volume denominator. Do not read the corridor list as “the most dangerous streets.”

The writeup for a technical reader is [`report/findings.md`](report/findings.md).

## Reproduce

### 1. Python

Python 3.12 was used. From the repo root:

```bash
python3 -m pip install -r requirements.txt
```

`osmnx` is pinned to 2.x. Version 1.x used `ox.get_nearest_edges`, which 2.x removed.

### 2. TIMS export

Create an account at [TIMS](https://tims.berkeley.edu). In **SWITRS Query & Map**:

1. Geography: **Alameda County**
2. Date: **2023-01-01** through **2023-12-31**
3. Filter: bicycle-involved (`BICYCLE_ACCIDENT`)
4. Download the three CSVs: Crashes, Parties, Victims

Place them at:

```
data/raw/Crashes.csv
data/raw/Parties.csv
data/raw/Victims.csv
```

Those files are gitignored, as are the repo-root all-mode CSVs, snapped crash tables, and HTML maps. Do not commit them.

Optional: also download **all** Alameda County fatal/injury crashes for 2023 (no bicycle filter) and save as `Crashes.csv` in the repo root. The pipeline uses it only as a crude all-mode crash count on the same OSM edges.

ACS 2019–2023 5-year table B08006 is loaded from Census FTP (no key) and cached at `data/processed/acs_b08006_alameda_tracts.csv`. `CENSUS_API_KEY` is optional and unused when that cache exists.

### 3. Run

```bash
python3 -m src.load        # schema check and row counts
python3 -m src.righthook   # three right-hook definitions (no OSM)
python3 -m src.run         # full pipeline (2023 extract in data/raw/)
python3 -m src.run --year 2026 --raw-dir data/raw/tims_2026 --no-all-mode
python3 -m src.run --year 2019-2023 --raw-dir data/raw/tims_2019_2023 --no-all-mode --min-crashes 15 --n-years 5
```

The 2026 command writes to `data/processed/2026/` and `report/figures/2026/` and does not overwrite 2023 outputs. 2026 is a provisional TIMS slice (dates in the file end 23 May 2026). The repo-root all-mode `Crashes.csv` is 2023; `--no-all-mode` keeps it out of the 2026 run and out of a five-year pool.

The 2019–2023 command needs Query & Map CSVs in `data/raw/tims_2019_2023/` (see `SOURCE.md` there). TIMS treats 2019–2023 as finalized in this vintage and 2024–2025 as provisional. The corridor floor is 15 (3 per year × 5). Do not chart those years as a trend.

The first `src.run` downloads the OpenStreetMap drive network for the county (several minutes). Later runs load `data/processed/alameda_drive.graphml`.

Outputs:

| Path | What |
|---|---|
| `data/processed/right_hook_summary.csv` | 2023 strict / core / loose counts |
| `data/processed/corridors.csv` | 2023 windows with ≥3 crashes after overlap collapse |
| `report/figures/corridors.png` | 2023 offline map |
| `report/findings.md` | 2023 writeup |
| `data/processed/2026/` and `report/figures/2026/` | Same tables and maps for the provisional 2026 extract |
| `report/findings_2026.md` | 2026 writeup (incomplete year; no corridors at the 3-crash floor) |

`notebooks/analysis.ipynb` reads the saved CSVs after a run.

## What’s in git

Committed: `src/`, `requirements.txt`, writeups, the ACS B08006 cache for Alameda tracts, and empty `data/processed/` / `report/figures/` placeholders.

Not committed: TIMS/CCRS CSVs, snapped crash tables, CASE_ID lists, OSM graphml, and Folium HTML maps. Run `python3 -m src.run` locally after placing your own extracts.

## Verification: TIMS Summary cross-check

Crashes and victims are different objects. This extract was checked against TIMS SWITRS Summary (Fatalities and any level of injuries, accessed 16 Sep 2026) and OTS 2023 Alameda rankings.

| Test | Object | Published | This extract |
|---|---|---:|---:|
| Crash vs crash | All-mode fatal/injury crashes, Alameda 2023 | TIMS Summary **7,084** | Repo-root `Crashes.csv` **7,084** |
| Crash vs crash | Bicycle-involved crashes | TIMS Summary has no bicycle crash metric | Bicycle extract **451**; all-mode `BICYCLE_ACCIDENT=Y` **451**, same CASE_IDs |
| Victim vs victim | Bicyclist killed + injured | TIMS Summary “All Bicyclist Fatalities and Injuries” **452** | `COUNT_BICYCLIST_KILLED` + `COUNT_BICYCLIST_INJURED` = 7 + 445 = **452** |
| Victim vs victim | All persons killed + injured in bicycle-involved crashes | OTS “Bicyclists” **464** | `NUMBER_KILLED` + `NUMBER_INJURED` = **464** |
| Victim vs victim | All modes, all killed + injured | TIMS Summary and OTS **9,509** | All-mode file **9,509** |

451 crashes next to 452 bicyclist casualties is not a crash-count match. Victim rows in the bicycle extract are 514 (1.14 per crash). If a new TIMS download disagrees with 451 bicycle crashes / 7,084 all-mode crashes / 452 bicyclist casualties for Alameda 2023, stop: the export filter does not match this analysis.

The Query & Map date filter was 2023-01-01 through 2023-12-31. The last bicycle crash **in the file** is 2023-12-22. The all-mode extract has 123 crashes on 23–31 Dec and zero of them are bicycle-flagged.

Also expected from `python3 -m src.load`:

- `ACCIDENT_YEAR` is 2023 only
- `COUNTY` is ALAMEDA on every row
- `BICYCLE_ACCIDENT` is Y on every row in `data/raw/Crashes.csv`
- 4 crashes missing `POINT_X` / `POINT_Y`

Also expected from `python3 -m src.righthook`:

- bicycle–motor-vehicle denominator = 393
- right hook core = 58, strict = 21, loose = 59
- left cross core = 50, strict = 18 (opposite headings), loose = 53

## Layout

```
src/load.py        read, validate, join crash → party → victim
src/righthook.py   party-level groupby, three definitions
src/network.py     OSM download, geocode repair, snap
src/corridors.py   sliding windows, scores, intersection baseline
src/viz.py         maps and bar chart
src/run.py         writes processed tables and figures
```

## Limits (also in the findings)

- One calendar year. Not a trend.
- SWITRS undercounts bicycle crashes, especially without a motor vehicle and without a police report.
- 2024–2025 TIMS years are provisional; 2019–2023 are finalized. This study’s crash extract is 2023; the five-year Query & Map download is not in the repo yet.
- Corridor scores are counts (and weak proxies), not danger.
- Right-hook movement codes are the officer’s reconstruction, not fault.
