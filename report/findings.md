# Bicycle crash concentrations and right-hook conflicts in Alameda County, 2023

This note reports two analyses of police-reported, bicycle-involved crashes in Alameda County, using a 2023 extract from UC Berkeley SafeTREC’s Transportation Injury Mapping System (TIMS). Claims stay inside what one year of reported crashes can support.

## Questions

**A.** Where are bicycle crashes concentrated along continuous stretches of street, rather than only at isolated intersections? (Corridor question, not a hot-spot question.)

**B.** How many of those crashes match a party-coded “right hook” — a motor vehicle turning right and a cyclist proceeding straight — and how does that count move when the definition is tightened or loosened? (Classification, not fault.)

## Data and its limits

The extract is three TIMS files (Crashes, Parties, Victims) filtered to Alameda County and `BICYCLE_ACCIDENT = Y`: **451 crashes**, **878 parties**, **514 victim rows**. The Query & Map date filter was calendar 2023 (1 January–31 December). Collision dates **in this bicycle file** run 1 January through **22 December 2023** — that is the last bicycle-involved crash present, not a truncated filter. The all-mode parent extract continues through 31 December and contains 123 crashes on 23–31 Dec, none of them bicycle-flagged.

Joins on `CASE_ID` are complete. A parent extract of all Alameda County fatal and injury crashes in 2023 (**7,084** records) is used only as a crude all-mode activity count on the same named street as each window. That file is not a second bicycle extract: 451 rows are `BICYCLE_ACCIDENT = Y` and 6,633 are not. Those 451 CASE_IDs are identical to this bicycle extract.

Of the 7,084 all-mode rows, 7,034 geocode and snap within 40 m; 6,434 snap to a named OSM edge; **6,427** locate onto a named centerline; 657 never enter a window (unusable coordinates, unnamed motorway edges, or a merged centerline more than 40 m away). All-mode counts on a corridor window include every located crash whose snapped OSM name matches that street and whose point is within 40 m of the window line — including the opposite carriageway when OSM split it onto another `line_id`. They are not a join on the bicycle fragment’s edge keys. A second column, `all_mode_street_count`, is the same name county-wide, so a 517 m OSM stub is not mistaken for the whole arterial.

TIMS does not include property-damage-only crashes. Crash-level severity is 7 fatal (K), 62 suspected serious (A), 251 suspected minor / visible (B), and 131 possible injury (C). Victim-level injury codes still mix legacy (2/3/4) and MMUCC (5/6/7) values; scoring uses crash-level KABCO.

**Geocoding.** SafeTREC `POINT_X` / `POINT_Y` are missing for 4 of 451 crashes. Two additional points fell outside the county polygon. Three crashes were remapped using officer GPS when that point lay inside the county; four remain unmapped. Officer GPS is missing for about half the file. Median snap distance to the OSM drive network is 0.8 m.

**Reporting lag and vintage.** CHP entry typically lags 12–18 months. TIMS’s SWITRS help page (accessed 16 Sep 2026) treats a year as final after CHP issues that year’s annual report. In this vintage, **2019–2023 are finalized**; **2024–2025 are provisional**; 2026 exists only as a Q1 Query & Map slice. TIMS Summary “All Bicyclist Fatalities and Injuries” for Alameda: 2019 496, 2020 401, 2021 388, 2022 520, 2023 **452**, 2024 561, 2025 486. Those are casualties, not crashes. 2023’s 452 matches this extract’s `COUNT_BICYCLIST_KILLED + COUNT_BICYCLIST_INJURED`. This note still uses the 2023 crash extract; a 2019–2023 party-level Query & Map download was not completed in this session (login-walled).

**Underreporting.** Police-reported SWITRS is a floor, not a census. Bike-only falls and crashes without a motor vehicle are systematically missing (58 of 451 crashes have no driver party). Low-speed right hooks that never generate a police report will not appear in Analysis B.

**Count cross-check.** Crashes are not victims. The header 451 is crashes; 7+445=452 is bicyclist casualties. Those landing one apart is not a crash-count match.

