import React from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Header from "./Header";
import { useTelemetry } from "@/hooks/useTelemetry";

export const TelemetryContext = React.createContext(null);

export default function Layout() {
  const { state, connected, error } = useTelemetry(2000);

  return (
    <TelemetryContext.Provider value={{ state, connected, error }}>
      <div className="flex h-screen bg-[#0B0B0C] text-zinc-100">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header state={state} />
          <main className="flex-1 overflow-auto p-3">
            {!state && (
              <div className="h-full flex items-center justify-center text-zinc-500 font-mono text-sm">
                {error ? "Connection lost — retrying..." : "Initialising simulation..."}
              </div>
            )}
            {state && <Outlet context={{ state }} />}
          </main>
        </div>
      </div>
    </TelemetryContext.Provider>
  );
}

export function useTelemetryState() {
  const ctx = React.useContext(TelemetryContext);
  return ctx?.state;
}
