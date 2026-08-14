# Project Flow & Architecture Map

Living document — reflects the current structure. For WHY things are built
this way, see `decisions.md`. This file is WHAT exists, WHERE it is, and
HOW it connects.

## High-level picture

Two independent-but-related tracks:
- **Modules** (`PAI-S01`, `PAI-S02`, `PAI-S03`) — user-facing dashboards.
- **Clusters** (`Cluster 1`, `Cluster 2`, `Cluster 4`, ... up to 14 planned)
  — a data-validation layer, largely independent of modules. Only Cluster 1
  is currently wired into a module (PAI-S01). All others are standalone,
  offline, report-only pipelines.

```
data/raw/boiler9_cleaned_2024.csv (91,767 rows, 2024, 5-min interval)
        |
        v
shared/raw_loader.py (load_raw(), cached)
        |
        +--> shared/feature_extraction.py (build_feature_view(raw_df, config))
        |         |
        |         +--> config/hindalco_boiler9_pai_s01_v2.yaml --> Module 1's feature view
        |         +--> config/hindalco_boiler9_pai_s02_v1.yaml --> Module 3's feature view
        |         +--> config/hindalco_boiler9_pai_s03_v1.yaml --> Module 2's feature view
        |
        +--> clusters/cluster_features.py / cluster2_features.py / etc.
                  (each cluster's own feature view off the same raw_df)
```

## Data pipeline layer (`backend/shared/`, `backend/engine/`)

| File | Role |
|---|---|
| `shared/raw_loader.py` | Loads the full raw historian CSV once, cached. |
| `shared/feature_extraction.py` | `build_feature_view(raw_df, config)` — config-driven extraction/derivation, reused by every module and cluster. |
| `shared/chronological_split.py` | Monthly-stratified 20/80 train/test split, reused everywhere a baseline is trained. |
| `shared/data_quality.py` | Stale/spike/known-bad-timestamp detection, reused for both live alerting and training exclusion. |
| `engine/mode_classifier.py` | STEADY/STARTUP/LOW_LOAD/SHUTDOWN classification, reused by every baseline. |
| `engine/baseline.py` | Module 1's load-binned baseline (mean/std per load bin, STEADY-only training). |
| `engine/scoring.py` | Module 1's BOI/sub-score/zone computation, %-deviation and z-score paths. |
| `engine/state_builder.py` | The central tick loop — replays test-window rows in order, builds and serves `/api/state` (Modules 1 & 3) and `/api/efficiency` (Module 2). |

## Module 1 — PAI-S01 (Boiler Operating KPI Dashboard)

- **Config**: `config/hindalco_boiler9_pai_s01_v2.yaml`
- **Backend**: `engine/baseline.py`, `engine/scoring.py`, served via
  `state_builder.py`'s `/api/state`.
- **Frontend**: `frontend/src/pages/BoilerDashboard.jsx`, route
  `/modules/pai-s01`.
- **Cluster dependency**: Cluster 1 (Load-Flow Mass Balance), rendered as
  the Cross-Validation panel (`CrossValidationPanel.jsx`), a separate
  signal from BOI.
- **Status**: Phase A complete (live on real data). Known gaps: sub-score
  doesn't hold flat 100% in-band, no plausibility/min-max check, alert
  dedup/auto-clear timings don't match original spec, Layer 6
  (reports/export) not started.

## Module 2 — PAI-S03 (Combustion Excess Air Monitor)

- **Config**: `config/hindalco_boiler9_pai_s03_v1.yaml`
- **Backend**: combustion block inside `state_builder.py`.
- **Frontend**: `frontend/src/pages/CombustionMonitor.jsx`, route
  `/modules/pai-s03`.
