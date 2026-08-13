import React, { useEffect, useMemo, useRef, useState } from "react";
import { useEfficiencyTelemetry } from "@/hooks/useEfficiencyTelemetry";
import { DataSourceChip, ZoneChip } from "@/components/StatusChips";
import { STATUS_COLOR, fmtNumber, timeShort } from "@/lib/format";
import { S02 } from "@/constants/testIds";
import {
  BarChart, Bar, XAxis, YAxis, Cell, ResponsiveContainer, Tooltip,
  LineChart, Line, CartesianGrid, ReferenceLine, Legend,
} from "recharts";

const LOSS_TERMS = [
  { key: "dry_flue_gas_loss_pct", name: "Dry Flue Gas Loss" },
  { key: "hydrogen_moisture_loss_pct", name: "H₂ Moisture Loss" },
  { key: "fuel_moisture_loss_pct", name: "Fuel Moisture Loss" },
  { key: "air_moisture_loss_pct", name: "Air Moisture Loss" },
  { key: "unburned_carbon_loss_pct", name: "Unburned Carbon Loss" },
  { key: "sensible_heat_loss_pct", name: "Ash Sensible Heat Loss" },
  { key: "surface_radiation_loss_pct", name: "Surface Radiation Loss" },
  { key: "other_loss_pct", name: "Other Loss" },
];

// Phase C: these two bars are legitimate additional detail from the
// calculation engine, not in the original spec's 8 named loss terms --
// noted inline (custom tooltip below) rather than hidden or relabeled.
const EXTRA_LOSS_NOTE =
  "Additional detail beyond the original spec's 8 named loss terms, computed by the calculation engine.";
const EXTRA_LOSS_KEYS = new Set(["other_loss_pct", "sensible_heat_loss_pct"]);

const CREDIT_TERMS = [
  { key: "entering_dry_air_credit_pct", name: "Entering Dry Air" },
  { key: "entering_air_moisture_credit_pct", name: "Entering Air Moisture" },
  { key: "fuel_sensible_heat_credit_pct", name: "Fuel Sensible Heat" },
  { key: "auxiliary_power_credit_pct", name: "Auxiliary Power" },
];

function LossTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-[#141416] border border-[#2A2A2E] px-2 py-1.5 text-[10px] font-mono max-w-[220px]">
      <div className="text-zinc-200">{row.name}: {Number(row.loss).toFixed(3)}%</div>
      {EXTRA_LOSS_KEYS.has(row.key) && (
        <div className="text-zinc-500 mt-1 leading-relaxed normal-case">{EXTRA_LOSS_NOTE}</div>
      )}
    </div>
  );
}

const ENTHALPY_ROWS = [
  { key: "steam_exit_kj_kg", name: "Steam / Flue-Gas Exit" },
  { key: "water_reference_kj_kg", name: "Water — Reference" },
  { key: "water_vapor_stack_kj_kg", name: "Water Vapor — Stack" },
  { key: "dry_gas_exit_kj_kg", name: "Dry Gas — Exit" },
  { key: "dry_gas_reference_kj_kg", name: "Dry Gas — Reference" },
  { key: "dry_air_entering_kj_kg", name: "Dry Air — Entering" },
  { key: "water_vapor_exit_kj_kg", name: "Water Vapor — Exit" },
  { key: "water_vapor_entering_kj_kg", name: "Water Vapor — Entering" },
  { key: "fuel_entering_kj_kg", name: "Fuel — Entering" },
];

const CORRECTION_ROWS = [
  { key: "air_temperature_correction_pct", name: "Air Temperature" },
  { key: "air_humidity_correction_pct", name: "Air Humidity" },
  { key: "fuel_moisture_correction_pct", name: "Fuel Moisture" },
  { key: "fuel_hydrogen_correction_pct", name: "Fuel Hydrogen" },
  { key: "fuel_hhv_correction_pct", name: "Fuel HHV" },
];

const DATA_SOURCE_GROUP_LABEL = {
  fuel: "Fuel Analysis",
  refuse: "Refuse / Ash",
  ambient: "Ambient",
  gas: "Gas / Air-Heater",
  enthalpy: "Enthalpy Reference",
  assumptions: "Engineering Assumptions",
  boiler_duty: "Boiler Duty (Steam/Feedwater)",
  gcv_check: "GCV Check Config",
};

