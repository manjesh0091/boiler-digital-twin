import React from "react";
import { STATUS_COLOR } from "@/lib/format";

/**
 * Radial arc gauge for BOI (0–100). Custom SVG for exact colored zones.
 */
export default function BOIGauge({ value = 0, zone = "green", suppressed = false, trend = "flat" }) {
  const size = 240;
  const stroke = 18;
  const cx = size / 2;
  const cy = size / 2 + 16;
  const r = size / 2 - stroke;
  // Arc spans from 200deg to 340deg (140deg sweep) — mapped by fraction
  const startAngle = 200;
  const endAngle = 340;
  const sweep = endAngle - startAngle;

  const polar = (angleDeg, radius) => {
    const a = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a) };
  };

  const arcPath = (a0, a1, radius) => {
    const p0 = polar(a0, radius);
    const p1 = polar(a1, radius);
    const large = a1 - a0 <= 180 ? 0 : 1;
    return `M ${p0.x} ${p0.y} A ${radius} ${radius} 0 ${large} 1 ${p1.x} ${p1.y}`;
  };

  // Zone arcs: 0-65 red, 65-80 amber, 80-100 green
  const angleAt = (v) => startAngle + (Math.max(0, Math.min(100, v)) / 100) * sweep;

  const needleAngle = angleAt(suppressed ? 0 : value);
  const needleEnd = polar(needleAngle, r - 6);
  const needleBase = polar(needleAngle, 8);

  const zoneColor = STATUS_COLOR[zone] || STATUS_COLOR.green;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size - 20} viewBox={`0 0 ${size} ${size}`}>
        {/* Track */}
        <path d={arcPath(startAngle, endAngle, r)} stroke="#2A2A2E" strokeWidth={stroke} fill="none" strokeLinecap="butt" />
        {/* Zones */}
        <path d={arcPath(startAngle, angleAt(65), r)} stroke={STATUS_COLOR.red} strokeWidth={stroke} fill="none" opacity="0.85" />
        <path d={arcPath(angleAt(65), angleAt(80), r)} stroke={STATUS_COLOR.amber} strokeWidth={stroke} fill="none" opacity="0.85" />
        <path d={arcPath(angleAt(80), endAngle, r)} stroke={STATUS_COLOR.green} strokeWidth={stroke} fill="none" opacity="0.85" />

        {/* Tick labels */}
        {[0, 25, 50, 65, 80, 100].map((v) => {
          const p = polar(angleAt(v), r - stroke - 12);
          return (
            <text
              key={v}
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fill="#71717A"
              style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9 }}
            >
              {v}
            </text>
          );
        })}

        {/* Needle */}
        {!suppressed && (
          <>
            <line
              x1={needleBase.x}
              y1={needleBase.y}
              x2={needleEnd.x}
              y2={needleEnd.y}
              stroke={zoneColor}
              strokeWidth="3"
              strokeLinecap="round"
              style={{ transition: "all 400ms ease-out" }}
            />
            <circle cx={cx} cy={cy} r={5} fill="#0B0B0C" stroke={zoneColor} strokeWidth="2" />
          </>
        )}
      </svg>

      <div className="-mt-6 flex flex-col items-center">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Boiler Operating Index</div>
        {suppressed ? (
          <div data-testid="pai-s01-boi-suppressed" className="mt-1 px-2 py-1 border border-status-amber text-status-amber font-display text-xs uppercase tracking-widest">
            BOI Suppressed — Insufficient Data
          </div>
        ) : (
          <div className="flex items-baseline gap-2 mt-1">
            <span
              data-testid="pai-s01-boi-value"
              className="num-ticker text-5xl font-mono font-semibold"
              style={{ color: zoneColor }}
            >
              {value.toFixed(1)}
            </span>
            <span className="text-xs text-zinc-500">/ 100</span>
            <span
              className={`text-xs ml-2 ${trend === "up" ? "text-status-green" : trend === "down" ? "text-status-red" : "text-zinc-500"}`}
              aria-label={`trend ${trend}`}
            >
              {trend === "up" ? "▲" : trend === "down" ? "▼" : "▬"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
