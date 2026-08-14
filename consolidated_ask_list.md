# Consolidated Ask List — Punarbasu / Awes / Plant-Site Team

Living document, companion to `decisions.md` and `flow.md`. Every open item
below blocks something specific (named per item) from moving out of
`synthetic_needed` / `needs_verification` / `assumed` / `simulated`. Compiled
2026-08-12 from every module's and cluster's own config files, adapter
docstrings, and reports (Module 1/PAI-S01, Module 2/PAI-S03, Module 3/PAI-S02,
Cluster 1, Cluster 2, Cluster 4) — the same underlying question asked from
multiple places is listed once, with every dependent noted.

**Update this file whenever a new open item is found or an existing one gets
resolved** — same standing practice as `decisions.md`/`flow.md`.

---

> ## ⚠️ SAFETY-CRITICAL — HIGHEST PRIORITY OPEN ITEM
>
> **`BOILER_TRIP_MFT_STATUS` (Module 1) has no real tag at all and is
> currently a synthetic placeholder.** This is a Master Fuel Trip status
> signal — a safety-critical trip indication, not an operating parameter.
> The synthetic value is prototype/demo use only and must never be used
> for a real safety decision. This is the single highest-priority item in
> this entire list, ahead of every other open question below, regardless
> of section. Duplicated here for visibility only — it also stays in its
> normal place as item 6 in the Tag Confirmation section; nothing else in
> the list is renumbered.
>
> **Who**: Punarbasu · **Kind**: Tag Confirmation · **Status**: OPEN

---

## How to read this

- **Status** — `OPEN` or `RESOLVED`.
- **Who** — `Punarbasu` (plant tag/data owner), `Awes` (efficiency-library
  author), `Plant/Site Team` (broader operations/maintenance — log checks,
  calibration records, practices Punarbasu may not personally hold), or
  `Punarbasu or Awes (unclear)` for the two questions the Cluster 2/4
  technical notes themselves left open without stating who owns the answer.
- **Kind** — `Tag Confirmation`, `Lab Report`, `Design Document`,
  `Engineering Judgment Call`, or `Operational/Process Confirmation` (a
  5th kind, added here — several items are neither a tag nor a document,
  but a question about plant practice or maintenance history).
- Each item names every module/cluster that depends on it, so resolving one
  item is visibly worth more than fixing one dashboard.

---

## Resolved

**R1. `eta_design_pct` (87.71%) and `eta_guaranteed_pct` (86.0%).**
Provided directly by the user, 2026-08-12. Wired into Module 3/PAI-S02's
Efficiency Gauge zone (`eta_design_pct`) and stored separately
(`eta_guaranteed_pct`, not used in the deviation formula). See
decisions.md #34.

**R2. `FURNACE_DRAFT` (Module 1).** Upgraded from `synthetic_needed` to
`available` — the 3-point average proxy (`FURNACE PR BELOW SCREEN-A/B/C`)
was confirmed usable. See `hindalco_boiler9_pai_s01_v2.yaml`.

**R3. PA Fan Head — interim modeling approach (Cluster 2).** Head dropped
from all 3 relationship formulas; config-driven re-enable path exists if
the underlying tag question (item 9 below) is ever confirmed. This is a
*workaround*, not an answer — the tag question itself is still open. See
decisions.md #22.

