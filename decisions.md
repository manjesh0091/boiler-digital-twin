# Project Decisions Log

Living document. Every decision here was made after checking real data or
real reasoning — never guessed. Update this file whenever a new decision is
made, in the same style: what, why, when.

## Architecture

**1. Config-driven, not hardcoded.** Every tag name lives in a YAML config,
never directly in Python code. Onboarding a new plant means writing a new
config file, not rewriting code.

**2. Config tiers.** Every parameter/tag is tiered: `available` (real,
direct) / `derived` (computed from available tags) / `needs_verification`
(real tag exists, physical meaning uncertain) / `synthetic_needed` (no real
tag, placeholder used, clearly flagged) / `optional_not_applicable`
(doesn't apply to this plant's design) / `static_config` (manually-entered
constant, not a live tag).

**3. `data_source` flag on every served value.** `real` / `derived` /
`needs_verification` / `synthetic`/`simulated` / `stale` / `partial` /
`derived_estimate`. A value with no visible warning label looks as
trustworthy as a verified one — this makes uncertainty visible instead of
hiding it. Extended during Module 2 (PAI-S02) with `assumed` for
engineering-judgment constants.

**4. Shared engine components reused across modules/clusters, not
duplicated.** `engine/mode_classifier.py`, `shared/data_quality.py`,
`shared/chronological_split.py`, `shared/raw_loader.py` /
`build_feature_view()` are single implementations reused everywhere the
same check is needed (STEADY-state filtering, stale/spike detection,
train/test split, raw data loading).

## Data philosophy

**5. 20%/80% monthly-stratified chronological split.** First 20% of each
calendar month trains baselines; remaining 80% is scored as unseen/"live"
data. Prevents training and testing on the same data (which always looks
falsely accurate). Monthly-stratified (not a single early-year block)
because a single-block split was found to miss seasonal drift — e.g.
Cluster 1 found Total Combustion Air ~15 TPH higher July-December than
January-May; a Jan-Mar-only training block wrongly flagged the back half of
the year as full of outliers.

**6. STEADY-state-only training**, via `mode_classifier.py`, reused by
every baseline (Module 1, Cluster 1, Cluster 2, Cluster 4). Never trains on
STARTUP/SHUTDOWN/LOW_LOAD rows.

**7. Stale/frozen-value detection**, via `shared/data_quality.py`. Two
thresholds: live-alerting (`STALE_STREAK_ROWS = 3`) vs. training-exclusion
(`TRAINING_STALE_STREAK_ROWS = 12`, raised because whole-degree-quantized
tags like STACK_TEMPERATURE/FEGT otherwise get wrongly excluded from
training by ordinary slow drift).

**8. Custom load bins `[0,80,90,100,110,120]`** (Module 1, Cluster 1),
not the original spec's Low(<40%)/Part(40-70%)/High(>70%) bands — real 2024
data shows the plant runs at 90-111% MCR over 97% of the year; the spec's
bands would leave "Low load" almost empty.

**9. Mode classifier requires absolute-state gates, not just slope.**
SHUTDOWN requires both negative pressure slope AND `pressure <= 60.0
kg/cm2`; STARTUP requires ramp signature AND `load <= 50%`. Slope-only
rules were found to false-positive on ordinary operating noise. This
dataset shows ~0 SHUTDOWN/STARTUP events all year — confirmed correct (this
plant never actually shuts down or cold-starts in 2024), not a bug.

## Scoring methodology

**10. Z-score zoning (not %-deviation) for small-magnitude parameters**:
`drum_level`, `furnace_draft`, `o2` (Module 1), later found necessary again
for `o2` in Module 2's target band. %-deviation badly overreacts when the
expected value itself is small (e.g. Furnace Draft's expected value is
often only -6 to -8 mmWC) — a tiny real swing looks like a huge percentage.

**11. Cross-Validation (Cluster 1) is a separate panel/signal, never folded
into BOI or any parameter's own sub_score.** BOI/Parameter Grid asks "is
this ONE reading close to what we'd expect at this load?" Cross-Validation
asks "do MULTIPLE related readings agree with each other and the physics
between them?" — different questions; conflating them would double-count or
double-hide the same issue.

**12. "Ambiguous" instead of guessing.** When two related readings disagree
and there's no clear way to tell which is at fault (Cluster 1's Steam
Flow-A/B tiebreak, Water-Steam Balance tiebreak), the system marks the
situation ambiguous rather than picking a side. Confidently wrong is worse
than honestly uncertain.

**13. A/B imbalance needs a LEARNED baseline, not a fixed zero-point.**
Found in Cluster 2 (PA Fan Current: stable ~-47% offset, not noise around
zero) and independently reconfirmed in Cluster 4 (SA Fan Current: ~+13.7%
offset, different magnitude and sign). Applying the doc's literal
zero-centered formula would false-alarm on nearly every healthy row in both
cases. Fixed by learning each pair's own stable offset as its baseline.

**14. A/B imbalance is only evaluated when duties are comparable** (a
guard, not a blanket calculation) — per each cluster doc's own instruction,
implemented identically in Cluster 2 and Cluster 4.

## Module-specific decisions

