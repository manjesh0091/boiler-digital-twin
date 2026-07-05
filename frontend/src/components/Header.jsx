import React, { useEffect, useState } from "react";
import { STATUS_COLOR, fmtDuration } from "@/lib/format";
import { fetchScenarios, setScenario } from "@/lib/api";
import { NAV } from "@/constants/testIds";

const MODE_COLORS = {
  "Steady State": STATUS_COLOR.green,
  "Ramping": STATUS_COLOR.amber,
  "Startup": STATUS_COLOR.amber,
  "Low Load": STATUS_COLOR.amber,
  "Soot Blowing": "#3B82F6",
  "Shutdown": STATUS_COLOR.red,
};

export default function Header({ state }) {
  const [scenarios, setScenarios] = useState([]);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    fetchScenarios().then((d) => setScenarios(d.scenarios || [])).catch(() => {});
  }, []);

  const load = state?.unit_load_mw ?? 0;
  const loadPct = state?.unit_load_pct ?? 0;
  const mode = state?.mode || "—";
  const modeColor = MODE_COLORS[mode] || "#A1A1AA";
  const dq = state?.data_quality_pct ?? 0;
  const dqZone = dq >= 85 ? "green" : dq >= 70 ? "amber" : "red";
  const activeScenario = state?.scenario || "Normal Operation";

  const activeAlerts = (state?.alerts || []).filter((a) => a.active);
  const unackHigh = activeAlerts.filter((a) => !a.acknowledged && a.severity === "red").length;

  const handleChange = async (e) => {
    setPending(true);
    try {
      await setScenario(e.target.value);
    } finally {
      setPending(false);
    }
  };

  return (
    <header className="h-14 border-b border-[#2A2A2E] bg-[#0B0B0C] flex items-center px-4 gap-6 shrink-0">
      {/* Unit Load */}
      <div className="flex items-baseline gap-2">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Unit Load</span>
        <span data-testid={NAV.loadValue} className="num-ticker text-lg font-mono text-zinc-100">
          {load.toFixed(1)}
        </span>
        <span className="text-[10px] text-zinc-500">MW</span>
        <span className="text-[10px] text-zinc-500 font-mono">({loadPct.toFixed(0)}% MCR)</span>
      </div>

      <div className="w-px h-8 bg-[#2A2A2E]" />

      {/* Mode ribbon */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Mode</span>
        <span
          data-testid={NAV.modeValue}
          className="px-2 py-0.5 text-xs font-display uppercase tracking-wider"
          style={{ color: modeColor, border: `1px solid ${modeColor}` }}
        >
          {mode}
        </span>
        <span className="text-[10px] text-zinc-500 font-mono">
          {fmtDuration(state?.mode_duration_sec)}
        </span>
      </div>

      <div className="w-px h-8 bg-[#2A2A2E]" />

      {/* Data quality */}
      <div className="flex items-center gap-2" data-testid={NAV.dqBadge}>
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Data Quality</span>
        <span
          className="text-xs font-mono px-2 py-0.5"
          style={{ color: STATUS_COLOR[dqZone], border: `1px solid ${STATUS_COLOR[dqZone]}` }}
        >
          {dq.toFixed(0)}%
        </span>
      </div>

      <div className="flex-1" />

      {unackHigh > 0 && (
        <div className="text-xs font-display uppercase tracking-widest px-2 py-1 border border-status-red text-status-red alarm-pulse">
          {unackHigh} UNACK&apos;D CRITICAL
        </div>
      )}

      {/* Scenario injector */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Inject Scenario</span>
        <select
          data-testid={NAV.scenarioSelect}
          disabled={pending}
          value={activeScenario}
          onChange={handleChange}
          className="bg-[#141416] border border-[#3F3F46] px-2 py-1 text-xs font-mono text-zinc-200 focus:outline-none focus:border-zinc-400"
        >
          {scenarios.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="text-[10px] text-zinc-600 font-mono">
        {state?.ts ? new Date(state.ts).toLocaleTimeString([], { hour12: false }) : "—"}
      </div>
    </header>
  );
}