| Test | Object | Published figure | This extract | Result |
|---|---|---:|---:|---|
| Crash vs crash | All-mode fatal/injury **crashes**, Alameda 2023 | TIMS SWITRS Summary, “Fatal and Injury Crashes”: **7,084** | Repo-root `Crashes.csv`: **7,084** | Match |
| Crash vs crash | Bicycle-involved **crashes** | TIMS Summary has no bicycle *crash* metric (only casualties) | Bicycle extract and all-mode `BICYCLE_ACCIDENT=Y`: **451**, same CASE_IDs | Internal match; no Summary crash total to compare |
| Victim vs victim | Bicyclist killed + injured | TIMS Summary, “All Bicyclist Fatalities and Injuries”: **452** | `COUNT_BICYCLIST_KILLED` + `COUNT_BICYCLIST_INJURED` = 7 + 445 = **452** | Match |
| Victim vs victim | All killed + injured persons in these bicycle crashes | OTS 2023 Alameda “Bicyclists — victims killed & injured”: **464** | `NUMBER_KILLED` + `NUMBER_INJURED` = 7 + 457 = **464** | Match |
| Victim vs victim | All killed + injured persons, all modes | TIMS Summary “Fatalities and Injuries” and OTS “Total Fatal and Injury”: **9,509** | All-mode file 108 + 9,401 = **9,509** | Match |

Victim **rows** in the bicycle extract are 514 (1.14 per crash), including drivers, passengers, and two uninjured bicyclist rows (degree 0). 454 victim rows attach to a bicyclist party; 452 of those are injured or killed. 6 bicycle-flagged crashes have 0 in the crash-level bicyclist COUNT_ fields. Do not divide 452 by 451 and call it victims per crash.

## Methods

**Analysis A.** Geocoded crashes were snapped to the OpenStreetMap drive network (`osmnx` 2.1). Edges more than 40 m away were retried on the bike network; still farther, they were dropped from corridor scoring. Named OSM edges were merged into centerlines. An 800 m window was slid in 100 m steps along each centerline.

Each window received three scores: raw crash count; FSI (K and A only); and Alameda CTC EPDO weights (K/A = 10, B/C = 5) — a local published precedent, not a SafeTREC standard. Overlapping windows on the same centerline were collapsed when they shared at least half of the shorter window. A stretch is listed only if it retains **at least three** bicycle crashes after that collapse. `crashes_per_year` is `raw_count / n_years` (1.0 for this file). For a five-year pool the reporting floor is **15** (3 per year × 5), not 3, so one-year noise is not promoted; years are pooled for power, not ranked year-over-year.

Crash counts are not risk. No bicycle-kilometers traveled are available. Length (crashes per km) and all-mode 2023 injury/fatal counts sit beside raw counts. The all-mode window count is same snapped OSM name within 40 m of the window line (opposite carriageway included); `all_mode_street_count` is that name county-wide.

ACS 2019–2023 5-year table B08006 (bike to work) is joined by tract from the Census FTP summary file (no API key). Alameda: 379 tracts, 829,369 workers, 11,090 bike commuters, county share **1.34%**. Each window gets a length-weighted mean of the tracts it crosses. That is a crude commute-to-work rate, not bicycle volume on the street, and not a 2023-only rate.

The naive baseline is officer-flagged intersections (`INTERSECTION = Y`), grouped by city and the two named streets.

**Analysis B.** A right hook is a property of a **pair of parties in the same crash**. Classification is a `groupby` on `CASE_ID`. A row filter on “driver turning right or cyclist going straight” would count the wrong crashes.

Codes were re-checked against the export and the TIMS codebook: `PARTY_TYPE` 1 = driver, 4 = bicyclist; `MOVE_PRE_ACC` D = right turn, E = left turn, B = proceeding straight, `-` = not stated; `DIR_OF_TRAVEL` N/S/E/W.

Three nested definitions:

- **Strict (right hook)** — a driver with D, a cyclist with B, and those two parties share a stated compass direction (same way of travel).
- **Strict (left cross)** — a driver with E, a cyclist with B, and those two parties are on **opposite** stated headings: N with S, or E with W. The pairing is explicit. A not-equal test would also admit N vs E, which is a crossing conflict, not a left cross.
- **Core** — the same movements, no direction requirement.
- **Loose** — core, but the cyclist’s movement may be missing or not stated.

