import React, { useMemo, useState } from "react";
import { useTelemetryState } from "@/components/Layout";
import BOIGauge from "@/components/BOIGauge";
import Sparkline from "@/components/Sparkline";
import AlertPanel from "@/components/AlertPanel";
import { STATUS_COLOR, ZONE_LABEL, fmtNumber } from "@/lib/format";
import { S01 } from "@/constants/testIds";
import {
  BarChart, Bar, XAxis, YAxis, Cell, ResponsiveContainer, Tooltip,
  LineChart, Line, CartesianGrid, ReferenceLine, ReferenceArea, Legend,
} from "recharts";

const PARAM_GROUPS = {
  Steam: ["steam_pressure", "steam_temp", "steam_flow"],
  Feedwater: ["feedwater_flow", "drum_pressure", "drum_level"],
  Draft: ["furnace_draft"],
  Combustion: ["o2", "fegt"],
  "Back-End": ["stack_temp"],
};

function ZoneChip({ zone }) {
  const color = STATUS_COLOR[zone] || STATUS_COLOR.green;
  return (
    <span
      className="font-mono text-[10px] px-1.5 py-0.5"
      style={{ color, border: `1px solid ${color}` }}
    >
      {ZONE_LABEL[zone] || "OK"}
    </span>
  );
}

