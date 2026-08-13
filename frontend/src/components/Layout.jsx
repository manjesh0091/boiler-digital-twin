import React from "react";
import { Outlet, useLocation, Link } from "react-router-dom";
import Header from "./Header";
import Breadcrumb from "./Breadcrumb";
import { useTelemetry } from "@/hooks/useTelemetry";

export const TelemetryContext = React.createContext(null);

const MODULE_META = {
  "/modules/pai-s01": { id: "PAI-S01", name: "Boiler Operating Dashboard" },
  "/modules/pai-s03": { id: "PAI-S03", name: "Combustion Excess Air Monitor" },
  "/modules/pai-s02": { id: "PAI-S02", name: "Boiler Efficiency Monitoring" },
};

export default function ModuleLayout() {
  const { state, connected, error, refetch } = useTelemetry(2000);
  const location = useLocation();
  const meta = MODULE_META[location.pathname] || { id: "", name: "Module" };

  return (
    <TelemetryContext.Provider value={{ state, connected, error, refetch }}>
      <div className="flex flex-col h-screen bg-[#0B0B0C] text-zinc-100">
        {/* Breadcrumb bar */}
        <div className="h-11 border-b border-[#2A2A2E] px-4 flex items-center justify-between bg-[#0F0F11]">
          <div className="flex items-center gap-3">
            <Link
              to="/modules"
              data-testid="back-to-modules"
              className="font-mono text-lg text-zinc-500 hover:text-zinc-100 leading-none"
              title="Back to Modules"
              aria-label="Back to Modules"
            >
              ←
            </Link>
            <div className="w-px h-5 bg-[#2A2A2E]" />
            <Breadcrumb current={meta.name} moduleId={meta.id} />
          </div>
          <div className="text-[10px] font-mono text-zinc-600 uppercase tracking-widest">
            Tkil Industries pvt ltd — Boiler Digital Twin
          </div>
        </div>

        <Header state={state} refetch={refetch} />

        <main className="flex-1 overflow-auto p-3">
          {!state && (
            <div className="h-full flex items-center justify-center text-zinc-500 font-mono text-sm">
              {error ? "Connection lost — retrying..." : "Initialising simulation..."}
            </div>
          )}
          {state && <Outlet context={{ state }} />}
        </main>
      </div>
    </TelemetryContext.Provider>
  );
}

export function useTelemetryState() {
  const ctx = React.useContext(TelemetryContext);
  return ctx?.state;
}