**15. Module 2 (PAI-S03, Combustion) has no cluster dependency.** Checked
all 14 cluster docs — several (5,6,8,9) reference O2 as an input but none
validate O2 itself; Cluster 9's own doc says O2 "should be brought in from
the combustion cluster," which doesn't exist among the 14. Module 2's own
O2/CO/AFR stoichiometric methodology (from its own original spec) fills
that role; other clusters will eventually consume ITS output, not the
reverse.

**16. Module 3 (PAI-S02, Efficiency) also has no cluster dependency.**
Built entirely from Awes's standalone ASME PTC-4 efficiency-calculation
library plus our own adapter layer. The library's calculation code
(`m01_boiler_duty.py` through `m09_corrections.py`, `orchestrator.py`,
`models.py`) is treated as an authoritative black box — never modified,
only wrapped.

**17. Combustion CO (`CO_IN_FLUE_GAS`) kept simulated, not wired to the
tag that shares its name.** The tag correlates 0.997 with a known PRESSURE
tag and has physically-impossible negative values — mislabeled, not real
CO. All CO-dependent items (quadrant, CSS's CO component, Alert P1/P4,
CO-referencing guidance) stay simulated/clearly flagged until the correct
tag is confirmed by the plant.

**18. Fuel Ultimate/Proximate Analysis (C/H/O/N/S/ash/moisture/VM/FC) is
entirely unwired, not just Carbon%/Hydrogen%** as first assumed. A repo-wide
grep found `state_builder.py`'s docstring falsely claimed O%/N%/S% were
available — they were never wired to any value. Only GCV (3610 kcal/kg) is
a genuine static constant. This blocks Module 2's AFR-design AND Module 3's
entire fuel-analysis input, from the same one lab report — asked once, not
twice.

**19. Scenario injections must produce identical values across all three
modules for any shared tag, at the same tick.** Found: PAI-S02 was reading
raw tag values independently, bypassing PAI-S01's scenario-driven
invalidation and PAI-S03's O2 scenario bias — meaning two dashboard tabs
open simultaneously during a scenario could show different values for "the
same" reading. Fixed by restructuring `_tick()` so scenario effects resolve
once, before any module reads its inputs.

**20. GCV Check WARN and other module-specific alert conditions must raise
real alerts (`_fire_or_update_alert()`), not just a UI badge** — a
badge-only signal is easy to miss if not looking directly at that panel.

## Cluster-specific decisions

**21. Cluster 1 (Load-Flow): Spray Water Flow omitted**, not proxied — the
only candidate tags (`CV-116/121 FB`) were already rejected as an unclear
proxy in Module 1's own config; the water-steam balance runs without a
spray term, documented as a real gap.

**22. Cluster 2 (PA Fan): Head dropped from all three relationship
formulas.** No real per-fan Head tag exists — the only PA-side pressure tag
(`PA PR TO HGG`) is a byte-identical duplicate of another tag, not two real
readings. Formulas reduced to `f(Fan Flow)` only. Config-driven re-enable
path if a real tag is found later: flip status to `available`, add `HEAD`
to the relationship's `stratify_by` list — no baseline/validator code
change needed.

**23. Cluster 2: baseline binned by Flow, not Load.** Checked empirically,
range-restriction ruled out directly (not assumed) — within a 1-percentage-
point-wide Load bin (n=10,735), Fan Flow's spread barely shrinks (101.1% of
unconditional std) — Load explains ~2% of Flow's variance. Flow is
genuinely driven by something else (damper/IGV position, fan-combination
choice), independent of demand, in this plant's real operation — a
materially different physical story than the doc's own framing.

**24. Cluster 4 (SA Fan): Head KEPT in the model**, unlike PA — `SA PR TO
APH(A)`/`(B)` confirmed genuinely distinct (not a duplicate). SA's
Load-Flow relationship is real but seasonally-mediated (per-month
correlation ranges from ~0 in December/March up to r²=36% in April,
verified via the same within-month range-restriction test) — the same
Flow-binning decision was reached as PA, but for a different, verified
reason (seasonal variation in coupling strength, not absence of any
relationship). Documented as a known limitation that a future
monthly-stratified scoring dimension could address.

**25. Cluster 4: no SA control-position/IGV-equivalent tag exists at
all** (confirmed absent via keyword search across all 103 raw columns, not
just differently-named). Kept as a documented placeholder relationship
(`status: synthetic_needed`) in config rather than removed entirely, so the
gap stays visible/auditable — consistent with how Module 1 handles
Spray Water Flow and Reheat parameters.

**29. Module 3 (PAI-S02) `eta_direct` cross-check uses the real, independent
`FUEL FLOW` historian tag, not the library's own `fuel_heat_input_mw`.**
Traced Awes's `m07_firing.py`: `fuel_kg_s` is derived from
`boiler_duty_mw*1000/(hhv_kj_kg*efficiency_pct/100)`, where `efficiency_pct`
IS `eta_indirect` — so the library's own fuel-heat-input figure is not an
independent measurement of input energy, it's `eta_indirect` restated
algebraically (verified numerically to float precision against
`boiler_duty_mw/(eta_indirect/100)`). Using it for a direct-vs-indirect
mass-balance check would be circular — always agree by construction. Fixed
entirely in the adapter (`compute_eta_direct_pct()`), using the real FUEL
FLOW tag Module 2 (PAI-S03) already uses for `afr_actual` — no library
changes.