The two crash types need different direction rules because their geometries differ: a right hook is a same-direction overtake-and-turn; a left cross is a driver turning across an oncoming cyclist. Copying the right-hook “shared direction” test onto left crosses was wrong and produced an artificial 50 → 4 collapse. The denominator for shares is bicycle–motor-vehicle crashes: at least one driver and one bicyclist (**393**), not all 451. Movement codes are the officer’s reconstruction, not ground truth. `PCF_VIOL_CATEGORY` is tabulated descriptively and is not treated as adjudicated fault.

## What was found

**Corridors — observed counts, not danger.** Five of the twelve windows are in Berkeley. Berkeley is a small share of Alameda County by population and road mileage; Oakland, roughly three times Berkeley’s size, does not appear on this list. The most defensible reading is that the table substantially reflects **where people ride**, not where riding is dangerous. ACS tract bike-commute share along the windows is a weak check on that reading, not a rate: University west 14.2% and University mid 10.0% sit well above the county 1.34%; Hearst west 10.7% vs Hearst east 2.0% on the same named street shows how jumpy a tract overlay is; Meekland is 0.0% (zero ACS bike commuters in the crossed tracts), which is a commute-to-work zero, not a proof that nobody bikes there.

Twelve stretches had at least three bicycle crashes after overlap collapse. Highest raw counts: Hearst Avenue (6), Telegraph Avenue (5), and University Avenue (5), all in Berkeley, then Milvia Street (4) and Warm Springs Boulevard in Fremont (4). University’s FSI (2) and EPDO (35) match Hearst; Telegraph’s five crashes include no FSI.

Hearst appears twice: 690–1490 m (6 crashes) and 200–1000 m (3). Those windows overlap by 310 m. The collapse rule keeps both because 310 is less than half the shorter window (400 m). Adjacent windows on one street are reported separately **by design**. The NMS threshold was not tightened; tightening it would hide a second stretch that the method is built to score.

The officer-flagged intersection table is mostly ones and twos. The top cell is Fremont Boulevard and Margery Drive (3 crashes, 2 FSI). Only the Fremont Boulevard corridor window matches a top intersection street name. Hearst, Telegraph, University, and Milvia do not: the corridor list is not the intersection list with padding.

All-mode window counts are a weak activity proxy, not a bicycle share of “the street.” Warm Springs (4 bicycle / 4 all-mode in the window) and Fremont Boulevard (3 / 3) are 800 m and 517 m slices. The Fremont window sits on a disconnected 517 m OSM fragment; county-wide the named street has 60 all-mode injury crashes and 10 bicycle. Warm Springs as a named OSM street has 7 all-mode and 4 bicycle. TIMS has no PDO, so a quiet 800 m of suburban arterial can be 100% bicycle in one injury year without that being a coding error. University’s 5 bicycle of 19 all-mode in the 600–1400 m window is high for an exposure ratio and still only a count comparison. The gap between University and Warm Springs is not a bicycle volume rate.

These are streets with elevated **observed** bicycle crash counts in 2023, not the most dangerous streets for cyclists.

**Right hooks.**

| Conflict | Definition | Count | Share of bike–MV (n = 393) |
|---|---|---:|---:|
| Right hook | Strict | 21 | 5.3% |
| Right hook | Core | 58 | 14.8% |
| Right hook | Loose | 59 | 15.0% |
| Left cross | Strict | 18 | 4.6% |
| Left cross | Core | 50 | 12.7% |
| Left cross | Loose | 53 | 13.5% |

Under the core definition, right hooks are slightly more common than left crosses (58 vs 50). Under the strict definition they are 21 vs 18 — not the old 21 vs 4, which was the shared-direction rule applied to the wrong geometry. Of 50 core left crosses, 18 are opposite headings, 4 are same-direction (kept in core, dropped from strict), 23 are perpendicular, and 5 have an unstated heading. Strict still throws away about two thirds of the right-hook set because same-direction is the correct right-hook filter and `DIR_OF_TRAVEL` is often blank or a crossing heading.

Loose barely moves the right-hook count (58 → 59). That is not a dead branch. Of 458 cyclist party rows, **7 (1.5%)** have `MOVE_PRE_ACC = -`. Loose only admits blank / not-stated movement, not every non-B code (E, Q, L, and the rest). A one-crash lift is what 1.5% unstated should produce. Incomplete cyclist movement is not the main uncertainty; `DIR_OF_TRAVEL` is.

