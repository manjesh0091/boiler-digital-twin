import React from "react";
import { useTelemetryState } from "@/components/Layout";
import O2Gauge from "@/components/O2Gauge";
import { DataSourceChip } from "@/components/StatusChips";
import { STATUS_COLOR, fmtNumber } from "@/lib/format";
import { S03 } from "@/constants/testIds";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
  ResponsiveContainer, LineChart, Line, ReferenceArea, Legend, ZAxis,
} from "recharts";

const renderLivePoint = (qColor) => (props) => (
  <g>
    <circle cx={props.cx} cy={props.cy} r={7} fill={qColor} />
    <circle cx={props.cx} cy={props.cy} r={12} fill="none" stroke={qColor} strokeOpacity={0.4} />
  </g>
);

function GuidanceBox({ guidance }) {
  const color = guidance?.level === "critical" ? STATUS_COLOR.red : guidance?.level === "warning" ? STATUS_COLOR.amber : STATUS_COLOR.green;
  const label = guidance?.level === "critical" ? "CRITICAL" : guidance?.level === "warning" ? "WARNING" : "OPTIMAL";
  return (
    <div data-testid={S03.guidance} className="panel">
      <div className="panel-header">
        <span>Operator Guidance</span>
        <span className="font-mono text-[10px]" style={{ color, border: `1px solid ${color}`, padding: "2px 6px" }}>{label}</span>
      </div>
      <div className="p-3 text-sm text-zinc-200 leading-relaxed">
        {guidance?.text || "Awaiting data…"}
      </div>
      {guidance?.references_co && (
        <div className="px-3 pb-3 -mt-1 flex items-center gap-1.5">
          <DataSourceChip dataSource="simulated" />
          <span className="text-[10px] text-zinc-600">CO reading referenced above is simulated, pending sensor confirmation</span>
        </div>
      )}
    </div>
  );
}

