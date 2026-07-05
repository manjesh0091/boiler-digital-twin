# Tkil Industries pvt ltd — Boiler Digital Twin

## Original Problem Statement
Build an MVP prototype for an industrial boiler monitoring platform (thermal/CFBC power plant) with **simulated sensor data**. Two independent, navigable screens + a landing/nav shell:

1. **PAI-S01 — Boiler Operating KPI Dashboard** — composite BOI (0–100) built from weighted sub-scores of 9+ operating parameters, plus parameter-level visibility, alarm log, daily summary.
2. **PAI-S03 — Combustion Excess Air Monitor** — real-time O₂/EA%, CO safety, CO-O₂ quadrant, O₂ trend, AFR strip, efficiency impact (₹/hr), operator guidance.

Simulation runs in FastAPI backend, streamed via 2 s polling to React frontend. Includes operator-triggered `Inject Scenario` control.

## Architecture

- **Backend** — FastAPI + in-memory asyncio simulator (no MongoDB usage; state is per-process).
  - `/api/state` — full snapshot (unit load, mode, params, BOI, combustion, alerts, DQ).
  - `/api/scenarios`, `/api/scenario` (POST) — scenario control.
  - `/api/alerts/{id}/ack`, `/api/alerts/ack-all` — alert acknowledgement.
  - `simulation.py` — BoilerSimulator ticks every 2 s: load oscillation → derived parameters → BOI scoring → CO-O₂ classification → alert dedup + auto-clear.
- **Frontend** — React Router + Recharts + custom SVG gauges.
  - `useTelemetry(2000)` polls `/api/state`.
  - Screens use Chivo (display), IBM Plex Sans (body), JetBrains Mono (numerics).
  - Industrial dark theme (`#0B0B0C` / `#141416`), status colors only (Green/Amber/Red).

## User Personas
- **Control-room operator** — needs dense, fast-updating parameter visibility, colored zoning, persistent alarm log with ack.
- **Combustion engineer** — needs O₂/CO quadrant guidance and efficiency impact for tuning.
- **Plant manager / stakeholder** — visits during a demo to see how the eventual platform will look with live plant data.

## Core Requirements (static)
- Two deep-linkable modules: `/pai-s01`, `/pai-s03`.
- Simulation must run continuously with load oscillation, occasional auto-injected deviation events, and manual scenario override.
- All values shown with engineering units; monospace font for numerics.
- ISA-101 industrial dark aesthetic; no purple/blue SaaS gradients; no color-only status.
- Persistent alarm log with dedup + auto-clear + acknowledge.
- BOI suppressed when data quality < 70 %.
- CO > 500 ppm dominates the UI with a full-width red banner.

## What's Been Implemented (2026-02)
- ✅ FastAPI simulation engine (10 tags, load-derived expected values, BOI weighted score, quadrant classification, CSS score, dry gas loss + INR cost estimate, operator guidance).
- ✅ Six scenarios: Normal / Excess Air / Under-Air CO Risk / Drum Level Excursion / Soot Blowing / Sensor Data Quality Drop.
- ✅ Auto scenario injection every 60–120 s during Normal Operation.
- ✅ Alert dedup by stable key, auto-clear after ~30 s of sustained normal band, ack + ack-all.
- ✅ React app shell with sidebar nav, persistent header (Unit Load, Mode ribbon with duration, DQ badge, unack'd-critical banner).
- ✅ PAI-S01: BOI radial gauge (custom SVG), deviation waterfall, parameter grid with sortable columns and sparklines, tabbed trend charts (Steam/Feedwater/Draft/Combustion/Back-End), alarm panel, daily summary strip.
- ✅ PAI-S03: O₂ dial with shaded target band, EA banner, CO safety indicator, CO-O₂ quadrant plot with fading trail, O₂ trend chart, AFR strip, efficiency impact card (₹/hr), operator guidance box, CSS badge, CO-critical full-width banner.
- ✅ Testing agent verified: backend 100 %, frontend 100 %.

## Prioritised Backlog

### P1
- Persist alarm log & daily min/avg/max across page refreshes (MongoDB collection).
- User-configurable weights and thresholds per parameter (admin page).
- WebSocket transport (replace polling) for sub-second updates on quadrant plot.

### P2
- Playback / historian mode with time-slider scrubbing.
- Export daily summary as PDF (management report).
- Additional screens: PAI-S02 Heat Rate, PAI-S04 Steam Purity.
- Multi-boiler / multi-unit navigation.
- Role-based auth for operator vs. engineer vs. viewer.

## Next Tasks
1. Wire MongoDB persistence for alarm log & daily rollups.
2. Add configuration UI for weights/thresholds.
3. Layer real DCS/OPC-UA ingestion behind the same `/api/state` contract.
