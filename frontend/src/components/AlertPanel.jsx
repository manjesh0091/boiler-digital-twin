import React from "react";
import { STATUS_COLOR, timeShort, fmtDuration } from "@/lib/format";
import { S01 } from "@/constants/testIds";
import { ackAlert, ackAll } from "@/lib/api";

const kindLabel = {
  param: "PARAM",
  safety: "SAFETY",
  composite: "COMPOSITE",
  co: "COMBUSTION",
  CLUSTER: "CROSS-VALIDATION",
  COMBUSTION: "COMBUSTION ALERT",
};

export default function AlertPanel({ alerts = [], compact = false }) {
  const active = alerts.filter((a) => a.active);
  const cleared = alerts.filter((a) => !a.active).slice(0, 8);

  const now = Date.now();
  const dur = (iso) => {
    try {
      return fmtDuration((now - new Date(iso).getTime()) / 1000);
    } catch {
      return "--";
    }
  };

  const handleAck = async (id) => {
    try {
      await ackAlert(id);
    } catch {
      /* noop */
    }
  };
  const handleAckAll = async () => {
    try {
      await ackAll();
    } catch {
      /* noop */
    }
  };

  return (
    <div className="panel h-full flex flex-col" data-testid={S01.alertList}>
      <div className="panel-header">
        <span>Alarm &amp; Event Log</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zinc-500">
            {active.length} active
          </span>
          <button
            data-testid="nav-ack-all"
            onClick={handleAckAll}
            className="text-[10px] uppercase tracking-wider font-display px-2 py-1 border border-[#3F3F46] text-zinc-300 hover:bg-[#22222608]"
          >
            Ack All
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto text-xs">
        {active.length === 0 && (
          <div className="p-4 text-zinc-500 text-xs">
            No active alarms — all parameters within band.
          </div>
        )}
        {active.map((a) => {
          const color = STATUS_COLOR[a.severity] || STATUS_COLOR.amber;
          return (
            <div
              key={a.id}
              className={`px-3 py-2 border-b border-[#22222E] flex items-start gap-2 ${
                !a.acknowledged && a.severity === "red" ? "alarm-pulse" : ""
              }`}
              style={{ borderLeft: `3px solid ${color}` }}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className="font-mono text-[10px] px-1"
                    style={{ color, border: `1px solid ${color}` }}
                  >
                    {a.severity === "red" ? "ERR" : "WRN"}
                  </span>
                  <span className="text-[10px] text-zinc-500 font-display uppercase tracking-wider">
                    {kindLabel[a.kind] || a.kind}
                  </span>
                  {!a.acknowledged && (
                    <span className="text-[9px] text-zinc-500 uppercase">unack&apos;d</span>
                  )}
                </div>
                <div className="text-[12px] mt-1 text-zinc-200 break-words">{a.message}</div>
                <div className="text-[10px] text-zinc-500 mt-1 font-mono">
                  {timeShort(a.first_ts)} · {dur(a.first_ts)}
                </div>
              </div>
              {!a.acknowledged && (
                <button
                  data-testid={S01.ackBtn(a.parameter_key)}
                  onClick={() => handleAck(a.id)}
                  className="text-[10px] uppercase font-display px-2 py-1 border border-[#3F3F46] text-zinc-300 hover:bg-[#22222608] tracking-wider"
                >
                  Ack
                </button>
              )}
            </div>
          );
        })}
        {!compact && cleared.length > 0 && (
          <>
            <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-zinc-600 font-display border-b border-[#22222E]">
              Recently Cleared
            </div>
            {cleared.map((a) => (
              <div key={a.id + a.cleared_ts} className="px-3 py-2 border-b border-[#151517] text-zinc-500">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] px-1 border border-[#3F3F46]">CLR</span>
                  <span className="text-[10px] uppercase tracking-wider">{a.parameter_name}</span>
                </div>
                <div className="text-[11px] mt-0.5">{a.message}</div>
                <div className="text-[10px] text-zinc-600 mt-0.5 font-mono">cleared {timeShort(a.cleared_ts)}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
