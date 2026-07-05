import React from "react";
import { Link } from "react-router-dom";

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#0B0B0C] text-zinc-100 flex flex-col">
      {/* subtle grid backdrop */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none opacity-[0.05]"
        style={{
          backgroundImage:
            "linear-gradient(#E4E4E7 1px, transparent 1px), linear-gradient(90deg, #E4E4E7 1px, transparent 1px)",
          backgroundSize: "80px 80px",
        }}
      />

      <header className="relative z-10 px-8 py-5 border-b border-[#2A2A2E] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 bg-status-green" aria-hidden />
          <div>
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Tkil Industries pvt ltd</div>
            <div className="font-display font-bold text-lg tracking-tight">Boiler Digital Twin</div>
          </div>
        </div>
        <div className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">v0.1 · MVP Prototype</div>
      </header>

      <main className="relative z-10 flex-1 flex items-center justify-center px-8">
        <div className="max-w-3xl w-full">
          <div className="text-[11px] uppercase tracking-[0.25em] text-zinc-500 font-display mb-4">
            <span className="inline-block w-8 h-px bg-zinc-500 align-middle mr-3" />
            Industrial Boiler Monitoring &amp; Combustion Analytics
          </div>
          <h1 className="font-display font-bold text-5xl sm:text-6xl lg:text-7xl tracking-tight leading-[1.02] text-zinc-100">
            Boiler Digital Twin
            <br />
            <span className="text-zinc-500">— MVP Prototype</span>
          </h1>
          <p className="mt-6 text-lg text-zinc-400 max-w-2xl leading-relaxed">
            A control-room preview of the Tkil Industries boiler operating platform. Explore composite performance scoring
            and combustion tuning with live-simulated plant telemetry, exactly as it will behave once wired to the DCS.
          </p>

          <div className="mt-10 flex items-center gap-4">
            <Link
              to="/modules"
              data-testid="landing-enter-btn"
              className="group inline-flex items-center gap-3 px-6 py-3 border-2 border-zinc-100 text-zinc-100 font-display uppercase tracking-widest text-sm hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
            >
              Enter Platform
              <span className="font-mono text-lg transition-transform group-hover:translate-x-1">→</span>
            </Link>
            <div className="text-[11px] font-mono text-zinc-600 uppercase tracking-widest">Simulation Mode · No live DCS connection</div>
          </div>

          <div className="mt-16 grid grid-cols-3 gap-6 border-t border-[#2A2A2E] pt-6">
            <Metric label="Simulated Tags" value="10" unit="channels" />
            <Metric label="Update Rate" value="2" unit="s / tick" />
            <Metric label="Scenarios" value="06" unit="presets" />
          </div>
        </div>
      </main>

      <footer className="relative z-10 px-8 py-4 border-t border-[#2A2A2E] text-[10px] font-mono text-zinc-600 uppercase tracking-widest flex justify-between">
        <span>ISA-101 · Control Room High-Contrast</span>
        <span>Stakeholder Preview Build</span>
      </footer>
    </div>
  );
}

function Metric({ label, value, unit }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="font-mono text-3xl text-zinc-100">{value}</span>
        <span className="text-xs text-zinc-500">{unit}</span>
      </div>
    </div>
  );
}
