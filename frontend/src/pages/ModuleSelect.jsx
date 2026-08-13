import React from "react";
import { Link } from "react-router-dom";

const MODULES = [
  {
    id: "PAI-S01",
    slug: "pai-s01",
    title: "Boiler Operating KPI Dashboard",
    tagline: "Composite BOI score across 10 operating tags with deviation waterfall, sparklines and persistent alarms.",
    highlights: ["BOI 0–100 gauge", "Parameter grid + trends", "Alarm log with ack"],
    testid: "module-card-pai-s01",
  },
  {
    id: "PAI-S03",
    slug: "pai-s03",
    title: "Combustion Excess Air Monitor",
    tagline: "Real-time O₂/EA tuning against a load-based target band with CO safety and CO–O₂ quadrant guidance.",
    highlights: ["O₂ dial + target band", "CO-O₂ quadrant plot", "Efficiency impact ₹/hr"],
    testid: "module-card-pai-s03",
  },
  {
    id: "PAI-S02",
    slug: "pai-s02",
    title: "Boiler Efficiency Monitoring",
    tagline: "ASME PTC-4-style indirect/heat-loss efficiency calculation with full loss breakdown and Appendix D-4 corrections.",
    highlights: ["HHV efficiency + loss waterfall", "GCV check + D-4 corrections", "Data source / assumptions panel"],
    testid: "module-card-pai-s02",
  },
];

export default function ModuleSelect() {
  return (
    <div className="min-h-screen bg-[#0B0B0C] text-zinc-100 flex flex-col">
      <header className="px-8 py-5 border-b border-[#2A2A2E] flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link
            to="/"
            data-testid="modules-back-home"
            className="text-[11px] font-display uppercase tracking-widest text-zinc-500 hover:text-zinc-200 flex items-center gap-2"
          >
            <span className="font-mono">←</span> Home
          </Link>
          <div className="text-[10px] font-mono text-zinc-600 uppercase tracking-widest">
            Home / <span className="text-zinc-300">Modules</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Tkil Industries pvt ltd</div>
          <div className="font-display font-bold text-sm tracking-tight">Boiler Digital Twin</div>
        </div>
      </header>

      <main className="flex-1 px-8 py-10 max-w-6xl w-full mx-auto">
        <div className="text-[11px] uppercase tracking-[0.25em] text-zinc-500 font-display mb-3">Select a Module</div>
        <h2 className="font-display font-semibold text-3xl tracking-tight text-zinc-100">
          Choose an operating view to enter
        </h2>
        <p className="mt-2 text-zinc-500 max-w-2xl text-sm">
          Each module streams live-simulated telemetry from the shared plant simulator. Data is continuous across screens.
        </p>

        <div className="mt-10 grid grid-cols-1 lg:grid-cols-2 gap-5">
          {MODULES.map((m) => (
            <Link
              key={m.slug}
              to={`/modules/${m.slug}`}
              data-testid={m.testid}
              className="group panel p-6 flex flex-col justify-between hover:border-zinc-300 transition-colors focus:outline-none focus:ring-2 focus:ring-zinc-300"
            >
              <div>
                <div className="flex items-baseline justify-between">
                  <div className="font-mono text-[11px] tracking-widest text-zinc-500">{m.id}</div>
                  <span className="text-[10px] font-mono text-status-green uppercase tracking-widest">Live</span>
                </div>
                <div className="mt-3 font-display text-2xl text-zinc-100 tracking-tight">{m.title}</div>
                <p className="mt-3 text-sm text-zinc-400 leading-relaxed">{m.tagline}</p>

                <ul className="mt-6 space-y-1.5">
                  {m.highlights.map((h) => (
                    <li key={h} className="flex items-center gap-2 text-[12px] text-zinc-300 font-mono">
                      <span className="w-1 h-1 bg-zinc-500" aria-hidden />
                      {h}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-8 pt-4 border-t border-[#2A2A2E] flex items-center justify-between">
                <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">Open module</span>
                <span className="font-mono text-xl text-zinc-500 group-hover:text-zinc-100 group-hover:translate-x-1 transition-all">
                  →
                </span>
              </div>
            </Link>
          ))}
        </div>
      </main>

      <footer className="px-8 py-4 border-t border-[#2A2A2E] text-[10px] font-mono text-zinc-600 uppercase tracking-widest flex justify-between">
        <span>Simulation Mode · No live DCS connection</span>
        <span>v0.1 · MVP Prototype</span>
      </footer>
    </div>
  );
}
