import React from "react";
import { STATUS_COLOR, ZONE_LABEL } from "@/lib/format";

// Shared status-chip visual pattern -- reused by the Parameter Grid
// (BoilerDashboard.jsx) and the Cross-Validation panel
// (CrossValidationPanel.jsx) so both use the exact same chip look
// (no fill, 1px border + matching text color, font-mono uppercase label)
// rather than each inventing its own status-badge style.
export function ZoneChip({ zone }) {
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

const DATA_SOURCE_LABEL = { unverified: "UNVERIFIED", stale: "STALE" };

export function DataSourceChip({ dataSource }) {
  const label = DATA_SOURCE_LABEL[dataSource];
  if (!label) return null;
  return (
    <span
      className="font-mono text-[9px] px-1 py-0.5 uppercase tracking-wider text-zinc-500"
      style={{ border: "1px solid #3F3F46" }}
    >
      {label}
    </span>
  );
}
