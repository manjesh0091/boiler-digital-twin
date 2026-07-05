import React from "react";
import { STATUS_COLOR } from "@/lib/format";

/**
 * Real-time O₂ dial with a shaded green target band.
 */
export default function O2Gauge({ value = 0, target = 4, bandLow = 3, bandHigh = 6, max = 12 }) {
  const size = 260;
  const stroke = 20;
  const cx = size / 2;
  const cy = size / 2 + 20;
  const r = size / 2 - stroke;
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

  const angleAt = (v) => startAngle + (Math.max(0, Math.min(max, v)) / max) * sweep;

  let zoneColor = STATUS_COLOR.green;
  if (value < bandLow - 0.5 || value > bandHigh + 1.5) zoneColor = STATUS_COLOR.red;
  else if (value < bandLow || value > bandHigh) zoneColor = STATUS_COLOR.amber;

  const needleAngle = angleAt(value);
  const needleEnd = polar(needleAngle, r - 6);
  const targetAngle = angleAt(target);
  const targetTick = polar(targetAngle, r + stroke / 2 + 2);
  const targetTickIn = polar(targetAngle, r - stroke / 2 - 2);

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size - 10} viewBox={`0 0 ${size} ${size}`}>
        <path d={arcPath(startAngle, endAngle, r)} stroke="#2A2A2E" strokeWidth={stroke} fill="none" />
        {/* Target band (green shaded) */}
        <path d={arcPath(angleAt(bandLow), angleAt(bandHigh), r)} stroke={STATUS_COLOR.green} strokeWidth={stroke} fill="none" opacity="0.55" />
        {/* Extreme zones */}
        <path d={arcPath(startAngle, angleAt(bandLow), r)} stroke={STATUS_COLOR.amber} strokeWidth={stroke} fill="none" opacity="0.35" />
        <path d={arcPath(angleAt(bandHigh), endAngle, r)} stroke={STATUS_COLOR.amber} strokeWidth={stroke} fill="none" opacity="0.35" />

        {/* Target tick */}
        <line x1={targetTick.x} y1={targetTick.y} x2={targetTickIn.x} y2={targetTickIn.y} stroke="#E4E4E7" strokeWidth="2" />

        {/* Numeric ticks */}
        {[0, 2, 4, 6, 8, 10, 12].map((v) => {
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
        <line
          x1={cx}
          y1={cy}
          x2={needleEnd.x}
          y2={needleEnd.y}
          stroke={zoneColor}
          strokeWidth="3"
          strokeLinecap="round"
          style={{ transition: "all 400ms ease-out" }}
        />
        <circle cx={cx} cy={cy} r={6} fill="#0B0B0C" stroke={zoneColor} strokeWidth="2" />
      </svg>
      <div className="-mt-6 flex flex-col items-center">
        <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-display">Flue Gas O₂</div>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="num-ticker text-4xl font-mono font-semibold" style={{ color: zoneColor }}>{value.toFixed(2)}</span>
          <span className="text-xs text-zinc-500">% vol</span>
        </div>
        <div className="text-[10px] text-zinc-500 mt-1 font-mono">TARGET {target.toFixed(1)} · BAND {bandLow.toFixed(1)}–{bandHigh.toFixed(1)}</div>
      </div>
    </div>
  );
}
