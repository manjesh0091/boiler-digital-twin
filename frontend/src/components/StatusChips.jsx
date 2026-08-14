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

// "real" is intentionally absent -- no chip shown, same convention as
// Module 1's parameter grid (a trustworthy value gets no badge at all).
const DATA_SOURCE_LABEL = {
  unverified: "UNVERIFIED",
  stale: "STALE",
  simulated: "SIMULATED",
  partial: "PARTIAL",
  derived_estimate: "ESTIMATED",
  static_config: "ASSUMED",
  // Distinct from every state above: not a blocked/uncertain REAL value --
  // there is no formula computing this at all (see decisions.md, Phase C).
  unavailable_no_formula: "NO FORMULA",
  // A real value from a plant engineering document (fuel.*, refuse.*
  // distribution/unburned-carbon, ambient.*, gcv_check.*, 2026-08-13) --
  // deliberately distinct from static_config/"ASSUMED" (a generic Awes/
  // library engineering default with no plant-specific override). A
  // reader should be able to tell "confirmed plant number" apart from
  // "generic placeholder pending confirmation" at a glance -- see
  // decisions.md #47.
  documented: "DOCUMENTED",
};

// Only "documented" gets a distinct (green) treatment -- it's the one
// state here that means "confirmed real data," not "blocked/uncertain/
// generic default." Every other chip keeps the shared neutral grey style
// unchanged, so no existing chip anywhere in the app changes appearance.
const DATA_SOURCE_COLOR = {
  documented: STATUS_COLOR.green,
};

export function DataSourceChip({ dataSource }) {
  const label = DATA_SOURCE_LABEL[dataSource];
  if (!label) return null;
  const color = DATA_SOURCE_COLOR[dataSource];
  return (
    <span
      className="font-mono text-[9px] px-1 py-0.5 uppercase tracking-wider"
      style={{ color: color || "#71717A", border: `1px solid ${color || "#3F3F46"}` }}
    >
      {label}
    </span>
  );
}