**R4. Fuel Ultimate/Proximate Analysis (Module 3/PAI-S02 `fuel.*`, also
unblocks Module 2/PAI-S03's `afr_design`).** Real values received from a
plant engineering document, 2026-08-13: carbon_pct=36.13,
hydrogen_pct=2.05, oxygen_pct=11.32, nitrogen_pct=0.89, sulfur_pct=0.5,
ash_pct=36.81, moisture_pct=12.31, hhv_kj_kg=14870, volatile_matter_pct=
26.4, fixed_carbon_pct=30.48. Wired into `hindalco_boiler9_pai_s02_v1.yaml`
fuel.* as `static_config`, source "plant engineering document, 2026-08-13".
Note: this document's HHV (14870 kJ/kg) differs ~1.64% from Module 1's
separate COAL_GCV constant (3610 kcal/kg / 15114.3 kJ/kg, different source)
— deliberately NOT reconciled, see decisions.md #43. Also revealed a real
finding worth the document owner's attention: Dulong HHV computed from
this composition (3149.3 kcal/kg) vs. the document's own Measured HHV
(3551.6 kcal/kg) gives g_factor=0.887, outside GCV Check's [0.95, 1.04]
band — worth double-checking for a transcription error, or may be a
genuine ultimate-analysis/HHV basis mismatch. See decisions.md #43.

**R5. Ambient weather data (Module 3/PAI-S02 `ambient.*`).** Real static
design-basis values received from the same 2026-08-13 plant engineering
document: dry_bulb_c=37.8, pressure_bar_a=0.9888, relative_humidity_pct=
46.61, fuel_temp_c=37.8. Wired in as `static_config` (still not a live
tag — not in the historian export). See decisions.md #43.

**R6. Refuse ash distribution % / unburned-carbon % per stream (Module
3/PAI-S02 `refuse.*`) — PARTIAL resolution of item 15 below.** Real values
received from the same 2026-08-13 document: bed/cyclone/APH/ESP
distribution = 10/40/0/50%, unburned-carbon = 6.4/0.3/0/2.31%. Wired in as
`static_config`. Ash TEMPERATURES per stream were NOT part of this
document and remain open — see item 15, not fully closed.

---

## Open — Tag Confirmation (Punarbasu)

**1. `DRUM_LEVEL` (Module 1).** Candidate tags `CV 104 A FB` / `CV 104B
FB` — do these represent drum level or feed-control-valve position? ("CV"
naming suggests control valve, not a level transmitter.)

**2. `FEGT` / `STACK_TEMPERATURE` share one raw tag (Module 1).** Both map
to `FG TEMP BEFORE STACK` — genuine duplication (spec asks for two
distinct points), or are they actually the same measurement point on this
plant's design? Also underlies Module 3/PAI-S02's Gate 3, which currently
gates on `STACK_TEMPERATURE` only as a documented proxy for the real DGL
Stack Temp input (decisions.md #31) — resolving this is a prerequisite for
that gate becoming fully spec-compliant.

**3. Air-heater-specific gas/air temperature tags (Module 3/PAI-S02
`gas.*`).** No tag named "air heater" exists anywhere in the historian.
Candidates, none confirmed:
   - Gas-side (`gas_temp_air_heater_inlet_c`/`outlet_c`): `FG TEMP ECO-1
     I/L`, `FG TEMP AT ECO-1 O/L`, `FG TEMP BEFORE ESP`, `FG TEMP AFTER
     ESP`.
   - Air-side (`air_temp_air_heater_inlet_c`): `AIR TEMP AT AIR BOX A/B`
     exist, but read POST-air-heater (secondary air delivered to the
     windbox) — the opposite point this field needs.
   Same naming-mismatch pattern as items 1-2 above.

**4. Second O2 measurement at the air-heater outlet (Module 3/PAI-S02
`gas.o2_air_heater_outlet_dry_pct`).** No second O2 sensor exists anywhere
downstream of the air heater. Blocks `air_heater_leakage_pct` and
everything downstream of it (dry/wet flue-gas rates, the Dry Gas Loss
term itself).

**5. `SPRAY_WATER_FLOW_SH` (Module 1, also referenced by Cluster 1).** No
usable tag — the only candidate (`CV-116/121 FB`) was rejected as an
unclear proxy. Does a real spray-water-flow tag exist under a different
name? Cluster 1's water-steam balance currently runs without a spray term
as a result (decisions.md #21).

**6. `BOILER_TRIP_MFT_STATUS` (Module 1) — SAFETY-CRITICAL.** No tag at
all; currently a synthetic placeholder, HIGH priority, prototype/demo use
only. Never usable for real safety decisions until a real MFT/trip-status
tag is confirmed.

**7. `APH_DIFFERENTIAL_PRESSURE` (Module 1).** No tag; currently
`synthetic_needed`.

**8. CO analyzer tag (Module 2/PAI-S03; also blocks Module 3/PAI-S02's
Incomplete Combustion flag and CO Loss).** The only "CO"-named raw tag
(`CO O/L TO ECO-1`) is almost certainly a mislabeled flue-gas PRESSURE
point — values are negative (CO ppm cannot be negative) and it correlates
0.997 with a known pressure tag. Does a real CO analyzer tag exist under a
different name, or does none exist on this unit at all? Blocks:
combustion CO/CSS/quadrant (Module 2), the Phase B Incomplete Combustion
flag and CO Loss's own value (Module 3) — all currently simulated
(decisions.md #17).

**9. PA Fan Head (Cluster 2).** Confirm no real per-fan Head tag exists
anywhere else in the historian (checked exhaustively, found none), and/or
confirm whether `PA PR AT AIR BOX A/B` is a valid Head substitute for Fan
A/B respectively. Resolving this re-enables the doc's full 3-input
formula (item R3 above is the interim workaround).

**10. `PA PR AT AIR BOX C` (Cluster 2).** No confirmed correspondence to
either PA fan at all — what is this third zone/point?

**11. SA control-position/IGV-equivalent tag (Cluster 4).** Confirmed
absent by keyword search across all 103 raw columns. Is it genuinely
absent from this plant's instrumentation, or logged under a name this
search didn't anticipate? If genuinely absent, the `fan_igv` relationship
stays permanently unscoreable, not just blocked pending a lab report.

**12. SA Fan Head correlation (Cluster 4).** `SA PR TO APH(A)` and `(B)`
correlate at 0.99996 with each other — expected (both taps draw from a
shared header/plenum), or does it suggest one of the two taps isn't
measuring what its name implies?

**13. `cyclone_ash_temperature_c` (Module 3/PAI-S02 `refuse.*`).** Real
candidate tags DO exist (`CYCLONE -A ASH O/L TEMP`, `CYCLONE B ASH O/L
TEMP`) — unlike the other 3 ash-temperature fields, which have no
candidate at all. Using one real value alongside three synthetic ones
would be an inconsistent mix worth a deliberate decision, not a silent
default — needs plant/Punarbasu confirmation of intent before wiring it in
on its own.

---

## Open — Lab Report (Punarbasu)

**14. Fuel Ultimate/Proximate Analysis — RESOLVED, see R4 above.**

Module 2/PAI-S03's `afr_design` still needs to actually be rewired to
consume Carbon%/Hydrogen% from this same data (currently still a
simulated placeholder formula) — R4 only resolved the data itself and
Module 3/PAI-S02's own consumption of it; the Module 2 rewiring is a
follow-up implementation task, not a new plant ask.

**15. Refuse ash TEMPERATURES per stream (Module 3/PAI-S02 `refuse.*`,
bed/cyclone/aph/esp_ash_temperature_c) — still open.** Distribution % and
unburned-carbon % per stream are resolved (see R6 above); temperatures
were not part of that document. `cyclone_ash_temperature_c` has candidate
real tags (item 13 above); the other three have no candidate at all.

---

## Open — Design Document (Punarbasu)

**16. Ambient weather data — RESOLVED, see R5 above.**

**17. Excess Dry Gas Loss / Excess Unburnt Carbon setpoints (Module
3/PAI-S02 Phase B, `scoring.excess_dgl_setpoint` /
`excess_fly_ash_setpoint`).** Named in the PAI-S02 spec's Scoring_Model
("DGL > plant-specific-setpoint-A", "C_FA > plant-specific-setpoint-B")
but no numeric value given anywhere in the spec (decisions.md #34).

**18. Per-component design-loss targets (Module 3/PAI-S02 Phase D Loss
Waterfall overlay).** Spec wants "Highlight if Li > Li_design by more
than 0.3% → RED marker." Checked — not assumed missing — the bundled
Appendix D-4 reference example (`mundra_result.json`) for any such value:
none exist anywhere in it. Needed from the plant's design basis or from
Awes if the library has them elsewhere (decisions.md #36).

**32. Which GCV figure is authoritative — new, surfaced by R4 (2026-08-13).**
Two different GCV values are now in the system from two different, unreconciled
documents: `fuel.hhv_kj_kg` = 14870 kJ/kg (3551.6 kcal/kg, this 2026-08-13
document) vs. Module 1's `COAL_GCV` / `GCV_KCAL_PER_KG` = 3610 kcal/kg
(15114.3 kJ/kg, source/date unknown), ~1.64% apart. Currently kept
deliberately independent (Gate 1's cross-check needs two separate GCV
sources), but worth the plant confirming which is more current/authoritative
for future single-source use elsewhere. See decisions.md #43.

**33. GCV Check now fails (g_factor=0.887) with the 2026-08-13 document's
real values — worth the document owner double-checking.** Dulong HHV
computed from the document's own C/H/O/S composition (3149.3 kcal/kg) vs.
the same document's stated Measured HHV (3551.6 kcal/kg) falls outside the
GCV Check's [0.95, 1.04] band. Since both figures are static, this is now
a permanent, deterministic WARN, not intermittent noise. Possible causes:
a transcription error in one field of the document, or a genuine
ultimate-analysis/HHV basis mismatch (e.g. different moisture bases) in
the underlying lab work. Not adjusted or resolved unilaterally here — see
decisions.md #43.

**34. Ambient data currency (Validation Rule #10) — Design Document.** Were
the 2026-08-13 document's ambient readings (dry bulb, RH, barometric
pressure) logged AT THE SAME TIMESTAMP as an actual boiler test window
(site met-station or handheld reading), or are they a daily/period
average? Cannot be verified programmatically — there's no distinct
"test-window timestamp" field separate from the document's own date to
compare against. If not time-aligned with a real test window, the rule's
own stated action is to reject these readings.

**35. Does this CFBC unit have active limestone/sorbent injection?
(Validation Rule #12) — Tag/Process Confirmation.**
`assumptions.spent_sorbent_lbm_per_100_lbm_fuel=0` is currently wired
(library default) — valid ONLY if no sorbent dosing is in service on this
unit. If dosing IS active, this must be a real non-zero value from
DM/limestone feeder logs, not 0. Not yet confirmed either way.

**36. O2 LHS/RHS calibration offset — confirmed real and persistent, full
year swept (Validation Rule #6) — Plant/Site Team.** Full test-window
sweep (73,069 valid rows, 2026-08-13): exceeds the 5% relative tolerance
on **56.94%** of ticks — this is a genuine year-round pattern, not a
one-off (superseding the earlier single-tick framing). But investigated,
not just counted: RHS reads ~0.40 percentage points higher than LHS on
average, all year (LHS > RHS only 17% of ticks) — a real, directional,
persistent offset, structurally the same kind of finding as the PA/SA Fan
Current A/B offsets already found in Clusters 2/4 (decisions.md #13). Most
of the extreme relative-percentage tail is a percentage-of-small-number
artifact (median ABSOLUTE gap is only 0.23pp; relative % balloons when
average O2 is 1-2%) — the 5% relative-tolerance rule itself may be too
tight for how O2 normally reads at this plant's typical 3-5% excess-air
range, separate from whether the sensors need recalibrating. September
2024 stands out further (97.6% exceedance, ~0.93pp average offset vs.
~0.40pp typical elsewhere) — checked for stuck/frozen values first (none
found), so this looks like a real, distinct calibration-drift period, not
a data artifact. Two real questions for the plant: (a) does O2 LHS/RHS
need recalibration given the persistent ~0.4pp offset, and (b) what
happened in September 2024 specifically (worth checking against
maintenance logs, same as Cluster 1's date-specific event asks, items
#30-31).

**Update, 2026-08-14 — tolerance switched, re-swept.** Rule 6's O2 LHS/RHS
sub-check now uses an absolute tolerance (0.85pp, the p90 of the observed
absolute gap — a data-derived candidate, `status:
configurable_pending_confirmation` in `hindalco_boiler9_pai_s02_v1.yaml`
`scoring.o2_ab_absolute_tolerance_pp`, not confirmed by the plant) instead
of the document's relative 5%. Re-swept the same full test window through
the actual production `check_ab_deviation()` function: exceedance drops
from 56.94% to **9.91%** (7,241/73,069). This does not resolve the
underlying finding — the persistent ~0.40pp offset and the September 2024
anomaly are unchanged facts about the sensors, just no longer inflated by
a tolerance formula that didn't suit O2's magnitude. See decisions.md #46.

**37. Main Steam Pressure ceiling — rare overall, but January 2024 is a
real outlier (Validation Rule #13) — Design Document.** Full test-window
sweep (73,427 rows, 2026-08-13): exceeds 92 kg/cm2(a) on only **2.18%** of
ticks overall — confirms the single-tick spot-check's implication that
this is rare, not routine. But NOT evenly spread: **January 2024 alone is
24.5%** (3,225 rows); every other month is under 6%, most under 1%,
December is exactly 0% (never reaching 92 all month). Reads as a real,
period-specific event in January 2024, not a chronic condition — worth
checking against maintenance/operations logs for that month, same pattern
as Cluster 1's own date-specific findings.
Still open: is 92 kg/cm2(a) the same concept as `DESIGN_STEAM_PARAMETERS`'
90.2 kg/cm2 (nominal/rated design), or a genuine operating ceiling above
it? Nothing in the repo clarifies this. Indirect evidence leans toward
"92 is the real ceiling, 90.2 a nominal/target point below it": mean
operating pressure is 88.77 (below both), but 17.32% of ticks already
exceed 90.2 in otherwise-normal operation — if 90.2 were the actual hard
limit, the plant would be routinely running "over design" 1 row in 6,
which reads as less physically plausible than 90.2 being a target/nominal
value with 92 as the real mechanical ceiling above it. Suggestive, not
conclusive — still needs the plant/document owner to confirm.

**38. O2 LHS/RHS persistent offset — worth a calibration check, not
confirmed as expected or as a fault (Plant/Site Team).** The ~0.40pp
RHS-higher-than-LHS bias is visible 83% of the time, all year — a
one-directional, persistent pattern, not noise (noise would center near
zero and flip sign roughly evenly). That shape is normally what prompts a
calibration check in real O2-monitoring practice, especially since
PAI-S03's excess-air control reads off these same two probes. But this
is not confirmed as a fault either — a benign explanation (e.g.
genuinely different physical sample-point locations for the LHS/RHS taps,
same kind of open question already raised for SA Fan Head's two pressure
taps in Cluster 4, item #12) hasn't been ruled out. Flagged as worth
checking, not asserted either way.

---

## Open — Engineering Judgment Call (Awes)

**19. CO Loss formula.** Should the `boiler_efficiency` library be
extended to compute CO Loss — a named spec component (L5)? Confirmed
absent from the entire library (grepped all 13 source files, zero
CO-related loss logic anywhere), not just the dashboard. Not urgent — CO
data itself is also currently blocked (item 8 above). See decisions.md
#36.

**20. Fly Ash (L6) / Bottom Ash (L7) mapping.** Does the spec's split mean
unburned-carbon-loss-per-stream, sensible-heat-loss-per-stream, or
something else entirely? The library internally tracks 4 ash streams
(bed/cyclone/APH/ESP) but aggregates them into 2 totals by loss
*mechanism* (carbon vs. heat), not by *stream* — genuinely ambiguous which
the spec's 2-term framing means. See decisions.md #36.

**21. Gate 4 / partial-efficiency reporting — open architectural
decision.** Spec wants "report only available components" when an input
is missing; the library's dataclasses require every field populated to
run at all and cannot natively produce a partial result. Fixing it means
either (a) restructuring the adapter to selectively skip loss terms whose
inputs are missing (nontrivial — PTC-4 loss terms aren't independent), or
(b) modifying the library itself (violates the standing black-box ground
rule). Needs Awes's and/or the user's explicit direction on which path, if
either. See decisions.md #33.

**22. `flue_gas_specific_heat_cpg_btu_lbm_f` (Module 3/PAI-S02 `gas.*`).**
Currently the library's own bundled example value (0.264). Does Awes have
a plant-specific recommendation instead? Low priority — not currently
blocking anything.

**23. `surface_radiation_loss_pct` / `other_loss_pct` (Module 3/PAI-S02
`assumptions.*`).** Currently library defaults (0.18%, 0.25%). Plant-
specific override available? Low priority — not currently blocking
anything.

**24. A/B Current structural offset (Clusters 2 and 4 — related but
distinct numbers, not the same fact).** Why do the two fans in each pair
draw meaningfully different current at matched RPM/comparable duty?
   - PA (Cluster 2): Fan A vs. Fan B, ~47% offset.
   - SA (Cluster 4): Fan A vs. Fan B, ~13.7% offset.
   Different motor/fan capacity rating between the two fans, or different
   current-transformer scaling? Affects whether the learned baseline
   offset is "normal for two different fans" or masks a genuine, permanent
   imbalance that's simply never been absent from the data to compare
   against.

**25. Fan A Speed resolution (Cluster 4).** Fan A's Speed tag repeats its
previous value 61.6% of the time vs. Fan B's 3.2%. Is Fan A logged at a
coarser resolution, or on a longer hold/deadband, by design?

---

## Open — Punarbasu or Awes (unclear — carried forward unmodified from the original technical notes)

**26. "If due to fuel change, if the air supply is more than usual needed
for the same load, how will the alert be reliable for high RPM?"**
Verbatim from the Cluster 2 and Cluster 4 technical notes' own open
questions (same wording pattern in both) — not answered by either
report, carried forward as-is.

**27. "Should Fuel GCV also be a reference variable?"** Verbatim from the
Cluster 2 and Cluster 4 technical notes' own open questions (Boiler
Demand and Required Fan Duty section) — same question in both docs, not
asked twice here.

---

## Open — Operational/Process Confirmation (Plant/Site Team)

**28. GCV update mechanism (Module 3/PAI-S02 Phase A Gate 2).** What is
the real per-shift lab-entry workflow? Needed so `GCV_LAST_UPDATED` can be
wired to something real instead of a fixed process-start timestamp
(decisions.md #30).

**29. Feedwater/Steam Flow calibration + blowdown practice (Cluster 1).**
Feedwater consistently reads higher than steam flow — one-directional,
shrinking with load (6.5% at 80-90% MCR down to 3.3% at 110-120% MCR).
Plausible explanations (continuous blowdown, calibration drift) can't be
confirmed from historian data alone. Recommend confirming actual blowdown
practice and the last calibration date for the feedwater and steam flow
elements before this offset is accepted as "normal."

**30. 2024-08-30 historian outage, ~16:20-17:50 (Cluster 1).** Steam
Flow-A, Steam Flow-B, and Feedwater Flow all freeze at identical values
simultaneously for roughly an hour, then again for ~30 minutes later the
same day — looks like a historian/logging outage rather than three
independent sensor faults. Worth confirming against plant maintenance
logs for that date.

**31. 2024-02-08 to 2024-02-26 Tertiary Air drop event, ~18 days
(Cluster 1).** Two distinct stages (severe ~82% drop for 4 days, partial
recovery still ~43% below normal for ~14 days); both TA channels move
together throughout, ruling out a single frozen transmitter. Flagged for
the plant engineer to check maintenance/operations logs for this window
(this is also the event that caused the single-cutoff train/test split to
incorrectly learn it as normal — see `decisions.md` #5).

---

## Maintenance note

When resolving an item: move it to **Resolved** with a one-line summary
and the date, update the corresponding config file's `status:` field, and
add/update the relevant `decisions.md` entry (per that file's own standing
practice). When a new item surfaces during future work: add it here in the
matching Who/Kind section, immediately — not deferred to a later cleanup
pass.