export default function CombustionMonitor() {
  const state = useTelemetryState();
  const c = state?.combustion || {};

  const coColor = c.co_ppm > 500 ? STATUS_COLOR.red : c.co_ppm > 300 ? STATUS_COLOR.amber : STATUS_COLOR.green;

  const qColor = STATUS_COLOR[c.quadrant?.color] || STATUS_COLOR.green;

  // Trend data — combine o2 history (from parameters) + load
  const o2Param = (state?.parameters || []).find((p) => p.key === "o2");
  const stackParam = (state?.parameters || []).find((p) => p.key === "stack_temp");
  const trend = React.useMemo(() => {
    if (!o2Param) return [];
    const rows = o2Param.history.map((v, i) => ({ i, o2: v }));
    // load history not stored per point; overlay current load line only
    return rows;
  }, [o2Param]);

  const trail = c.quadrant_trail || [];
  const currentPoint = trail.length ? trail[trail.length - 1] : { x: 0, y: 0 };

  const afrPct = c.afr_actual && c.afr_design ? (c.afr_actual / c.afr_design) * 100 : 100;
  // afr_design is still simulated pending coal Ultimate Analysis (Phase B)
  // -- comparing a real Actual against a placeholder Design shouldn't paint
  // an alarm-red bar over what might not be a real problem at all.
  const afrDesignReal = c.data_source?.afr_design === "real";
  const afrColor = !afrDesignReal
    ? STATUS_COLOR.grey
    : Math.abs(afrPct - 100) < 10 ? STATUS_COLOR.green : Math.abs(afrPct - 100) < 25 ? STATUS_COLOR.amber : STATUS_COLOR.red;

  return (
    <div data-testid={S03.root} className="grid grid-cols-12 gap-3">
      {/* CO Critical banner — dominates when > 500 */}
      {c.co_ppm > 500 && (
        <div data-testid={S03.coCriticalBanner} className="col-span-12 border-2 border-status-red bg-[#EF444422] text-status-red px-4 py-3 alarm-pulse flex items-center gap-4">
          <span className="font-mono text-2xl">■</span>
          <div>
            <div className="font-display uppercase tracking-widest text-lg">CO CRITICAL — {fmtNumber(c.co_ppm, 0)} ppm</div>
            <div className="text-sm mt-0.5">Verify air supply immediately. Do NOT reduce air until CO confirmed safe.</div>
          </div>
        </div>
      )}

      {/* Top row: O2 gauge, EA banner, CO indicator */}
      <section className="col-span-5 panel">
        <div className="panel-header">
          <span>O₂ Real-Time</span>
          <div className="flex items-center gap-2">
            <DataSourceChip dataSource={c.data_source?.o2_pct} />
            <span className="text-[10px] font-mono text-zinc-500">Load-corrected target</span>
          </div>
        </div>
        <div className="p-3" data-testid={S03.o2Gauge}>
          <O2Gauge value={c.o2_pct || 0} target={c.o2_target || 4} bandLow={c.o2_band_low || 3} bandHigh={c.o2_band_high || 6} max={12} />
        </div>
      </section>

      <section className="col-span-4 grid grid-rows-2 gap-3">
        <div className="panel" data-testid={S03.eaBanner}>
          <div className="panel-header"><span>Excess Air</span><DataSourceChip dataSource={c.data_source?.excess_air_pct} /></div>
          <div className="p-4 flex items-baseline gap-3">
            <span className="num-ticker text-5xl font-mono font-semibold text-zinc-100">
              {fmtNumber(c.excess_air_pct, 1)}
            </span>
            <span className="text-sm text-zinc-500">%</span>
          </div>
          <div className="px-4 pb-3 text-[10px] font-mono text-zinc-500">
            EA = O₂ / (21 − O₂) × 100
          </div>
        </div>
        <div className="panel" data-testid={S03.cssBadge}>
          <div className="panel-header"><span>Combustion Stability</span><DataSourceChip dataSource={c.data_source?.css} /></div>
          <div className="p-4 flex items-baseline gap-3">
            <span
              className="num-ticker text-4xl font-mono font-semibold"
              style={{ color: c.css >= 80 ? STATUS_COLOR.green : c.css >= 60 ? STATUS_COLOR.amber : STATUS_COLOR.red }}
            >
              {fmtNumber(c.css, 1)}
            </span>
            <span className="text-sm text-zinc-500">/ 100</span>
          </div>
          <div className="px-4 pb-3 text-[10px] font-mono text-zinc-500">CSS = 0.5·O₂ + 0.3·CO + 0.2·Quadrant</div>
        </div>
      </section>

      <section className="col-span-3 panel" data-testid={S03.coIndicator} style={{ borderColor: coColor }}>
        <div className="panel-header"><span>CO Safety</span><DataSourceChip dataSource={c.data_source?.co_ppm} /></div>
        <div className="p-4">
          <div className="flex items-baseline gap-2">
            <span className="num-ticker text-5xl font-mono font-semibold" style={{ color: coColor }}>
              {fmtNumber(c.co_ppm, 0)}
            </span>
            <span className="text-sm text-zinc-500">ppm</span>
          </div>
          <div className="mt-3 flex justify-between text-[10px] font-mono">
            <span style={{ color: STATUS_COLOR.green }}>&lt;200 OK</span>
            <span style={{ color: STATUS_COLOR.amber }}>200-500 WRN</span>
            <span style={{ color: STATUS_COLOR.red }}>&gt;500 ERR</span>
          </div>
          <div className="mt-3 h-2 bg-[#0B0B0C] border border-[#2A2A2E]">
            <div
              className="h-full"
              style={{
                width: `${Math.min(100, (c.co_ppm || 0) / 8)}%`,
                background: coColor,
                transition: "width 400ms ease-out",
              }}
            />
          </div>
        </div>
      </section>

      {/* CO-O2 Quadrant + O2 Trend */}
      <section className="col-span-6 panel" data-testid={S03.quadrantPlot}>
        <div className="panel-header">
          <span>CO – O₂ Quadrant</span>
          <div className="flex items-center gap-2">
            <DataSourceChip dataSource={c.data_source?.quadrant} />
            <span
              className="font-mono text-[10px] px-2 py-0.5"
              style={{ color: qColor, border: `1px solid ${qColor}` }}
            >
              {c.quadrant?.label || "—"}
            </span>
          </div>
        </div>
        <div className="p-2 h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 20, bottom: 20, left: 8 }}>
              <CartesianGrid stroke="#27272A" />
              <XAxis
                type="number"
                dataKey="x"
                stroke="#71717A"
                domain={[-4, 6]}
                label={{ value: "O₂ deviation (% pt)", fill: "#A1A1AA", fontSize: 10, position: "insideBottom", offset: -8 }}
                tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
              />
              <YAxis
                type="number"
                dataKey="y"
                stroke="#71717A"
                domain={[0, 800]}
                label={{ value: "CO ppm", fill: "#A1A1AA", fontSize: 10, angle: -90, position: "insideLeft" }}
                tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
              />
              <ZAxis range={[40, 40]} />
              {/* Quadrant labels via ReferenceArea */}
              <ReferenceArea x1={-4} x2={-1} y1={300} y2={800} fill={STATUS_COLOR.red} fillOpacity={0.06} label={{ value: "Q2 DANGEROUS", position: "insideTopLeft", fill: STATUS_COLOR.red, fontSize: 10 }} />
              <ReferenceArea x1={2} x2={6} y1={0} y2={200} fill={STATUS_COLOR.amber} fillOpacity={0.06} label={{ value: "Q3 WASTEFUL", position: "insideBottomRight", fill: STATUS_COLOR.amber, fontSize: 10 }} />
              <ReferenceArea x1={2} x2={6} y1={300} y2={800} fill={STATUS_COLOR.red} fillOpacity={0.06} label={{ value: "Q4 ABNORMAL", position: "insideTopRight", fill: STATUS_COLOR.red, fontSize: 10 }} />
              <ReferenceArea x1={-0.5} x2={1.5} y1={0} y2={200} fill={STATUS_COLOR.green} fillOpacity={0.1} label={{ value: "Q1 OPTIMAL", position: "insideBottomLeft", fill: STATUS_COLOR.green, fontSize: 10 }} />
              <ReferenceLine x={0} stroke="#3F3F46" />
              <ReferenceLine y={500} stroke={STATUS_COLOR.red} strokeDasharray="4 4" />
              <Tooltip cursor={{ stroke: "#3F3F46" }} />
              {/* Fading trail */}
              {trail.slice(0, -1).map((pt, i) => (
                <Scatter
                  key={i}
                  data={[pt]}
                  fill="#A1A1AA"
                  fillOpacity={(i + 1) / trail.length * 0.5}
                  isAnimationActive={false}
                />
              ))}
              {/* Live point */}
              <Scatter
                data={[currentPoint]}
                fill={qColor}
                shape={renderLivePoint(qColor)}
                isAnimationActive={false}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="col-span-6 panel" data-testid={S03.o2Trend}>
        <div className="panel-header"><span>O₂ Trend</span><span className="text-[10px] font-mono text-zinc-500">Session window</span></div>
        <div className="p-2 h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trend} margin={{ top: 8, right: 30, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="#27272A" strokeDasharray="2 2" />
              <XAxis dataKey="i" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <YAxis stroke="#71717A" domain={[0, 12]} tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <Tooltip />
              <ReferenceArea y1={c.o2_band_low || 3} y2={c.o2_band_high || 6} fill={STATUS_COLOR.green} fillOpacity={0.08} />
              <ReferenceLine y={c.o2_target || 4} stroke={STATUS_COLOR.green} strokeDasharray="3 3" label={{ value: `target ${(c.o2_target || 4).toFixed(1)}%`, fill: STATUS_COLOR.green, fontSize: 10, position: "insideTopRight" }} />
              <Line type="monotone" dataKey="o2" stroke="#E4E4E7" strokeWidth={1.5} dot={false} isAnimationActive={false} name="O₂ %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* AFR strip + Efficiency + Guidance */}
      <section className="col-span-4 panel" data-testid={S03.afrStrip}>
        <div className="panel-header"><span>Air-Fuel Ratio</span></div>
        <div className="p-3">
          <div className="flex justify-between items-baseline">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Actual</div>
              <div className="num-ticker text-3xl font-mono" style={{ color: afrColor }}>{fmtNumber(c.afr_actual, 2)}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display flex items-center gap-1.5 justify-end">
                <span>Design</span>
                <DataSourceChip dataSource={c.data_source?.afr_design} />
              </div>
              <div className="num-ticker text-3xl font-mono text-zinc-400">{fmtNumber(c.afr_design, 2)}</div>
            </div>
          </div>
          <div className="mt-3 relative h-3 bg-[#0B0B0C] border border-[#2A2A2E]">
            <div
              className="absolute top-0 bottom-0 left-1/2 w-px bg-zinc-500"
              style={{ transform: "translateX(-50%)" }}
            />
            <div
              className="h-full"
              style={{
                width: `${Math.min(100, Math.max(0, afrPct / 2))}%`,
                background: afrColor,
                transition: "width 400ms ease-out",
              }}
            />
          </div>
          <div className="mt-2 text-[10px] font-mono text-zinc-500">
            Ratio to design: {fmtNumber(afrPct, 1)}%
          </div>
          {!afrDesignReal && (
            <div className="mt-1 text-[10px] text-zinc-600 italic">
              Design value simulated (pending coal Ultimate Analysis) — ratio not yet meaningful.
            </div>
          )}
        </div>
      </section>

      <section className="col-span-4 panel" data-testid={S03.efficiencyCard}>
        <div className="panel-header"><span>Efficiency Impact</span><span className="text-[10px] font-mono text-zinc-500">Illustrative</span></div>
        <div className="p-3 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-zinc-500">Excess O₂ above target</span>
            <span className="font-mono text-zinc-200">{fmtNumber(c.efficiency?.excess_o2_pct, 2)} %</span>
          </div>
          <div className="flex justify-between">
            <span className="text-zinc-500">Dry gas loss delta</span>
            <span className="font-mono text-zinc-200">{fmtNumber(c.efficiency?.dry_gas_loss_delta_pct, 3)} %</span>
          </div>
          <div className="pt-2 border-t border-[#2A2A2E]">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display flex items-center gap-1.5">
              <span>Avoidable Cost</span>
              <DataSourceChip dataSource={c.data_source?.["efficiency.avoidable_cost_inr_per_hr"]} />
            </div>
            <div className="mt-1 flex items-baseline gap-1">
              <span
                className="num-ticker text-3xl font-mono font-semibold"
                style={{ color: (c.efficiency?.avoidable_cost_inr_per_hr || 0) > 500 ? STATUS_COLOR.amber : STATUS_COLOR.green }}
              >
                ₹{Number(c.efficiency?.avoidable_cost_inr_per_hr || 0).toLocaleString("en-IN")}
              </span>
              <span className="text-xs text-zinc-500">/ hr</span>
            </div>
          </div>
          <div className="text-[10px] text-zinc-600 mt-2">
            DGL(%) ≈ 0.028 · O₂<sub>excess</sub> · (T<sub>stack</sub> − T<sub>amb</sub>) / GCV. Coal ₹{6.5}/kg.
          </div>
        </div>
      </section>

      <div className="col-span-4">
        <GuidanceBox guidance={c.guidance} />
      </div>
    </div>
  );
}