function groupDataSource(dataSource) {
  const groups = {};
  for (const [k, v] of Object.entries(dataSource || {})) {
    const [prefix, ...rest] = k.split(".");
    const field = rest.join(".");
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push({ field, value: v });
  }
  return groups;
}

// Visual-consistency pass: verbose always-on prose (assumption_notes, loss
// caveats) was the single biggest reason PAI-S02 read as a document rather
// than a dashboard, unlike PAI-S01/PAI-S03 which have no equivalent
// always-visible multi-sentence blocks (checked, not assumed -- neither
// page has a comparable pattern). Collapsed by default, one click away.
function Collapsible({ label, count, children, testId, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-[10px] font-mono text-zinc-500 hover:text-zinc-300 uppercase tracking-wider py-1"
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>{label}{count !== undefined ? ` (${count})` : ""}</span>
      </button>
      {open && <div className="pt-1">{children}</div>}
    </div>
  );
}

function Panel({ title, right, testId, children, className = "" }) {
  return (
    <section className={`panel ${className}`} data-testid={testId}>
      <div className="panel-header">
        <span>{title}</span>
        {right}
      </div>
      {children}
    </section>
  );
}

export default function EfficiencyMonitor() {
  const { state } = useEfficiencyTelemetry(2000);
  const [history, setHistory] = useState([]);
  const idxRef = useRef(0);

  useEffect(() => {
    if (state?.status !== "ok") return;
    const v = state.efficiency?.values?.boiler_efficiency_hhv_pct;
    if (v === undefined || v === null) return;
    idxRef.current += 1;
    setHistory((h) => {
      const next = [...h, { i: idxRef.current, eff: v, load: state.unit_load_pct, ts: state.source_timestamp }];
      return next.length > 150 ? next.slice(next.length - 150) : next;
    });
  }, [state]);

  const dataSourceGroups = useMemo(() => groupDataSource(state?.data_source), [state]);

  const lossRows = useMemo(() => {
    const vals = state?.efficiency?.values || {};
    return LOSS_TERMS
      .map((t) => ({ ...t, loss: vals[t.key] ?? 0 }))
      .sort((a, b) => b.loss - a.loss);
  }, [state]);

  // "auto" domain only fits the live eff line's own range -- with eff
  // currently running well below design, the Design/Amber/Red reference
  // lines below would silently fall outside the visible range and never
  // render. Explicit domain that always includes them, padded slightly
  // either side. Computed here (before the early return below) so this
  // hook always runs, same as every other hook in this component.
  const effDomain = useMemo(() => {
    const z = state?.zone || {};
    const designLine = z.eta_design_pct;
    const amberLine = z.eta_design_pct !== undefined ? z.eta_design_pct - z.green_max_pct : undefined;
    const redLine = z.eta_design_pct !== undefined ? z.eta_design_pct - z.amber_max_pct : undefined;
    const vals = history.map((h) => h.eff).filter((v) => v !== undefined && v !== null);
    const refs = [designLine, amberLine, redLine].filter((v) => v !== undefined);
    const all = [...vals, ...refs];
    if (all.length === 0) return ["auto", "auto"];
    const min = Math.min(...all), max = Math.max(...all);
    const pad = Math.max((max - min) * 0.08, 0.1);
    // Round to 1 decimal (%.1f is plenty of precision for an efficiency
    // trend) -- an un-rounded float bound here makes Recharts' automatic
    // tick generator produce garbled repeating-decimal tick labels.
    return [Math.floor((min - pad) * 10) / 10, Math.ceil((max + pad) * 10) / 10];
  }, [history, state]);

  if (!state) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500 font-mono text-sm">
        Loading efficiency calculation…
      </div>
    );
  }

  const ok = state.status === "ok";
  const eff = state.efficiency?.values || {};
  const corr = state.corrections?.values || {};
  const boilerDuty = state.boiler_duty?.values || {};
  const firing = state.fuel_firing?.values || {};
  const gcv = state.gcv_check?.values || {};
  const airFlueGas = state.air_flue_gas?.values || {};
  const gasCalc = state.gas_calculated || {};
  const enthalpy = state.enthalpy || {};
  const warnings = state.warnings || [];
  // undefined (data_gap/error -- gcv is {}) must NOT read as "WARN": that
  // would show a false alarm badge for a tick that never actually computed
  // a GCV check at all.
  const gFactorOk = ok && (gcv.correction_required === 0 || gcv.correction_required === 0.0);
  const zone = state.zone || {};
  const coFlag = zone.flags?.co_incomplete_combustion;
  const coLoss = state.co_loss;
  const alertCards = state.alert_cards || [];
  const shiftSummary = state.shift_summary || [];
  const dataQuality = state.data_quality;
  // Reference lines for the Trend Panel (Phase D): eta_design + the two
  // zone-boundary efficiencies implied by the same GREEN/AMBER/RED bands
  // the gauge uses (design - green_max = amber boundary, design - amber_max
  // = red boundary) -- not separate numbers, the same zone.* the gauge
  // already renders, just expressed as absolute efficiency values instead
  // of deviation points.
  const etaDesignLine = zone.eta_design_pct;
  const etaAmberLine = zone.eta_design_pct !== undefined ? zone.eta_design_pct - zone.green_max_pct : undefined;
  const etaRedLine = zone.eta_design_pct !== undefined ? zone.eta_design_pct - zone.amber_max_pct : undefined;

  return (
    <div data-testid={S02.root} className="grid grid-cols-12 gap-3">
      {!ok && (
        <div
          data-testid={S02.dataGapBanner}
          className="col-span-12 border border-status-amber text-status-amber px-3 py-2 font-display uppercase tracking-widest text-sm flex items-center gap-3"
        >
          <span className="font-mono">■</span>
          {state.status === "data_gap" ? "DATA GAP — "
            : state.status === "invalid_inputs" ? "INPUTS INVALID — "
            : "CALCULATION ERROR — "}
          <span className="normal-case tracking-normal font-mono text-xs text-zinc-300">{state.error}</span>
        </div>
      )}

      {ok && warnings.length > 0 && (
        <div
          data-testid={S02.warningsBanner}
          className="col-span-12 border border-status-amber text-status-amber px-3 py-2 text-sm flex flex-col gap-1"
        >
          {warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="font-mono">■</span>
              <span className="font-mono text-xs">{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Efficiency Gauge + Loss Breakdown Waterfall */}
      <Panel title="Boiler Efficiency" testId={S02.effGauge} className="col-span-4" right={<span className="text-[10px] font-mono text-zinc-500">ASME PTC-4 Indirect Method</span>}>
        <div className="p-4 flex flex-col items-center">
          <div className="flex items-center gap-2">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">HHV Efficiency</div>
            {ok && zone.zone && <ZoneChip zone={zone.zone} />}
          </div>
          <div className="flex items-baseline gap-2 mt-1">
            <span
              className="num-ticker text-6xl font-mono font-semibold"
              style={{ color: ok && zone.zone ? STATUS_COLOR[zone.zone] : undefined }}
              data-testid={S02.effGaugeValue}
            >
              {fmtNumber(eff.boiler_efficiency_hhv_pct, 2)}
            </span>
            <span className="text-sm text-zinc-500">%</span>
          </div>
          {ok && zone.eta_design_pct !== undefined && (
            <div className="mt-2 text-[11px] font-mono text-zinc-400" data-testid={S02.effGaugeDeviation}>
              vs. design {fmtNumber(zone.eta_design_pct, 2)}% — deviation {zone.eta_deviation_pct >= 0 ? "+" : ""}{fmtNumber(zone.eta_deviation_pct, 2)} pts
            </div>
          )}
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Appendix D-4 Corrected</span>
            <span className="num-ticker text-lg font-mono text-zinc-300">{fmtNumber(corr.corrected_boiler_efficiency_hhv_pct, 2)}%</span>
          </div>
          {ok && zone.eta_guaranteed_pct !== undefined && (
            <div className="mt-1 text-[10px] font-mono text-zinc-600">
              Guaranteed (contract floor): {fmtNumber(zone.eta_guaranteed_pct, 2)}% — reference only, not used in zone above
            </div>
          )}
          {coFlag?.triggered && (
            <div
              className="mt-3 text-[10px] font-mono px-2 py-1"
              style={{ color: STATUS_COLOR.red, border: `1px solid ${STATUS_COLOR.red}` }}
              data-testid={S02.effGaugeCoFlag}
            >
              CO {fmtNumber(coFlag.co_ppm, 0)} ppm &gt; {fmtNumber(coFlag.setpoint_ppm, 0)} — INCOMPLETE COMBUSTION (SIMULATED CO — not a real tag yet)
            </div>
          )}
          <div className="mt-4 text-[10px] text-zinc-600 text-center leading-relaxed">
            Zone (green ≤1.0pt / amber ≤2.5pt / red &gt;2.5pt below design) from
            eta_deviation = eta_design − eta_actual, per the PAI-S02 spec's
            Scoring_Model. Excess Dry Gas Loss / Excess Unburnt Carbon flags
            are not shown — their plant-specific setpoints aren't given in
            the spec and haven't been supplied yet (configurable-pending,
            not guessed).
          </div>
        </div>
      </Panel>

      <Panel
        title="Loss Breakdown Waterfall"
        testId={S02.lossWaterfall}
        className="col-span-8"
        right={<span className="text-[10px] font-mono text-zinc-500">% of HHV input, largest first</span>}
      >
        <div className="p-2 h-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={lossRows} layout="vertical" margin={{ top: 4, right: 30, bottom: 4, left: 8 }}>
              <XAxis type="number" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} unit="%" />
              <YAxis type="category" dataKey="name" stroke="#A1A1AA" width={150} tick={{ fontSize: 10, fontFamily: "IBM Plex Sans" }} />
              <Tooltip cursor={{ fill: "#22222608" }} content={<LossTooltip />} />
              <Bar dataKey="loss" radius={[0, 0, 0, 0]}>
                {lossRows.map((row, i) => (
                  <Cell key={row.key} fill={STATUS_COLOR.amber} opacity={i === 0 ? 1 : 0.75 - i * 0.06} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {/* Phase C: CO Loss stub -- a named spec component (L5) with no
            formula anywhere in the calculation engine (confirmed by
            grepping the whole library), so it can't be a bar on a numeric
            axis without implying a fabricated magnitude. Shown as its own
            clearly-labeled strip instead, tagged unavailable_no_formula --
            distinct from a blocked/stale REAL value. */}
        <div
          data-testid={S02.coLossStub}
          className="mx-3 mb-2 px-2 py-1.5 flex items-center justify-between text-[10px] font-mono"
          style={{ border: "1px dashed #3F3F46", color: "#71717A" }}
        >
          <span>{coLoss?.message || "CO Loss — not computed (no formula exists in the calculation engine)"}</span>
          <DataSourceChip dataSource={coLoss?.data_source || "unavailable_no_formula"} />
        </div>
        <div className="px-3 pb-3">
          <Collapsible label="Notes on these figures">
            <div className="text-[10px] text-zinc-600 leading-relaxed pt-1">
              Every loss term above depends on at least one placeholder input
              (fuel composition, refuse/ash, or air-heater gas temps) — see
              the Data Source / Assumptions panel below before treating these
              as measured. Unburned Carbon Loss / Ash Sensible Heat Loss are
              each a single figure combined across all 4 ash streams
              (bed/cyclone/APH/ESP) — not yet split into the spec's separate
              Fly Ash / Bottom Ash terms (genuinely ambiguous mapping, kept
              as Awes's native terms rather than force-relabeled — see Data
              Source / Assumptions panel).
            </div>
          </Collapsible>
        </div>
      </Panel>

      {/* Data Source / Assumptions panel -- deliberately prominent, right
          after the headline numbers, not buried at the page bottom. */}
      <Panel
        title="Data Source / Assumptions"
        testId={S02.assumptionsPanel}
        className="col-span-12"
        right={
          <div className="flex items-center gap-3">
            {dataQuality && (
              <span
                data-testid={S02.dataQualityBadge}
                className="font-mono text-[10px] px-2 py-0.5 uppercase tracking-wider"
                style={{
                  color: dataQuality.composite === "good" ? STATUS_COLOR.green : STATUS_COLOR.amber,
                  border: `1px solid ${dataQuality.composite === "good" ? STATUS_COLOR.green : STATUS_COLOR.amber}`,
                }}
                title={`GCV: ${dataQuality.gcv_fresh ? "fresh" : "stale"} · O2: ${dataQuality.o2_data_source} · Fly-ash: ${dataQuality.fly_ash_data_source} (not time-tracked)`}
              >
                Data Quality: {dataQuality.composite === "good" ? "GOOD" : "DEGRADED"}
              </span>
            )}
            <span className="text-[10px] font-mono text-zinc-500">what this calculation run actually used</span>
          </div>
        }
      >
        {dataQuality && (
          <div className="px-3 pt-2 flex gap-4 text-[10px] font-mono text-zinc-500">
            <span>GCV freshness: <span className={dataQuality.gcv_fresh ? "text-status-green" : "text-status-amber"}>{dataQuality.gcv_fresh ? "FRESH" : "STALE"}</span></span>
            <span>O2 validity: <span className="text-zinc-300">{dataQuality.o2_data_source.toUpperCase()}</span></span>
            <span>Fly-ash data: <span className="text-zinc-600">STATIC (not time-tracked)</span></span>
          </div>
        )}
        <div className="p-3 grid grid-cols-4 gap-3">
          {Object.entries(dataSourceGroups).map(([prefix, fields]) => (
            <div key={prefix} className="bg-[#141416] border border-[#2A2A2E] p-2">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display mb-1.5">
                {DATA_SOURCE_GROUP_LABEL[prefix] || prefix}
              </div>
              <div className="space-y-1">
                {fields.map((f) => (
                  <div key={f.field} className="flex items-center justify-between gap-2 text-[10px] font-mono">
                    <span className="text-zinc-400 truncate">{f.field}</span>
                    {f.value === "real" ? (
                      <span className="text-status-green shrink-0">REAL</span>
                    ) : (
                      <DataSourceChip dataSource={f.value} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        {(state.assumption_notes || []).length > 0 && (
          <div className="px-3 pb-3 border-t border-[#2A2A2E] pt-2 mt-1">
            <Collapsible label="Why these values" count={state.assumption_notes.length}>
              <div className="space-y-2 pt-1">
                {state.assumption_notes.map((n, i) => (
                  <div key={i} className="text-[11px] text-zinc-500 leading-relaxed flex gap-2">
                    <span className="text-zinc-600 shrink-0">▸</span>
                    <span>{n}</span>
                  </div>
                ))}
              </div>
            </Collapsible>
          </div>
        )}
      </Panel>

      {/* Efficiency Alert Cards -- Phase D. Reuses the EFFICIENCY-kind
          alerts already fired by Gates 1/2 (mass balance, GCV check), never
          a separate alert source -- one card per currently-active alert,
          priority-sorted by deviation magnitude (state_builder.py already
          sorts this list). flex-wrap with a per-card max-width (not a rigid
          3-col grid) so 1 active card doesn't leave 2 conspicuously empty
          grid cells -- visual-consistency pass, Step 3. */}
      <Panel
        title="Efficiency Alert Cards"
        testId={S02.alertCards}
        className="col-span-12"
        right={<span className="text-[10px] font-mono text-zinc-500">{alertCards.length} active</span>}
      >
        {alertCards.length === 0 ? (
          <div className="p-3 text-[11px] text-zinc-600 font-mono">No active efficiency deviations.</div>
        ) : (
          <div className="p-3 flex flex-wrap gap-3">
            {alertCards.map((c, i) => (
              <div
                key={i}
                className="bg-[#141416] p-2.5 w-full sm:w-[380px]"
                style={{ border: `1px solid ${c.severity === "red" ? STATUS_COLOR.red : STATUS_COLOR.amber}`, opacity: c.clearing ? 0.6 : 1 }}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] uppercase tracking-widest font-display" style={{ color: c.severity === "red" ? STATUS_COLOR.red : STATUS_COLOR.amber }}>
                    {c.parameter}
                  </span>
                  {c.clearing && (
                    <span className="text-[9px] font-mono text-zinc-500 uppercase tracking-wider" title="Currently back under threshold -- staying active for a short grace period in case it recurs, same debounce every alert in this project uses.">
                      clearing…
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-y-1 text-[11px] font-mono">
                  <span className="text-zinc-500">Current ({c.current_label})</span>
                  <span className="text-right text-zinc-200">{fmtNumber(c.current, 2)}{c.unit}</span>
                  <span className="text-zinc-500">Design ({c.design_label})</span>
                  <span className="text-right text-zinc-200">{typeof c.design === "number" ? fmtNumber(c.design, 2) + c.unit : c.design}</span>
                  <span className="text-zinc-500">Deviation</span>
                  <span className="text-right text-zinc-100 font-semibold">{c.deviation >= 0 ? "+" : ""}{fmtNumber(c.deviation, 2)}{c.unit}</span>
                </div>
                <div className="mt-2 pt-2 border-t border-[#2A2A2E] text-[10px] text-zinc-400">
                  Recommended check: {c.recommended_check}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Heat Credits -- Phase C/D: the 4 credit terms already in
          /api/efficiency's response (efficiency.values.*_credit_pct) were
          previously computed but never shown, so a reader had no way to see
          why 100 - total_loss != efficiency. Grouped with Boiler Duty/GCV
          Check as a col-4/4/4 trio of compact stat cards (visual-consistency
          pass) -- previously sat alone at col-span-4 with 8 columns of dead
          space beside it. */}
      <Panel
        title="Heat Credits"
        testId={S02.heatCreditsCard}
        className="col-span-4"
        right={<span className="text-[10px] font-mono text-zinc-500">added back to 100 − losses</span>}
      >
        <div className="p-2">
          <table className="w-full text-xs">
            <tbody>
              {CREDIT_TERMS.map((r) => (
                <tr key={r.key} className="border-b border-[#151517]">
                  <td className="px-2 py-1.5 text-zinc-500">{r.name}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-zinc-200">{fmtNumber(eff[r.key], 4)}%</td>
                </tr>
              ))}
              <tr>
                <td className="px-2 py-1.5 text-zinc-300 font-semibold">Total Heat Credit</td>
                <td className="px-2 py-1.5 text-right font-mono text-zinc-100 font-semibold">{fmtNumber(eff.total_heat_credit_pct, 4)}%</td>
              </tr>
              <tr>
                <td className="px-2 py-1.5 text-zinc-500">Total Heat Loss</td>
                <td className="px-2 py-1.5 text-right font-mono text-zinc-400">{fmtNumber(eff.total_heat_loss_pct, 4)}%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="px-3 pb-3 text-[10px] text-zinc-600">
          efficiency = 100 − total loss + total credit.
        </div>
      </Panel>

      {/* Boiler Duty & Firing */}
      <Panel title="Boiler Duty & Firing" testId={S02.boilerDutyCard} className="col-span-4">
        <div className="p-3 space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-zinc-500">Boiler Duty</span><span className="font-mono text-zinc-200">{fmtNumber(boilerDuty.boiler_duty_mw, 2)} MW</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Fuel Firing</span><span className="font-mono text-zinc-200">{fmtNumber(firing.fuel_firing_kg_h, 0)} kg/h</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Air Flow</span><span className="font-mono text-zinc-200">{fmtNumber(firing.air_flow_kg_s, 2)} kg/s</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Fuel Heat Input</span><span className="font-mono text-zinc-200">{fmtNumber(firing.fuel_heat_input_mw, 2)} MW</span></div>
        </div>
      </Panel>

      {/* GCV Check */}
      <Panel
        title="GCV Check"
        testId={S02.gcvCheckCard}
        className="col-span-4"
        right={
          <span
            className="font-mono text-[10px] px-2 py-0.5"
            style={{
              color: !ok ? STATUS_COLOR.grey : gFactorOk ? STATUS_COLOR.green : STATUS_COLOR.amber,
              border: `1px solid ${!ok ? STATUS_COLOR.grey : gFactorOk ? STATUS_COLOR.green : STATUS_COLOR.amber}`,
            }}
          >
            {!ok ? "—" : gFactorOk ? "PASS" : "WARN"}
          </span>
        }
      >
        <div className="p-3 space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-zinc-500">Dulong HHV</span><span className="font-mono text-zinc-200">{fmtNumber(gcv.dulong_hhv_kcal_kg, 0)} kcal/kg</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Measured HHV</span><span className="font-mono text-zinc-200">{fmtNumber(gcv.measured_hhv_kcal_kg, 0)} kcal/kg</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">G-Factor</span><span className="font-mono text-zinc-200">{fmtNumber(gcv.g_factor, 4)}</span></div>
          <div className="text-[10px] text-zinc-600 pt-1 border-t border-[#2A2A2E]">Band: [0.95, 1.04] · Dulong HHV uses the placeholder fuel composition, not this plant's coal.</div>
        </div>
      </Panel>

      {/* Air / Flue-Gas Composition */}
      <Panel title="Air / Flue-Gas Composition" testId={S02.airFlueGasCard} className="col-span-4">
        <div className="p-3 space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-zinc-500">Theoretical Air</span><span className="font-mono text-zinc-200">{fmtNumber(airFlueGas.theoretical_air_kg_kg_fuel, 3)} kg/kg</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Excess Air (econ.)</span><span className="font-mono text-zinc-200">{fmtNumber(airFlueGas.excess_air_economizer_pct, 1)} %</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Excess Air (AH outlet)</span><span className="font-mono text-zinc-200">{fmtNumber(airFlueGas.excess_air_air_heater_outlet_pct, 1)} %</span></div>
          <div className="flex justify-between items-center">
            <span className="text-zinc-500 flex items-center gap-1.5">Air-Heater Leakage <DataSourceChip dataSource="simulated" /></span>
            <span className="font-mono text-zinc-200">{fmtNumber(gasCalc.air_heater_leakage_pct, 1)} %</span>
          </div>
          <div className="flex justify-between"><span className="text-zinc-500">Dry Gas CO₂ (econ.)</span><span className="font-mono text-zinc-200">{fmtNumber(airFlueGas.econ_co2_dry_vol_pct, 1)} %</span></div>
          <div className="flex justify-between"><span className="text-zinc-500">Dry Gas O₂ (econ.)</span><span className="font-mono text-zinc-200">{fmtNumber(airFlueGas.econ_o2_dry_vol_pct, 2)} %</span></div>
        </div>
        <div className="px-3 pb-3 text-[10px] text-zinc-600">
          Air-heater leakage is placeholder-driven: no second O₂ sensor exists at the air-heater outlet (see Assumptions panel).
        </div>
      </Panel>

      {/* Heat Balance / Enthalpy table */}
      <Panel title="Heat Balance — Enthalpy Reference" testId={S02.enthalpyTable} className="col-span-4">
        <div className="p-2">
          <table className="w-full text-xs">
            <tbody>
              {ENTHALPY_ROWS.map((r) => (
                <tr key={r.key} className="border-b border-[#151517]">
                  <td className="px-2 py-1.5 text-zinc-500">{r.name}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-zinc-200">{fmtNumber(enthalpy[r.key], 2)} kJ/kg</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Appendix D-4 Corrections */}
      <Panel
        title="Appendix D-4 Corrections"
        testId={S02.correctionsCard}
        className="col-span-4"
        right={
          <span className="font-mono text-[10px] px-2 py-0.5 text-zinc-500" style={{ border: "1px solid #3F3F46" }}>
            G-FACTOR: {!ok ? "—" : gcv.correction_applied ? "APPLIED" : "NOT APPLIED"}
          </span>
        }
      >
        <div className="p-2">
          <table className="w-full text-xs">
            <tbody>
              {CORRECTION_ROWS.map((r) => (
                <tr key={r.key} className="border-b border-[#151517]">
                  <td className="px-2 py-1.5 text-zinc-500">{r.name}</td>
                  <td className="px-2 py-1.5 text-right font-mono text-zinc-200">{fmtNumber(corr[r.key], 4)} pts</td>
                </tr>
              ))}
              <tr>
                <td className="px-2 py-1.5 text-zinc-300 font-semibold">Sum Correction</td>
                <td className="px-2 py-1.5 text-right font-mono text-zinc-100 font-semibold">{fmtNumber(corr.sum_correction_pct, 4)} pts</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="px-3 pb-3 text-[10px] text-zinc-600">
          These contract/design corrections (c1–c5) are always computed by the
          library. The G-factor/GCV composition correction above is a
          separate, disabled-by-default toggle (library README control #6) —
          shown as its own status since it affects which fuel composition
          feeds everything else, not just this card.
        </div>
      </Panel>

      {/* Trend chart */}
      <Panel
        title="Efficiency Trend"
        testId={S02.trendChart}
        className="col-span-12"
        right={<span className="text-[10px] font-mono text-zinc-500">Session window · last {history.length} ticks</span>}
      >
        <div className="p-2 h-[240px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history} margin={{ top: 8, right: 30, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="#27272A" strokeDasharray="2 2" />
              <XAxis dataKey="i" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <YAxis yAxisId="eff" stroke="#71717A" domain={effDomain} tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} unit="%" />
              <YAxis yAxisId="load" orientation="right" stroke="#52525B" domain={[0, 110]} tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} unit="%" />
              <Tooltip labelFormatter={(_, p) => timeShort(p?.[0]?.payload?.ts)} formatter={(v, name) => [`${Number(v).toFixed(2)}%`, name]} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              {etaDesignLine !== undefined && (
                <ReferenceLine yAxisId="eff" y={etaDesignLine} stroke="#A1A1AA" strokeDasharray="4 4" label={{ value: "Design", position: "insideTopLeft", fill: "#A1A1AA", fontSize: 9 }} />
              )}
              {etaAmberLine !== undefined && (
                <ReferenceLine yAxisId="eff" y={etaAmberLine} stroke={STATUS_COLOR.amber} strokeDasharray="2 3" label={{ value: "Amber", position: "insideBottomLeft", fill: STATUS_COLOR.amber, fontSize: 9 }} />
              )}
              {etaRedLine !== undefined && (
                <ReferenceLine yAxisId="eff" y={etaRedLine} stroke={STATUS_COLOR.red} strokeDasharray="2 3" label={{ value: "Red", position: "insideBottomLeft", fill: STATUS_COLOR.red, fontSize: 9 }} />
              )}
              <Line yAxisId="eff" type="monotone" dataKey="eff" stroke="#E4E4E7" strokeWidth={1.5} dot={false} isAnimationActive={false} name="Efficiency %" />
              <Line yAxisId="load" type="monotone" dataKey="load" stroke="#3B82F6" strokeWidth={1} dot={false} isAnimationActive={false} name="Unit Load %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="px-3 pb-3 text-[10px] text-zinc-600">
          Design/Amber/Red reference lines are the same eta_design_pct and
          GREEN/AMBER/RED zone bands the gauge above uses, expressed as
          absolute efficiency values.
        </div>
      </Panel>

      {/* Daily/Shift Summary Table -- Phase D. Our data is a historical
          replay (not truly live shifts) -- "shift" here is a fixed 8-hour
          block over the replay's own source_timestamp, a documented
          simplification versus a real plant shift schedule, not an attempt
          to model actual shift handover times. */}
      <Panel
        title="Daily / Shift Summary"
        testId={S02.shiftSummaryTable}
        className="col-span-12"
        right={<span className="text-[10px] font-mono text-zinc-500">fixed 8h blocks over replay source_timestamp — not real plant shifts</span>}
      >
        {shiftSummary.length === 0 ? (
          <div className="p-3 text-[11px] text-zinc-600 font-mono">No completed shift data yet this session.</div>
        ) : (
          <div className="p-2 overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-zinc-500 text-[10px] uppercase tracking-wider">
                  <th className="text-left px-2 py-1.5">Shift</th>
                  <th className="text-right px-2 py-1.5">Avg η%</th>
                  <th className="text-right px-2 py-1.5">η vs Design</th>
                  <th className="text-right px-2 py-1.5">DGL%</th>
                  <th className="text-right px-2 py-1.5">FA Carbon%*</th>
                  <th className="text-right px-2 py-1.5">GCV kcal/kg</th>
                  <th className="text-right px-2 py-1.5">O2%</th>
                  <th className="text-right px-2 py-1.5">Stack °C</th>
                  <th className="text-right px-2 py-1.5">CO ppm†</th>
                  <th className="text-right px-2 py-1.5">n</th>
                </tr>
              </thead>
              <tbody>
                {shiftSummary.map((s) => {
                  const devColor = s.eta_deviation_pct <= 1.0 ? STATUS_COLOR.green : s.eta_deviation_pct <= 2.5 ? STATUS_COLOR.amber : STATUS_COLOR.red;
                  return (
                    <tr key={s.label} className="border-b border-[#151517] font-mono">
                      <td className="px-2 py-1.5 text-zinc-400">{s.label}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-200">{s.avg_eta_pct.toFixed(2)}</td>
                      <td className="text-right px-2 py-1.5 font-semibold" style={{ color: devColor }}>{s.eta_deviation_pct >= 0 ? "+" : ""}{s.eta_deviation_pct.toFixed(2)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-300">{s.avg_dgl_pct.toFixed(3)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-300">{s.avg_fa_carbon_pct.toFixed(3)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-500">{s.avg_gcv_kcal_kg.toFixed(0)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-300">{s.avg_o2_pct.toFixed(2)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-300">{s.avg_stack_temp_c.toFixed(1)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-500">{s.avg_co_ppm.toFixed(0)}</td>
                      <td className="text-right px-2 py-1.5 text-zinc-600">{s.n_ticks}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="px-3 pb-3 text-[10px] text-zinc-600">
          * FA Carbon = Unburned Carbon Loss, combined across all 4 ash streams, not fly-ash-specific (see Loss Waterfall note). † CO simulated, not a real tag.
        </div>
      </Panel>
    </div>
  );
}
