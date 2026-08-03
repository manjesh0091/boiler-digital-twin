import React from "react";
import { ZoneChip } from "@/components/StatusChips";
import { S01 } from "@/constants/testIds";

// Cluster status vocabulary ("consistent"/"outlier"/"ambiguous"/"unknown")
// is different from parameter zones ("green"/"amber"/"red") -- this maps
// one onto the other so ZoneChip (the SAME chip the Parameter Grid uses)
// can render it, rather than inventing a second status-badge style.
const STATUS_ZONE = {
  consistent: "green",
  outlier: "red",
  ambiguous: "amber",
  unknown: "grey",
};

export default function CrossValidationPanel({ items = [] }) {
  return (
    <div
      className="panel"
      data-testid={S01.crossValidation}
      style={{ borderTop: "2px solid #3B82F6" }}
    >
      <div className="panel-header">
        <span>Cross-Validation Status</span>
        <span className="text-[10px] font-mono text-zinc-500">
          Cluster 1 — Load-Flow Mass Balance
        </span>
      </div>
      <div className="px-3 pt-2 text-[10px] text-zinc-500">
        Checks relationships BETWEEN parameters (e.g. do Steam Flow-A and
        Steam Flow-B agree with each other and with Feedwater Flow?) against
        a baseline trained on held-out historical data — a different signal
        from each parameter&apos;s own deviation above, not folded into BOI.
      </div>
      <div className="overflow-x-auto mt-1">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-zinc-500 font-display border-b border-[#2A2A2E]">
              <th className="px-3 py-2">Relationship</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Members</th>
              <th className="px-3 py-2">Note</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-3 text-zinc-500 text-xs">
                  No cross-validation data available.
                </td>
              </tr>
            )}
            {items.map((item) => (
              <tr
                key={item.relationship}
                data-testid={S01.crossValidationRow(item.relationship)}
                className="border-b border-[#151517]"
              >
                <td className="px-3 py-2 text-zinc-200">{item.name}</td>
                <td className="px-3 py-2">
                  <ZoneChip zone={STATUS_ZONE[item.status] || "grey"} />
                </td>
                <td className="px-3 py-2 text-[11px] text-zinc-400">
                  {(item.members || []).join(", ")}
                </td>
                <td className="px-3 py-2 text-[11px] text-zinc-500">{item.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