export default function BoilerDashboard() {
  const state = useTelemetryState();
  const [sortKey, setSortKey] = useState("worst");
  const [trendGroup, setTrendGroup] = useState("Steam");

  const params = state?.parameters || [];
  const sorted = useMemo(() => {
    const arr = [...params];
    if (sortKey === "worst") arr.sort((a, b) => a.sub_score - b.sub_score);
    else if (sortKey === "name") arr.sort((a, b) => a.name.localeCompare(b.name));
    else if (sortKey === "dev") arr.sort((a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct));
    return arr;
  }, [params, sortKey]);

  const waterfall = state?.deviation_waterfall || [];
  const boi = state?.boi || {};
  const safetyIncomplete = state?.safety_data_incomplete;

  // Build trend chart data from current group parameters
  const trendData = useMemo(() => {
    const keys = PARAM_GROUPS[trendGroup] || [];
    const groupParams = params.filter((p) => keys.includes(p.key));
    if (!groupParams.length) return [];
    const len = Math.min(...groupParams.map((p) => p.history.length));
    const rows = [];
    for (let i = 0; i < len; i++) {
      const row = { i };
      groupParams.forEach((p) => {
        row[p.key] = p.history[p.history.length - len + i];
      });
      row.load = (state?.unit_load_pct || 0);
      rows.push(row);
    }
    return { rows, groupParams };
  }, [params, trendGroup, state]);

  return (
    <div data-testid={S01.root} className="grid grid-cols-12 gap-3">
      {safetyIncomplete && (
        <div
          data-testid={S01.safetyIncomplete}
          className="col-span-12 border border-status-red text-status-red px-3 py-2 font-display uppercase tracking-widest text-sm alarm-pulse flex items-center gap-3"
        >
          <span className="font-mono">■</span> INCOMPLETE SAFETY DATA — Drum Level or Furnace Draft tag invalid
        </div>
      )}

      {/* Top row: BOI gauge + Waterfall + Alerts */}
      <section className="col-span-4 panel">
        <div className="panel-header"><span>Composite Score</span><span className="text-[10px] font-mono text-zinc-500">BOI</span></div>
        <div className="p-3" data-testid={S01.boiGauge}>
          <BOIGauge value={boi.value || 0} zone={boi.zone || "green"} suppressed={boi.suppressed} trend={boi.trend} />
          <div className="mt-4 flex justify-center gap-4 text-[10px] font-mono text-zinc-500">
            <span><span className="text-status-red">■</span> &lt;65</span>
            <span><span className="text-status-amber">■</span> 65-80</span>
            <span><span className="text-status-green">■</span> ≥80</span>
          </div>
        </div>
      </section>

      <section className="col-span-5 panel">
        <div className="panel-header"><span>Deviation Waterfall</span><span className="text-[10px] font-mono text-zinc-500">Loss contribution</span></div>
        <div className="p-2 h-[290px]" data-testid={S01.waterfall}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={waterfall} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="#27272A" horizontal={false} />
              <XAxis type="number" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <YAxis type="category" dataKey="name" stroke="#A1A1AA" width={130} tick={{ fontSize: 10, fontFamily: "IBM Plex Sans" }} />
              <Tooltip cursor={{ fill: "#22222608" }} />
              <Bar dataKey="loss" radius={[0, 0, 0, 0]}>
                {waterfall.map((row, i) => (
                  <Cell key={i} fill={STATUS_COLOR[row.zone] || "#A1A1AA"} opacity={i === 0 ? 1 : 0.7} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="col-span-3 row-span-2">
        <AlertPanel alerts={state?.alerts || []} />
      </section>

      {/* Parameter grid */}
      <section className="col-span-9 panel">
        <div className="panel-header">
          <span>Parameter Grid — {params.length} tags</span>
          <div className="flex gap-2 text-[10px]">
            {["worst", "name", "dev"].map((k) => (
              <button
                key={k}
                onClick={() => setSortKey(k)}
                className={`px-2 py-0.5 uppercase tracking-wider font-display border ${
                  sortKey === k ? "border-zinc-300 text-zinc-100" : "border-[#3F3F46] text-zinc-500"
                }`}
              >
                {k === "worst" ? "Sort: Worst" : k === "name" ? "Sort: Name" : "Sort: |dev|"}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto" data-testid={S01.paramGrid}>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-widest text-zinc-500 font-display border-b border-[#2A2A2E]">
                <th className="px-3 py-2">Parameter</th>
                <th className="px-3 py-2 text-right">Actual</th>
                <th className="px-3 py-2 text-right">Expected</th>
                <th className="px-3 py-2 text-right">Δ%</th>
                <th className="px-3 py-2">Zone</th>
                <th className="px-3 py-2">Trend</th>
                <th className="px-3 py-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p) => (
                <tr
                  key={p.key}
                  data-testid={S01.paramRow(p.key)}
                  className="param-row border-b border-[#151517]"
                >
                  <td className="px-3 py-2">
                    <div className="text-zinc-200">{p.name}</div>
                    <div className="text-[10px] text-zinc-600 font-mono">{p.unit}{p.safety ? " · SAFETY" : ""}</div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className="num-ticker font-mono"
                      style={{ color: p.valid ? STATUS_COLOR[p.zone] : "#71717A" }}
                    >
                      {p.valid ? fmtNumber(p.value, 2) : "INV"}
                    </span>
                    <span className="text-[10px] text-zinc-500 ml-1">{p.unit}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-400">{fmtNumber(p.expected, 2)}</td>
                  <td className="px-3 py-2 text-right font-mono" style={{ color: STATUS_COLOR[p.zone] }}>
                    {p.deviation_pct >= 0 ? "+" : ""}{fmtNumber(p.deviation_pct, 1)}%
                  </td>
                  <td className="px-3 py-2"><ZoneChip zone={p.valid ? p.zone : "amber"} /></td>
                  <td className="px-3 py-2">
                    <Sparkline values={p.history} color={STATUS_COLOR[p.zone] || "#A1A1AA"} width={90} height={20} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-zinc-400">{fmtNumber(p.sub_score, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Trend charts */}
      <section className="col-span-9 panel">
        <div className="panel-header">
          <span>Trend Charts</span>
          <div className="flex gap-1" data-testid={S01.trendTabs}>
            {Object.keys(PARAM_GROUPS).map((g) => (
              <button
                key={g}
                data-testid={S01.trendTab(g)}
                onClick={() => setTrendGroup(g)}
                className={`px-2 py-1 text-[10px] uppercase tracking-wider font-display border ${
                  trendGroup === g ? "border-zinc-300 text-zinc-100" : "border-[#3F3F46] text-zinc-500"
                }`}
              >
                {g}
              </button>
            ))}
          </div>
        </div>
        <div className="p-2 h-[240px]" data-testid={S01.trendChart}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData.rows || []} margin={{ top: 8, right: 30, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="#27272A" strokeDasharray="2 2" />
              <XAxis dataKey="i" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <YAxis yAxisId="left" stroke="#71717A" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
              <YAxis yAxisId="right" orientation="right" stroke="#3B82F6" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} domain={[0, 1]} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "IBM Plex Sans" }} />
              {(trendData.groupParams || []).map((p, idx) => (
                <Line
                  key={p.key}
                  yAxisId="left"
                  type="monotone"
                  dataKey={p.key}
                  name={p.name}
                  stroke={["#E4E4E7", "#A1A1AA", "#F5A623", "#10B981", "#3B82F6"][idx % 5]}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
              <Line yAxisId="right" type="monotone" dataKey="load" name="Load frac" stroke="#3B82F6" strokeWidth={1} strokeDasharray="3 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Daily summary */}
      <section className="col-span-12 panel" data-testid={S01.summary}>
        <div className="panel-header"><span>Daily Summary — Session Min / Avg / Max</span></div>
        <div className="grid grid-cols-5 gap-px bg-[#2A2A2E]">
          {params.map((p) => (
            <div key={p.key} className="bg-[#141416] p-2">
              <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">{p.name}</div>
              <div className="mt-1 flex justify-between text-[11px] font-mono">
                <span>
                  <span className="text-zinc-600">min </span>
                  <span className="text-zinc-300">{fmtNumber(p.day_min, 1)}</span>
                </span>
                <span>
                  <span className="text-zinc-600">avg </span>
                  <span className="text-zinc-100">{fmtNumber(p.day_avg, 1)}</span>
                </span>
                <span>
                  <span className="text-zinc-600">max </span>
                  <span className="text-zinc-300">{fmtNumber(p.day_max, 1)}</span>
                </span>
              </div>
              <div className="text-[10px] text-zinc-600 font-mono">{p.unit}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
