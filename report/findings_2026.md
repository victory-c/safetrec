# Bicycle crash concentrations and right-hook conflicts in Alameda County, 2026 (provisional)

This note repeats the 2023 corridor and right-hook analyses on a TIMS Query & Map extract of Alameda County bicycle-involved crashes dated 2026. It uses the same party-level definitions, the same 800 m sliding windows, and the same three-crash reporting floor. The claims stay inside what a **provisional, incomplete year** can support.

This is not an update of the 2023 corridor list. It is a rerun on a thinner file.

## Questions

**A.** Where are bicycle crashes concentrated along continuous stretches of street, rather than only at isolated intersections?

**B.** How many of those crashes match a party-coded “right hook” (driver turning right, cyclist proceeding straight), and how does that count move under strict / core / loose definitions?

## Data and its limits

The extract is three TIMS files in `data/raw/tims_2026/`, Query & Map: Alameda County, 1 January–31 December 2026, Bicycle Crash = Yes. After loading: **107 crashes**, **202 parties**, **116 victim rows**. Joins on `CASE_ID` are complete.

Collision dates in the file run only **1 January through 23 May 2026**. TIMS’s own form, at download, stated that **2014–2026 Q1** is what is posted, and that 2024–2026 is provisional. CHP data entry typically lags 12–18 months. Expect this count to rise in later quarterly extracts. A 2026 total of 107 bicycle injury/fatal crashes is not comparable to the 451 in the finalized 2023 file.

TIMS still excludes property-damage-only crashes. Crash-level severity here is 0 fatal, 10 suspected serious (A), 64 suspected minor / visible (B), 33 possible injury (C). Sixteen of 107 crashes have no driver party.

**Geocoding.** Two crashes have SafeTREC `POINT_X`/`POINT_Y` of (0, 0) and no officer GPS (Livermore L St; Fremont Niles Canyon Rd). They are unmapped. 105 of 107 snapped; all 105 were corridor-eligible. No all-mode 2026 TIMS extract was used; the repo-root all-mode file is 2023 and was not mixed in.

**Underreporting** still applies: SWITRS is a floor. Low-speed hooks without a police report are missing. Police-reported 2026 is even more incomplete than usual because CHP has not finished the year.

City counts in this file (Berkeley 32, unincorporated 26, Pleasanton 14, Oakland 4) are **not** a finding that Oakland got safer. Oakland’s 2023 count in the bicycle extract was much higher. The gap is consistent with delayed CHP entry, not with a finished year of local reporting.

## Methods

Same as 2023. Crashes snap to the cached OSM drive network (40 m, then bike network). Named centerlines; 800 m windows, 100 m step; NMS if overlap/min(window lengths) ≥ 0.5; report only windows with **at least three** bicycle crashes. Scores: raw count, FSI, Alameda CTC EPDO (K/A = 10, B/C = 5). Baseline: officer `INTERSECTION = Y` by city + two street names.

Right hook is a `groupby` on `CASE_ID`: driver `PARTY_TYPE=1` and `MOVE_PRE_ACC=D`, cyclist `PARTY_TYPE=4` and `MOVE_PRE_ACC=B`. Strict right hook adds a **shared** compass direction. Strict left cross (driver `E`) requires **opposite** headings (N with S, E with W), because that geometry is oncoming, not same-direction. Loose allows unstated cyclist movement. Denominator is bicycle–motor-vehicle crashes (**91**), not 107. Movement codes are officer reconstruction. `PCF_VIOL_CATEGORY` is descriptive, not fault.

## What was found

**Corridors.** After the same overlap collapse, **zero** 800 m windows retained three or more bicycle crashes. The officer-flagged intersection table is all ones: no cell has two crashes. With 107 events spread across the county, the 2023 method’s reporting floor is not met anywhere.

That is a sample-size result, not a safety result. Hearst, Telegraph, University, and Milvia were high-count stretches in the finished 2023 file. Their absence from a 2026 list does not mean those streets cooled. It means this extract does not yet have three bicycle crashes on any one 800 m named stretch.

The offline map (`report/figures/2026/corridors.png`) therefore shows crash points by KABCO and no blue corridor lines. Berkeley still has the densest cloud of points in this file. That is where the incomplete records piled up, not a new HIN.

**Right hooks.**

| Conflict | Definition | Count | Share of bike–MV (n = 91) |
|---|---|---:|---:|
| Right hook | Strict | 4 | 4.4% |
| Right hook | Core | 20 | 22.0% |
| Right hook | Loose | 20 | 22.0% |
| Left cross | Strict | 7 | 7.7% |
| Left cross | Core | 18 | 19.8% |
| Left cross | Loose | 18 | 19.8% |

Core right hooks (20) are slightly more common than core left crosses (18), as in 2023. Strict left cross is 7, not empty: the old 0 was the same-direction rule applied to oncoming geometry. Of 18 core left crosses, 7 are opposite headings and 11 are perpendicular. Loose does not move the right-hook count (20 = 20): cyclist `MOVE_PRE_ACC` is complete in this small set. The strict-to-core drop for right hooks (4 vs 20) is again `DIR_OF_TRAVEL`.

Among core right hooks: 0 fatal, 0 suspected serious, 13 visible/minor, 7 complaint of pain (0/20 killed-or-serious). Among the other bicycle–motor-vehicle crashes (n = 71): 0 fatal, 5 suspected serious. All 10 suspected-serious crashes in the extract sit outside the core right-hook set; 5 of those 10 have no driver party and are not in this complement. With n = 20 that is a description, not a test.

Officer PCF among core right hooks, description only: 08 improper turning (5), 05 wrong side of road (3), 12 traffic signals and signs (3).

Core n = 20 is below the 25-crash threshold used in 2023 for even a cautious spatial look. Points are spread (unincorporated 5, Berkeley 4, Dublin / Fremont / Pleasanton 3 each). 10 of 20 are flagged `INTERSECTION = Y`. No clustering claim is made. The share of bike–MV (22%) is higher than 2023’s 15%; do not read that as a real increase. The 2026 denominator is 91 crashes in five incomplete months.

## What this analysis cannot support

- That 2026 has no bicycle corridors, or that 2023’s Hearst / Telegraph / University list is obsolete.
- That Oakland’s four records mean Oakland had few bicycle crashes in 2026.
- Year-over-year rates, ranks, or “improvement.”
- That 20 is the number of right hooks that occurred. It is the number of *reported* injury crashes in this TIMS vintage whose party codes match the core definition.
- Trend statements. The file is not a year.

## What would be needed next

Wait for later 2026 TIMS quarters, then rerun the same code (`python3 -m src.run --year 2026 --raw-dir data/raw/tims_2026 --no-all-mode`) without changing the three-crash floor. A five-year extract of **finalized** years only (2019–2023 in this vintage) is the right way to see whether 2023’s Berkeley stretches persist. The command is `python3 -m src.run --year 2019-2023 --raw-dir data/raw/tims_2019_2023 --no-all-mode --min-crashes 15 --n-years 5` once those CSVs are in place. Until CHP finishes 2026, the defensible sentence is: in the Q1-vintage TIMS file, 107 Alameda bicycle injury crashes are on the map, 20 match a core right-hook coding rule, and none of the 800 m windows yet reach three crashes.