**30. Module 3 GCV staleness gate: `> 8h` since last lab update marks
`fuel.hhv_kj_kg`'s `data_source` as `stale`,** matching the spec's own
requirement that a per-shift lab GCV entry expires. No live GCV-update
mechanism exists yet (open ask for Punarbasu/Awes: what the real per-shift
lab-entry workflow is) — `GCV_LAST_UPDATED` is currently set once at
process start, so this gate will not yet fire from a genuinely stale lab
entry in the running demo; the check itself is real and wired for when it
does.

**31. Module 3 Gate 3 (Stack Temp/O2 invalid) blocks Dry Gas Loss
entirely rather than computing through bad inputs** — `run_efficiency()`
returns `status: "invalid_inputs"` (distinct from `"data_gap"`) when either
tag's `data_source` is `"stale"`, matching the spec's requirement that DGL
not silently compute on frozen readings. O2's stale-check takes priority
over any scenario-driven simulation, matching decision 19's shared-resolution
rule.

**32. Module 3 Gate 3's Stack Temp staleness check uses the 12-row
`TRAINING_STALE_STREAK_ROWS` threshold, not the live 3-row
`STALE_STREAK_ROWS` rule** — scoped to this one gate only, via an
independent `ParamRuntimeState` tracker
(`_s02_stack_temp_gate_runtime`) reading the same raw `STACK_TEMPERATURE`
tag but counting its own streak separately from Module 1's
`_param_runtime["stack_temp"]`. Same reasoning as decision 7
(whole-degree quantization trips the 3-row rule on ordinary slow drift, not
genuine freezing). Measured, not assumed: at the 3-row threshold Gate 3
blocked 76.1% of rows (69,879/91,767) in `module1_features.csv`'s
STACK_TEMPERATURE column; at 12-row it blocks 41.7% (38,287/91,767).
Module 1's own live Parameter Grid alerting for `stack_temp` is unchanged
and still uses the 3-row rule — confirmed via `/api/state`, no Gate 3
change reaches it. The remaining 41.7% is a downstream symptom of the
already-tracked air-heater-tag gap (decision 31, Punarbasu/Awes ask list),
not a new problem: Gate 3 gates on `STACK_TEMPERATURE` only as a proxy for
the real DGL Stack Temp input, so this number will fall once the real tag
is confirmed and wired — it does not need independent chasing.

**33. Module 3 Gate 4 (partial-efficiency reporting) left as-is —
flagged as an open architectural decision, not resolved.** The spec's
methodology is "report only available components" when an input is
missing; the current implementation instead always computes a full result,
substituting Awes's library's own bundled ASME Appendix D-4 reference-coal
composition wherever the plant's real fuel analysis is missing
(`_placeholder_fuel_composition()`), with every substituted field's
`data_source` tagged `"assumed"`/`"synthetic_needed"` so the substitution
is visible rather than hidden. This is a deliberate difference, not an
oversight: the library's dataclasses (`FuelAnalysis`, `RefuseAnalysis`,
etc.) require every field populated to run at all — they cannot natively
produce a genuinely partial result. Making this spec-compliant would
require one of two paths, both currently rejected as out of scope: (a)
restructuring the adapter/orchestrator layer around the library to
selectively skip loss terms whose inputs are missing (nontrivial — ASME
PTC-4 loss terms are not independent, e.g. Dry Gas Loss and Unburned Carbon
Loss both depend on the same refuse/fuel split), or (b) modifying the
library's own dataclasses/orchestrator to accept partial input, which
violates the standing ground rule to treat Awes's `boiler_efficiency`
package as an authoritative, unmodified black box (decision 16). Left
unresolved deliberately rather than silently picking one path — needs an
explicit decision from the user/Awes before either is attempted.

**34. Module 3 Efficiency Gauge zone (Phase B) uses two distinct
plant-provided numbers, only one of which feeds the formula.**
`eta_design_pct = 87.71` (design-condition target) is used in
`eta_deviation = eta_design - eta_actual`, GREEN≤1.0pt / AMBER 1.0-2.5pt /
RED>2.5pt (spec-given bands). `eta_guaranteed_pct = 86.0` (contractual/OEM
guarantee-test floor) is stored separately (`config` `scoring.*`,
`adapter.py` constant) and deliberately NOT wired into the deviation
formula or any alert — a different concept, kept available for a possible
future lower-bound warning per the user's explicit instruction not to
discard it. `eta_actual` uses the raw indirect-method efficiency
(`efficiency.values.boiler_efficiency_hhv_pct`, the same figure already
headline-displayed), not the Appendix D-4 corrected figure — checked (not
assumed) whether corrected efficiency coincidentally equals eta_design: an
offline 2070-tick sweep shows corrected clustering at 86.8-87.1%, close to
87.71% but not equal, and above 86.0% guaranteed. Plausible in principle
(D-4 corrections exist to normalize a test result toward design/guarantee
conditions) but the corrected figure here still runs on the bundled
reference-coal placeholder, not real plant fuel analysis — so the
closeness isn't asserted as a real methodological match, just recorded as
checked. Excess Dry Gas Loss / Excess Unburnt Carbon flags (spec-named,
setpoints A/B not given numerically) stay `status: pending` in the API
response — not computed, not guessed, same discipline as every other
undefined threshold in this project.

