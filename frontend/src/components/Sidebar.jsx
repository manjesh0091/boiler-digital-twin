import React from "react";
import { NavLink } from "react-router-dom";
import { NAV } from "@/constants/testIds";

const items = [
  { to: "/pai-s01", id: "PAI-S01", name: "Boiler Operating Dashboard", testid: NAV.linkS01 },
  { to: "/pai-s03", id: "PAI-S03", name: "Combustion Excess Air Monitor", testid: NAV.linkS03 },
];

export default function Sidebar() {
  return (
    <aside
      data-testid={NAV.sidebar}
      className="w-64 shrink-0 border-r border-[#2A2A2E] bg-[#0F0F11] flex flex-col"
    >
      <div className="px-4 py-4 border-b border-[#2A2A2E]">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Tkil Industries pvt ltd</div>
        <div className="mt-1 font-display font-bold text-lg tracking-tight text-zinc-100">Boiler Digital Twin</div>
        <div className="text-[10px] text-zinc-600 mt-0.5 font-mono">v0.1 · Prototype</div>
      </div>

      <nav className="flex-1 py-2">
        <div className="px-4 py-2 text-[10px] uppercase tracking-widest text-zinc-600 font-display">Modules</div>
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            data-testid={it.testid}
            className={({ isActive }) =>
              `flex flex-col px-4 py-3 border-l-2 text-sm transition-colors ${
                isActive
                  ? "border-l-zinc-100 bg-[#141416] text-zinc-100"
                  : "border-l-transparent text-zinc-400 hover:text-zinc-200 hover:bg-[#141416]"
              }`
            }
          >
            <span className="font-mono text-[10px] text-zinc-500">{it.id}</span>
            <span className="font-display">{it.name}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-3 border-t border-[#2A2A2E] text-[10px] text-zinc-600 font-mono">
        Simulation Mode<br />
        No live DCS connection
      </div>
    </aside>
  );
}