- **Cluster dependency**: none (see decisions.md #15).
- **Status**: Phase A complete — O2/AFR-actual/efficiency-%/quadrant/
  guidance real; CO and everything CO-gated (P1/P4 alerts, CO-referencing
  guidance, CSS's CO component) simulated pending the correct CO tag.

## Module 3 — PAI-S02 (Boiler Efficiency Monitoring)

- **Config**: `config/hindalco_boiler9_pai_s02_v1.yaml`
- **Backend**: `efficiency_engine/boiler_efficiency/` (Awes's untouched
  ASME PTC-4 library) + `efficiency_engine/adapter.py` (our config-driven
  bridge), served via `/api/efficiency`.
- **Frontend**: `frontend/src/pages/EfficiencyMonitor.jsx`, route
  `/modules/pai-s02`.
- **Cluster dependency**: none (see decisions.md #16).
- **Status**: Phases A, B, C, and D complete — `boiler_duty.*`
  (steam/feedwater) real, Efficiency Gauge zone real, dashboard layout
  matches the Dashboard_Method spec (Trend overlays, Alert Cards, Shift
  Summary, Data Quality badge). As of 2026-08-13 (decisions.md #43):
  `fuel.*`, `refuse.*_distribution_pct`/`*_unburned_carbon_pct`, and
  `ambient.*` are real static_config values from a plant engineering
  document — no longer the library's reference-coal placeholder. Still
  open: refuse ash *temperatures* (4 fields, still placeholder), most
  `gas.*` (air-heater tag naming, no candidate confirmed).
- **Real-static-data constants** (`efficiency_engine/adapter.py`):
  `FUEL_ULTIMATE_PROXIMATE`, `FUEL_HHV_KJ_KG`, `REFUSE_ASH_SPLIT`,
  `AMBIENT_CONDITIONS`, tracked against a fixed `PLANT_ENGINEERING_DOC_DATE`
  (not re-evaluated to "now" per restart, unlike `GCV_LAST_UPDATED` — these
  are periodic test-report values, not per-shift entries). `fuel.hhv_kj_kg`
  and Gate 1's `GCV_KCAL_PER_KG` are deliberately NOT reconciled (~1.64%
  apart, different source documents) so Gate 1 keeps two independent GCV
  sources either side of its cross-check.
- **14 Logical Filtering & Validation Rules** (plant engineering document,
  2026-08-13, decisions.md #44) — `efficiency_engine/adapter.py`'s
  `check_*()` functions + `run_validation_checks()` aggregator, backend
  only (no frontend panel yet — not asked for). Rules 1-2 are real
  blocking gates in `run_efficiency()` (before the library is called);
  rule 3 cross-references the existing GCV Check; rules 4-14 are advisory,
  returned in `result["validation_checks"]` (sorted list of 14, one entry
  per rule except rule 6 which yields 4 — one per A/B pair). Rule 6 needed
  6 new raw-tag columns (`SH3_PRESSURE_A/B`, `SH3_TEMP_A/B`, `O2_LHS/RHS`)
  added to `hindalco_boiler9_pai_s02_v1.yaml`'s `parameters:` block; Steam
  Flow A/B reused from Cluster 1's existing `self._cluster_view`, no
  duplicate extraction. Rule 14 reuses Module 1's own
  `self._param_runtime["steam_flow"].history`, no duplicate tracker.
  Rule 6's O2 LHS/RHS sub-check uses an absolute tolerance (0.85pp,
  `scoring.o2_ab_absolute_tolerance_pp`, `status:
  configurable_pending_confirmation`) instead of the document's relative
  5% — the other 3 pairs are unaffected (decisions.md #46).
- **`data_source` vocabulary**: `"documented"` (decisions.md #47) — a real
  plant-engineering-document value (fuel.*, refuse.*_distribution_pct/
  _unburned_carbon_pct, ambient.*, gcv_check.*), rendered as a green
  "DOCUMENTED" chip (`StatusChips.jsx`), distinct from `"static_config"`/
  grey "ASSUMED" (a generic Awes/library default, e.g. `assumptions.*`).
  Refuse ash temperatures (still placeholder) stay `"simulated"`.
- **Spec-alignment data-confidence gates** (Phase A of the PAI-S02 Spec
  Alignment brief, see decisions.md #29-32), all computed in
  `adapter.py`/wired in `state_builder.py`'s `_tick()`, never inside Awes's
  library:
  - **Gate 1 — direct-vs-indirect mass balance.** `eta_direct` computed in
    the adapter from the real, independent `FUEL FLOW` tag (not the
    library's own `fuel_heat_input_mw`, which is circular — see decisions.md
    #29). `|eta_direct - eta_indirect| > 2%` fires alert kind `"EFFICIENCY"`,
    id `efficiency::mass_balance`.
  - **Gate 2 — GCV staleness.** `fuel.hhv_kj_kg`'s `data_source` flips to
    `"stale"` past `GCV_MAX_AGE_HOURS = 8.0` since `GCV_LAST_UPDATED`.
  - **Gate 3 — Stack Temp / O2 invalid blocks DGL.** `run_efficiency()`
    returns `status: "invalid_inputs"` (not `"data_gap"`) when O2 or Stack
    Temp is stale, so Dry Gas Loss is never computed through frozen inputs.
    Stack Temp's own staleness is tracked by a dedicated
    `_s02_stack_temp_gate_runtime` (`ParamRuntimeState`) at the 12-row
    `TRAINING_STALE_STREAK_ROWS` threshold — independent of, and looser
    than, Module 1's own live `_param_runtime["stack_temp"]` tracker, which
    stays at the 3-row `STALE_STREAK_ROWS` rule (decisions.md #32).
  - **Gate 4 — partial-efficiency reporting — NOT implemented, open
    architectural decision (decisions.md #33).** Spec wants "report only
    available components" when an input is missing; current behavior
    always computes a full result using the library's own bundled
    reference-coal composition as a flagged placeholder instead. Left
    unresolved on purpose — fixing it means either restructuring the
    adapter around the library's all-fields-required dataclasses, or
    modifying the library itself (violates decision 16's black-box rule).
    Do not treat this as silently closed.
- **Efficiency Gauge zone** (Phase B, see decisions.md #34-35), computed in
  `classify_efficiency_zone()`/`classify_co_flag()` (`adapter.py`), wired in
  `state_builder.py`'s `_tick()`, rendered in `EfficiencyMonitor.jsx`'s
  gauge panel:
  - `eta_deviation_pct = eta_design_pct(87.71) - eta_actual` (raw
    `boiler_efficiency_hhv_pct`, not the Appendix D-4 corrected figure).
    GREEN ≤1.0pt / AMBER 1.0-2.5pt / RED >2.5pt, config source
    `hindalco_boiler9_pai_s02_v1.yaml` `scoring.*`.
  - `eta_guaranteed_pct(86.0)` stored alongside but not wired into any
    formula/alert — a separate contractual-floor concept (decisions.md #34).
  - CO>300ppm "Incomplete Combustion" flag: computed, shown as its own
    badge, `data_source: "simulated"`, deliberately does not affect the
    main gauge color (decisions.md #35).
  - Excess Dry Gas Loss / Excess Unburnt Carbon flags: `status: "pending"`
    in the API response — setpoints not given in the spec, not implemented.
- **Loss Waterfall reconciliation** (Phase C, see decisions.md #36) —
  investigation against Awes's library source, not the frontend:
  - CO Loss: absent from the entire library. `co_loss.data_source =
    "unavailable_no_formula"` (new status, distinct from stale/simulated),
    rendered as its own stub strip below the waterfall bars, never folded
    into any numeric total.
  - Fly Ash (L6) / Bottom Ash (L7): library keeps native
    `unburned_carbon_loss_pct` / `sensible_heat_loss_pct` labels (combined
    across 4 internal ash streams, by mechanism not by stream) — not
    relabeled, mapping is genuinely ambiguous (Punarbasu/Awes ask).
    `other_loss_pct` / `sensible_heat_loss_pct` get an inline tooltip
    noting they're extra detail beyond the spec's 8 named terms.
  - **Heat Credits panel** (new, `EfficiencyMonitor.jsx`): the 4 credit
    terms + total, already present in `/api/efficiency`'s response
    (`efficiency.values.*_credit_pct`) but previously unshown.
- **Efficiency Alert Cards** (Phase D, decisions.md #37) — reuses the two
  existing EFFICIENCY-kind alerts (mass_balance, gcv_check) from
  `self._alerts`; no new alert-firing logic. `state_builder.py` builds
  `alert_cards` (priority-sorted by deviation) each tick; rendered as a new
  panel in `EfficiencyMonitor.jsx`.
- **Daily/Shift Summary Table** (Phase D, decisions.md #38) —
  `self._shift_stats` incremental accumulator in `state_builder.py`, keyed
  by `_shift_key()` (fixed 8-hour blocks over the replayed row's own
  `source_timestamp`). Exposed as `shift_summary` (last 12 shifts) in
  `/api/efficiency`; rendered as a table, documented as a fixed-window
  simplification, not a real plant shift schedule. GCV column uses
  `FUEL_HHV_KCAL_KG` (`fuel.hhv_kj_kg`'s kcal/kg form — the GCV that
  actually drives every other column in the row), not `GCV_KCAL_PER_KG`
  (Gate 1's deliberately-independent constant) — fixed 2026-08-14, was an
  oversight predating decision 43's real-fuel wiring, not a deliberate
  choice (decisions.md #48).
- **Efficiency Trend Panel overlays** (Phase D) — Design/Amber/Red
  reference lines (same `zone.*` values the gauge uses, expressed as
  absolute efficiency) and a secondary Y-axis for unit load
  (`unit_load_pct`, reused from Module 1's own `load_pct`, added to the
  efficiency snapshot). Y-axis domain is computed explicitly (not "auto")
  so the reference lines are always visible even when live efficiency runs
  far from design.
- **Loss Waterfall design-target overlay** ("Highlight if Li > Li_design by
  more than 0.3%") — NOT implemented. Checked the bundled reference
  example (`mundra_result.json`) for per-component design-loss values:
  none exist. Genuine Awes/Punarbasu ask, not guessable (decisions.md #36).
- **Data Quality composite badge** (Phase D, decisions.md #39) — rolls up
  GCV freshness + O2 validity (`good`/`degraded`); fly-ash shown as its own
  static line, not folded into the composite color (no timestamp exists to
  compute an age from). Computed in `adapter.py`'s `run_efficiency()`
  (`result["data_quality"]`), shown next to the Data Source / Assumptions
  panel's title, alongside (not replacing) the per-field DataSourceChips.
- **Visual-consistency pass** (decisions.md #40-42) — presentation only, no
  data/logic changes except the Alert Card `clearing` flag:
  - Verbose prose (`assumption_notes`, loss-term caveats) collapsed behind
    a `Collapsible` toggle component (new, `EfficiencyMonitor.jsx`),
    collapsed by default — status chips stay always-visible.
  - Panel grid reflowed: Heat Credits/Boiler Duty & Firing/GCV Check and
    Air-Flue-Gas/Heat Balance/Appendix D-4 are now 4/4/4 trios (previously
    Heat Credits was orphaned alone at col-4, and the second group was
    3+3+6). Alert Cards uses `flex-wrap` with a per-card max-width instead
    of a fixed `grid-cols-3`, so a single active card doesn't render with
    2 empty grid cells beside it.
  - Efficiency Alert Cards' `clearing` field (`state_builder.py`) marks an
    alert that's `active` only because it's inside its 30s
    `AUTO_CLEAR_SECONDS` grace period, not because the current tick is
    genuinely over threshold — rendered as a "clearing…" label so this
    doesn't look like the gate disagrees with itself.

## Clusters (`backend/clusters/`)

| Cluster | Docs | Code | Status |
|---|---|---|---|
| 1 — Load-Flow Mass Balance | `docs/Cluster_1_...` | `cluster_config.yaml`, `cluster_baseline.py`, `cluster_features.py`, `cluster_validator.py`, `reports/cluster1_report.*` | Complete, wired into Module 1 |
| 2 — PA Fan Performance | `docs/Cluster_2_...` | `cluster2_config.yaml`, `cluster2_baseline.py`, `cluster2_features.py`, `cluster2_validator.py`, `reports/cluster2_report.*` | Complete, standalone |
| 4 — SA Fan Performance | `docs/Cluster_4_...` | `cluster4_config.yaml`, `cluster4_baseline.py`, `cluster4_features.py`, `cluster4_validator.py`, `reports/cluster4_report.*` | Complete, standalone |
| 3, 5-14 | docs present | none | Not started |

## Frontend shared components (`frontend/src/components/`)

| Component | Used by |
|---|---|
| `StatusChips.jsx` (`DataSourceChip`, `ZoneChip`) | All 3 modules (DataSourceChip); ZoneChip only Module 1 |
| `Header.jsx` / `Layout.jsx` | All 3 modules, via the `ModuleLayout` route wrapper |
| `AlertPanel.jsx` | Module 1 only (Modules 2/3 have their own bespoke banners/no alert UI — see decisions.md #20 for the GCV-alert fix direction) |
| `CrossValidationPanel.jsx` | Module 1 only (Cluster 1's output) |

## Known cross-module coupling (see decisions.md #19)

`state_builder.py`'s single `_tick()` loop indexes one shared `self._row_idx`
into the replayed dataset — all three modules' state is built from the same
tick, same `source_ts`. Scenario effects (O2 bias, CO boost, sensor-drop
invalidation) are resolved once before any module reads its inputs, so a
shared tag (e.g. `o2`, `feedwater_flow`) shows the same value across all
three modules' API responses in the same tick.

## Not yet built anywhere

- Reporting/export (PDF/CSV/Excel, daily/weekly/monthly reports) — planned
  for all 3 modules per their original specs, not started.
- Any module that would consume Clusters 2/4 (a future "FPI" Fan
  Performance module family) — doesn't exist yet.
- Clusters 3, 5-14.