**35. Module 3's CO>300ppm "Incomplete Combustion" flag is computed and
shown but deliberately does NOT drive the main gauge zone color.** The
threshold itself is spec-given, but the CO reading it compares against is
the combustion module's simulated `co_ppm` (no real tag confirmed — same
blocker as decision 17), so letting it flip the real-data-driven gauge
color would let a simulated value silently override a real one. Tagged
`data_source: "simulated"` and rendered as a separate badge instead. CO for
this tick is computed later in `_tick()` than PAI-S02's efficiency block
(no PAI-S01-equivalent hoisting point exists for it), so the flag is
patched into `self._last_efficiency_snapshot` in place once `self._co_ppm`
is finalized for the tick, rather than reusing the previous tick's value.

**36. Module 3 Loss Waterfall (Phase C reconciliation) keeps Awes's native
loss-term labels and structure — not force-relabeled to the spec's 8 named
terms.** Checked directly against library source (`m08_efficiency.py`,
`models.py`, `orchestrator.py`), not inferred from the frontend:
- CO Loss (spec's L5) is absent from the entire library, not just the
  dashboard — grepped all 13 source files, zero CO-related loss logic
  anywhere. Shown as a distinct, clearly-labeled stub line ("CO Loss — not
  computed (no formula exists in the calculation engine)"), tagged
  `data_source: "unavailable_no_formula"` — a new status, deliberately
  different from `"stale"`/`"simulated"` (those mean a real value is
  blocked; this means no formula exists to block). Never folded into
  `total_heat_loss_pct` as a fabricated 0 or any other number.
- Fly Ash (L6) / Bottom Ash (L7): the library tracks 4 ash streams (bed,
  cyclone, APH, ESP — CFBC-specific granularity beyond the spec's simpler
  2-stream framing) but sums them into 2 aggregates by loss *mechanism*
  (`unburned_carbon_loss_pct`, `sensible_heat_loss_pct`), not 2 aggregates
  by *stream*. Whether the spec's L6/L7 mean unburned-carbon-per-stream,
  sensible-heat-per-stream, or something else is genuinely ambiguous —
  not guessed, added to the Punarbasu/Awes ask list. Labels kept as
  Awes's own terms rather than mapped onto a possibly-wrong interpretation.
- `other_loss_pct` ("Other Loss") and `sensible_heat_loss_pct` ("Ash
  Sensible Heat Loss") are legitimate additional detail beyond the spec's
  8 named terms, kept as their own bars with an inline tooltip note
  ("Additional detail beyond the original spec's 8 named loss terms,
  computed by the calculation engine.") rather than hidden or merged.
- The 4 credit terms (`entering_dry_air_credit_pct`,
  `entering_air_moisture_credit_pct`, `fuel_sensible_heat_credit_pct`,
  `auxiliary_power_credit_pct`) were already in `/api/efficiency`'s
  response but shown nowhere in the dashboard — `efficiency = 100 -
  total_loss + total_credit`, so without them a reader couldn't see why
  the losses shown don't fully account for the efficiency number. Added a
  dedicated "Heat Credits" panel (Phase D scope) rather than folding them
  into the loss waterfall (a credit isn't a loss, conflating them would
  misrepresent the waterfall's own total).

**37. Module 3 Efficiency Alert Cards (Phase D) show only alerts the
system already fires — no new alert-firing logic added.** Reuses the two
EFFICIENCY-kind alerts from Phase A (`efficiency::mass_balance`,
`efficiency::gcv_check`) exactly as they already exist in `self._alerts`;
a card renders whenever that alert is currently `active`, not only on the
exact tick it fired. Deliberately did NOT add a third card for the
eta_deviation zone itself (Phase B) — the brief said "reuse the alert data
already being generated," and zone deviation doesn't call
`_fire_or_update_alert()`, so inventing a card for it would be new alert
semantics, not reuse.

**38. Module 3 Daily/Shift Summary Table (Phase D) is an incremental
per-tick accumulator keyed by the replayed row's own `source_timestamp`,
fixed 8-hour blocks — not a separate batch job.** Consistent with this
backend's existing tick-based architecture (everything else is
incremental, nothing here is batch-computed). The replay loops forever
(`self._row_idx` wraps), so a shift key naturally caps at however many
real calendar shifts exist in the 80% test window — revisiting one on a
later loop pass just updates its running average, doesn't grow unbounded.
Only accumulates on `status == "ok"` ticks, so every column in a shift's
row comes from the same set of ticks (no mixing an eta average computed
over fewer ticks than the O2/Stack Temp/CO averages). "FA Carbon" column
uses `unburned_carbon_loss_pct` (decision 36's combined figure, not
fly-ash-specific) and is labeled with an asterisk + footnote accordingly,
not silently implied to be fly-ash-only. Explicitly documented as a fixed
time window over the replay, not a real plant shift schedule, per the
brief's own framing.

**39. Module 3 Data Quality composite badge (Phase D) rolls up GCV
freshness + O2 validity only — fly-ash data is shown as its own static
line, not folded into the same color signal.** Every refuse/ash input is
the bundled reference-coal placeholder with no timestamp at all
(`static_config`, not a live tag), so there is no real "age" to compute —
inventing one would violate the same discipline as decision 12
("ambiguous instead of guessing"). Composite is `"good"` only when GCV is
fresh AND O2's `data_source` is `"real"` (not `"simulated"`, i.e. no
active demo scenario biasing it); Gate 3 (decision 32) already blocks
before this point whenever O2/Stack Temp go stale, so by the time this
badge computes, O2 is never `"stale"` here — only `"real"` or
`"simulated"`.

**40. Module 3's verbose always-on prose (assumption_notes, loss-term
caveats) is collapsed behind a click, not removed.** Measured (not
assumed) that PAI-S01/PAI-S03 have no equivalent always-visible
multi-sentence block anywhere — checked both files directly, only a
single dynamic 1-2 line guidance sentence exists on PAI-S03, nothing
comparable to PAI-S02's 7-entry, ~2,500-character `assumption_notes`
array. Status chips (SIMULATED/REAL/ASSUMED/NO FORMULA) stay always
visible next to each field — only the explanatory "why" text moved behind
a `Collapsible` toggle, collapsed by default. No information removed.

**41. Module 3's panel grid was reflowed to match PAI-S01/PAI-S03's
density, not left as a near-single-column stack.** Measured (not
assumed): before this pass, PAI-S02 took 3.89 screen-heights for 12
panels vs. PAI-S01's 2.66 for 7 and PAI-S03's 1.19 for 9 — the real gap
was two literally-orphaned rows (Heat Credits alone at col-span-4 with 8
columns of dead space; Efficiency Alert Cards at col-span-12 for a single
card in a 3-slot grid), not a fundamentally different design. Fixed by
grouping Heat Credits with Boiler Duty & Firing/GCV Check as a 4/4/4 trio,
regrouping Air/Flue-Gas Composition/Heat Balance/Appendix D-4 Corrections
as a second 4/4/4 trio (down from 3+3+6), and switching Alert Cards from
a fixed `grid-cols-3` to `flex-wrap` with a per-card max-width so N=1
doesn't render 2 empty cells. Result: 2.20 screen-heights for the same 12
panels — denser than PAI-S01 despite more content. Checked headline-number
prominence (PAI-S02's `text-6xl` is already larger than PAI-S01 BOI's and
PAI-S03 O2's `text-5xl` — no change needed) and primary/secondary panel
de-emphasis (neither PAI-S01 nor PAI-S03 actually visually differentiates
primary from detail panels — one uniform `.panel` style project-wide — so
there is no existing pattern to match; none invented here either).

**42. Module 3's Efficiency Alert Cards distinguish "active because
currently over threshold" from "active because still inside its
auto-clear grace period."** Verified live (not assumed) that the
underlying gate itself is correct — `abs(deviation_pct) > 2.0` genuinely
drives `mass_balance_discrepancy`, confirmed by polling `/api/efficiency`
across several ticks and observing the card correctly absent whenever the
live deviation was under 2%. The apparent inconsistency was a display gap,
not a logic bug: every alert in this project (GCV Check WARN, CLUSTER
alerts, this one) stays `active` for `AUTO_CLEAR_SECONDS` (30s) after its
condition clears, by design — but the card was showing a small
current-tick deviation number next to "ACTIVE" with nothing explaining
why, during that window. Fixed by exposing `clearing` (true when
`below_threshold_since` is set but not yet past the grace period) and
labeling the card "clearing…" instead of leaving it looking identical to
a genuine active breach.

**43. Module 3's fuel Ultimate/Proximate Analysis, ash-split, and ambient
conditions are now real static values from a plant engineering document
(2026-08-13), resolving ask-list items #14/#16 and partially resolving
#15.** `fuel.*` (9 fields + hhv_kj_kg), `refuse.*_distribution_pct`/
`*_unburned_carbon_pct` (8 fields), and `ambient.*` (4 fields) are now
`static_config`, sourced from `FUEL_ULTIMATE_PROXIMATE`/`REFUSE_ASH_SPLIT`/
`AMBIENT_CONDITIONS` (`adapter.py`), tracked against a fixed
`PLANT_ENGINEERING_DOC_DATE` constant (2026-08-13) rather than
re-evaluating to "now" at every process start like `GCV_LAST_UPDATED` —
these are periodic test-report values, not per-shift entries, so a fixed
date is the correct model, not an approximation of one. Refuse ash
*temperatures* (4 fields) were NOT part of this document and still use the
reference-coal placeholder — item #15 is only partially closed, and the
config/adapter comments say so explicitly rather than implying full
resolution.

`fuel.hhv_kj_kg` now uses this document's own value (14870 kJ/kg = 3551.6
kcal/kg), NOT `GCV_KJ_PER_KG` (Module 1's separate COAL_GCV constant, 3610
kcal/kg = 15114.3 kJ/kg, ~1.64% higher, different source document/date).
Deliberately NOT reconciled — `GCV_KCAL_PER_KG` still feeds Gate 1's
independent `eta_direct` Q_input, and collapsing both onto one document
would remove Gate 1's independence between its two sides. Reconciling
which GCV figure is authoritative is a new, separate ask (see
consolidated_ask_list.md).

Measured (2000-tick offline sweep, not assumed), two real, significant
findings from wiring this in:
- **GCV Check now fails, not passes.** Dulong HHV (computed from the real
  C/H/O/S composition) = 3149.3 kcal/kg vs. this document's Measured HHV =
  3551.6 kcal/kg → g_factor = 0.887, outside the [0.95, 1.04] band (spec-
  given, decision 34). Since fuel.* is now a static value, this is not
  noise — it is a deterministic, permanent WARN state at these exact
  numbers, not an intermittent one. Not silently adjusted or hidden; this
  is exactly the kind of discrepancy the GCV Check exists to catch, and it
  now surfaces a genuine question worth the plant/document owner
  double-checking (transcription error in one field, or a real
  ultimate-analysis/HHV basis mismatch) — flagged to the user directly,
  not resolved unilaterally.
- **Mass Balance (Gate 1) discrepancy rate is 99.8%** (1331/1334 ok
  ticks), up in visibility (not necessarily in kind) from before this
  change. `eta_indirect` is now tight (87.52-87.66%, since fuel/refuse/
  ambient are all static and don't vary tick-to-tick) while `eta_direct`
  is highly volatile (37-92%), driven by real Fuel Flow tag noise against
  a GCV constant that differs ~1.64% from fuel.hhv_kj_kg's new real value
  (see above) — this was already eta_direct's character before this
  change (composition never varied tick-to-tick under the placeholder
  either), just now paired with a real, higher eta_indirect baseline
  (~87.6% vs. ~85.3% before).

**44. Module 3's 14 Logical Filtering & Validation Rules (plant
engineering document, 2026-08-13) are implemented as: rules 1-2 as real
BLOCKING gates (their spec'd action is "do not proceed"), rule 3 as a
cross-reference to the already-existing GCV Check mechanism (not
recomputed), and rules 4-14 as advisory checks in
`result["validation_checks"]` — same Gate-style pattern as Phase A's Gates
1-3.** Implementation notes, rule by rule:
- **Rules 1 (mass closure, ±0.5%) and 2 (ash-split=100% exactly)** —
  blocking, evaluated in `run_efficiency()` before the library is even
  called, reusing the same `check_mass_closure()`/`check_ash_split_closure()`
  functions the advisory list also includes (one implementation, not
  duplicated between the blocking and advisory paths). Both pass with
  current real data (100.01%, 100.000%).
- **Rule 2's stated alternative action ("normalize proportionally")** —
  deliberately NOT implemented; only "flag data-entry error" is. Silently
  renormalizing real plant data would fabricate a number, against this
  project's standing discipline (decision 12).
- **Rule 3 (GCV cross-check band)** — no new code; this IS Phase A Gate 2 /
  the library's own GCV Check. Cross-referenced from `gcv_check.values`
  after the library runs.
- **Rule 4 (O2 rise across air heater)** — computed, but always returns
  `"not_checkable"`: the AH-outlet O2 side is still the library's
  placeholder (no real sensor, ask-list item #4), so the rise figure
  (currently +5.86pp in testing) isn't yet trustworthy. Computed value
  shown in the message for transparency, not hidden.
- **Rule 5 (monotonic flue-gas temperature)** — only 3 of the spec's 7
  chain points have a confirmed real tag (Economizer Inlet/Outlet, Stack;
  Furnace/SH/APH-outlet/ESP-outlet do not, ask-list item #3) — checks that
  3-point subset only, explicitly named as a subset in the check's own
  message, not silently treated as the full chain.
- **Rule 6 (A/B instrument deviation, 5% tolerance)** — needed raw A/B
  pairs Module 1 already averages away. Steam Flow A/B reused from
  Cluster 1's existing `self._cluster_view` (no duplicate extraction);
  SH-3 Pressure/Temp A/B and O2 LHS/RHS needed 6 new raw-tag entries added
  to `hindalco_boiler9_pai_s02_v1.yaml`'s `parameters:` block
  (`SH3_PRESSURE_A/B`, `SH3_TEMP_A/B`, `O2_LHS/RHS`) — same raw tags
  Module 1 already reads for `MAIN_STEAM_PRESSURE`/`MAIN_STEAM_TEMPERATURE`/
  `FLUE_GAS_O2_APH_INLET`, kept separate here purely for this check; the
  efficiency calc itself is unaffected, still uses Module 1's real
  averages. First real-data test found O2 LHS/RHS at 8.64% deviation
  (above the 5% tolerance) — ask-list item #36.
- **Rule 7 (steam/feedwater mass balance, 3-5% tolerance, using the
  lenient 5% bound since the doc gives a range not a number)** — no
  Blowdown/Spray Water Flow term (neither has a real tag), same
  already-documented gap as Cluster 1's own Water-Steam Balance check
  (decisions.md #21). First real-data test: +6.28% deviation (feedwater
  reads higher) — this independently reproduces Cluster 1's own earlier
  finding (ask-list item #29: feedwater consistently reads 3-6.5% higher
  than steam flow) from a completely different code path. Not a new ask —
  cross-confirms an existing one.
- **Rule 8 (bed-ash temperature sanity)** — always returns
  `"not_checkable"`: `bed_ash_temperature_c` is still the reference-coal
  placeholder (800C), which matches NEITHER the in-bed (850-950C) nor
  post-cooler (150-250C) range — ash temperatures were not part of the
  2026-08-13 document (ask-list item #15).
- **Rule 9 (UBC order-of-magnitude, Bed > ESP > Cyclone > APH)** — passes
  with real data (6.4 > 2.31 > 0.3 > 0), confirming the document's own
  claimed consistency rather than assuming it.
- **Rule 10 (ambient data currency)** — always returns `"not_checkable"`;
  fundamentally not programmatically verifiable with this system's data
  shape (no distinct test-window timestamp separate from the document's
  own date). A flag for manual confirmation, not a gate — ask-list item #34.
- **Rule 11 (fixed-constant lock)** — reads the ACTUAL
  `EfficiencyAssumptions` dataclass instance's field values, not the raw
  (deliberately empty) `assumptions_kwargs` dict `build_inputs()` passes to
  it (that dict only carries `data_source` tags, relying entirely on the
  library's own dataclass defaults for the values themselves — a real bug
  caught during testing, fixed by capturing the instantiated
  `EfficiencyAssumptions()` object and reading its fields instead of
  reaching into the empty kwargs dict). Passes: both constants match ASME
  PTC 4.1 exactly (8.937, 33700.0).
- **Rule 12 (spent sorbent verification)** — always returns
  `"not_checkable"` while the value is 0: we don't yet know whether this
  CFBC unit has active sorbent injection. Ask-list item #35.
- **Rule 13 (steam design-limit check, ≤92 kg/cm2(a), ≤540C)** — passes
  temperature, but a first real-data spot-check found pressure at 93.7
  kg/cm2(a), above the 92 limit. Worth confirming whether 92 is the
  correct operating ceiling (Module 1's own `DESIGN_STEAM_PARAMETERS`
  lists 90.2 kg/cm2 as nominal/rated design pressure, a different concept)
  — ask-list item #37.
- **Rule 14 (load stability, ±2% over 30-60 min)** — reuses Module 1's own
  `self._param_runtime["steam_flow"].history` directly (no duplicate
  tracker); uses the 12-row/60-min end of the stated 30-60 min range, same
  convention as `TRAINING_STALE_STREAK_ROWS`. Passes with real data (1.60%
  max deviation over the window).

**45. Full-test-window sweep (73,427 rows) of Rules 6 (O2 LHS/RHS) and 13
(Main Steam Pressure ceiling) — both findings are real, but neither is
what the single-tick spot-check alone suggested.**
- **O2 LHS/RHS (Rule 6): exceeds 5% on 56.94% of ticks** (41,608/73,069) —
  far more than "one data point." But the relative-percentage framing
  overstates it: median ABSOLUTE difference is only 0.23pp, mean 0.49pp —
  the two probes usually sit within a quarter-point of each other. Most of
  the extreme tail (dev% > 100%) comes from a percentage-of-small-number
  artifact — when average O2 is 1-2%, a small absolute gap produces a
  triple-digit relative percentage (mean 144%, median 200% in that bucket)
  by arithmetic alone, not a worse physical fault. On top of that,
  there IS a real, persistent, directional bias: RHS reads ~0.40pp higher
  than LHS on average all year (LHS > RHS only 17% of the time) — a
  genuine calibration offset, same character as the PA/SA Fan Current A/B
  offsets already found in Clusters 2/4 (decision 13), not noise. September
  2024 is a distinct outlier within this (97.6% exceedance vs. 30-60% other
  months, offset ~0.93pp vs. ~0.40pp typical) — checked for stuck/frozen
  values (none found, all readings unique that month), so this looks like a
  genuine period-specific calibration drift, not a data artifact. Ask-list
  item #36 updated with these numbers.
- **Main Steam Pressure (Rule 13): exceeds 92 kg/cm2(a) on only 2.18% of
  ticks** (1,598/73,427) — a rare excursion, not routine operation, matching
  the single-tick spot-check's implication. But 2.18% overall hides a sharp
  concentration: **January 2024 alone is 24.5%** (3,225 rows); every other
  month is under 6%, most under 1%, December is exactly 0% (max 91.78,
  never reaching 92 all month). This reads as a real, period-specific
  event in January 2024, not a chronic condition.
- **92 vs. 90.2 kg/cm2 reconciliation — evidence gathered, not resolved.**
  Checked whether anything in the repo clarifies the relationship: nothing
  does (`DESIGN_STEAM_PARAMETERS`'s own value has no elaboration beyond the
  bare number). Indirect evidence from the sweep leans toward "92 is a real
  operating ceiling with margin above a 90.2 nominal/target, not a
  duplicate of the same limit": mean operating pressure is 88.77 (below
  both), but 17.32% of ticks already exceed 90.2 in apparently normal
  operation — if 90.2 were the actual hard ceiling, that would mean the
  plant routinely runs "over design" one row in six, which is a less
  physically plausible reading than 90.2 being a nominal/target point with
  92 as the real mechanical/instrumentation ceiling above it. Suggestive,
  not conclusive — still requires the plant/document owner to confirm,
  ask-list item #37 updated with this reasoning rather than left as a bare
  open question.

**46. Module 3's Rule 6 uses an ABSOLUTE tolerance (0.85pp) for O2
LHS/RHS specifically, not the Logical Filtering & Validation Rules
document's relative 5% — the other 3 A/B pairs (Steam Flow, SH-3
Pressure, SH-3 Temp) are unaffected.** Decision 45's full sweep found the
document's uniform relative-5% formula flagged 56.94% of ticks for O2
LHS/RHS, mostly a percentage-of-small-number artifact (O2 typically reads
3-5%, so a small absolute gap reads as a large relative percentage;
median absolute gap was only 0.23pp) — same class of problem decision 10
already fixed for Drum Level/Furnace Draft with z-score/absolute-
deviation zoning instead of %-deviation, and consistent with how O2
analyzer accuracy is conventionally specified in industry (absolute %O2,
not %-of-reading). The switch is scoped to O2 LHS/RHS only — the other 3
pairs operate at levels (100+ TPH, 90+ kg/cm2, 500+ C) where relative
framing doesn't have this problem, and the document's own 5% figure is
kept for them.

The tolerance value (0.85pp) is the p90 of the observed absolute gap from
the same sweep — a data-derived CANDIDATE, not a number either source
document states. Tagged `status: configurable_pending_confirmation`
(`hindalco_boiler9_pai_s02_v1.yaml` `scoring.o2_ab_absolute_tolerance_pp`)
— a new status value, same spirit as `needs_verification` on the DGL/Fly-
Ash setpoints (decision 34): a real working default, not silently
treated as final.

Re-swept the full 73,427-row test window through the actual production
`check_ab_deviation()` function (not a parallel calculation) after the
switch: exceedance drops from 56.94% to **9.91%** (7,241/73,069 valid
rows) — expected, since the tolerance was set at the observed p90 by
construction. This does not resolve the underlying finding from decision
45 (the persistent ~0.40pp RHS-higher-than-LHS offset, the September 2024
anomaly) — those are unchanged facts about the sensors; only the
tolerance formula changed, not the data. The calibration question itself
is tracked separately, ask-list item #38, deliberately worded as "worth a
calibration check, not confirmed as expected or as a fault" — not
resolved either direction, since a benign explanation (different physical
sample-point locations) hasn't been ruled out from data alone.

**47. Module 3's `data_source` vocabulary gains a new value, `"documented"`,
distinct from `"static_config"`.** Before this, every plant-engineering-
document-sourced field (fuel.*, refuse.*_distribution_pct/
_unburned_carbon_pct, ambient.*, gcv_check.*, all wired in decision 43) and
every genuine Awes/library engineering default with no plant-specific
override (assumptions.*, enthalpy.reference_water_temperature_c,
gas.flue_gas_specific_heat_cpg_btu_lbm_f) both got tagged `"static_config"`
and rendered as an identical grey "ASSUMED" chip — a reader couldn't tell
"a confirmed plant number" apart from "a generic placeholder pending
confirmation" at a glance. `"documented"` now covers only the former;
`"static_config"`/"ASSUMED" is reserved for the latter. `DataSourceChip`
(`StatusChips.jsx`) renders `"documented"` as a green "DOCUMENTED" chip,
visually distinct from every other (grey) chip — the one existing status
whose color changed is `"documented"` itself; every chip that existed
before this decision renders identically to before, no regression risk.
Refuse ash *temperatures* (still placeholder, not part of the 2026-08-13
document) correctly stay `"simulated"`, unaffected by this change.

**48. The Daily/Shift Summary Table's GCV column was showing Module 1's
separate `COAL_GCV` constant (3610 kcal/kg) instead of the GCV that
actually drives every other column in that same row — confirmed as an
oversight, not the same deliberate independence Gate 1 uses, and fixed.**
Investigated rather than assumed either way: the Shift Summary Table
(Phase D) was built before decision 43's real-fuel-data wiring existed, so
`GCV_KCAL_PER_KG` was literally the only GCV constant available at the
time — it was never revisited once `fuel.hhv_kj_kg`'s real value landed.
This is a different situation from Gate 1's mass-balance cross-check
(decision 43), which deliberately keeps `GCV_KCAL_PER_KG` independent from
`fuel.hhv_kj_kg` so the two sides of that specific comparison don't
silently converge — the shift table has no such cross-check purpose, it's
a plain summary column, and showing an unrelated constant next to
`avg_eta_pct`/`avg_dgl_pct` (which ARE driven by `fuel.hhv_kj_kg`) was
simply inconsistent. Fixed: added `FUEL_HHV_KCAL_KG` (`fuel.hhv_kj_kg` in
kcal/kg form) to `adapter.py`, `state_builder.py`'s shift accumulator now
sums this instead of `GCV_KCAL_PER_KG` (now unused in that file, removed
from its import). Column now reads 3552 kcal/kg, matching the GCV Check
card's own "Measured HHV" figure, instead of an unrelated 3610. Frontend
footnote added (same pattern as the existing "FA Carbon" footnote)
explicitly naming which GCV source the column uses and why it differs
from Gate 1's Mass Balance card.

## Process decisions

**26. Clusters are built standalone first (config -> baseline -> validator
-> report), never wired into a live module/dashboard until explicitly
decided.** Wiring is a separate, later decision — most of the 14 clusters
will eventually feed modules that don't exist yet (e.g. an FPI Fan
Performance module), so cluster-building and module-wiring are independent
tracks.

**27. Every cluster's specific numeric findings are re-verified
independently for each new cluster, even when the code structure is
reused.** Cluster 4 reused Cluster 2's code pattern but re-checked every
empirical finding fresh against SA's own data — several came out
materially different (Head usable vs. blocked, offset +13.7% vs. -47%,
different stop-event dates). Code reuse is fine; finding reuse is not.

**28. Doc source-of-truth artifacts are checked for copy-paste errors
before trusting them.** Cluster 4's technical note was found to be a copy
of Cluster 2's doc with an incomplete find/replace (wrong title, leftover
"PA" references in three places) — the variable/tag table (the
authoritative part) was correctly updated; prose artifacts were not. Future
cluster docs should get the same scrutiny.