Among core right hooks: 0 fatal, 3 suspected serious (3/58 = 5.2% killed-or-serious; Wilson 95% interval 1.8–14.1%). Among the other bicycle–motor-vehicle crashes: 5 fatal, 45 suspected serious (50/335 = 14.9%; Wilson 95% 11.5–19.1%). The comparison is `bike_mv − core right hooks` (n = 335), not all 451 bicycle crashes and not the 393 bike–MV set with the hooks still inside. A two-sided Fisher exact test on the 2×2 collapsed to K+A vs not is p = 0.058 (odds ratio 0.31). That is not below 0.05; the intervals overlap. In this reported year, core right hooks were not the more injurious subset. Given underreporting of low-speed hooks and n = 3 killed-or-serious events among hooks, that is a description of the police-reported file, not a test of the full injury distribution.

Officer PCF among core right hooks, description only: 08 improper turning (18), 09 automobile right of way (12), 05 wrong side of road (11). Those are form codes, not findings of fault.

Core n = 58 is large enough to map and too small to support a density cluster. Points are spread across the county (Fremont 15, Oakland 12, Berkeley 8, Union City 7). Oakland has roughly twice Fremont’s population; Fremont still has more core right hooks in this file. That is an observation. It is not a test of suburban right-turn-lane geometry.

33 of 58 are flagged `INTERSECTION = Y`; **25 are N**. Ten non-intersection core cases were read in full (CASE_IDs omitted from this public note). Every one has a driver D and a cyclist B. Four sit ≤6 ft from the named secondary road (near-intersection despite the flag). Six sit 67–883 ft away (midblock / driveway distances on the form). Collision types are mixed (D, B, H, G). The definition is catching plausible D+B pairs, including some the officer did not flag as intersections. It does not prove they were driveway hooks.

OSM bicycle tags are mixed (23 none, 13 `cycleway:right=lane`). This extract cannot test the classic bike-lane-to-the-right geometry. No spatial clustering claim is made.

## What this analysis cannot support

- That these corridors are the most dangerous streets for cycling. There is no bicycle-volume denominator. ACS commute share is attached and remains a crude tract overlay.
- That a 2023 corridor list would hold up over five years. Alameda CTC’s High Injury Network used five years of TIMS data. Several listed windows sit at the three-crash floor. The 2019–2023 party extract needed to re-score those windows has not been downloaded.
- Year-over-year “improvement.” TIMS Summary bicycle casualties for Alameda move around (2020–21 dip, 2022 rebound, 2024 provisional 561). Reporting practice, geocoding, and pandemic-era volumes confound that series; this note does not interpret it as a trend.
- That a driver coded “making a right turn” caused the crash. Movement is not blame. `AT_FAULT` was not used.
- That 58 is the number of right hooks that occurred. It is the number of *reported* injury/fatal crashes whose party codes match the core definition.
- That OSM `cycleway` tags describe the facility present on the day of the crash.
- Trend statements of any kind from the 2023 crash file. The file is one calendar year.

## What would be needed next

Place a Query & Map extract (Alameda, bicycle, 2019-01-01 through 2023-12-31) in `data/raw/tims_2019_2023/` and run:

```
python3 -m src.run --year 2019-2023 --raw-dir data/raw/tims_2019_2023 --no-all-mode --min-crashes 15 --n-years 5
```

`--no-all-mode` because the repo-root all-mode file is 2023 only. The floor of 15 is the one-year three-crash rule scaled by five; `crashes_per_year` is written beside raw count. Do not chart those five years as improvement.

A dated local bike-facility shapefile — not OSM tags — would be the right join for the right-hook geometry question. CHP narratives, if available, could audit a sample of the 58 core cases against the movement codes.

The defensible sentences are: these 800 m stretches had elevated observed bicycle crash counts in 2023 relative to other named streets in this file, in a pattern that tracks where people ride at least as much as where riding is hazardous; and between 21 and 59 reported bicycle–motor-vehicle crashes match a right-hook coding rule, depending on how strictly direction is required.
