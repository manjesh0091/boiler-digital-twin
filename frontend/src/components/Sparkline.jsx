import React from "react";

/**
 * Tiny inline SVG sparkline. Non-interactive by design (SCADA-style density).
 */
export default function Sparkline({ values = [], width = 100, height = 22, color = "#A1A1AA" }) {
  if (!values || values.length < 2) {
    return <svg width={width} height={height} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (values.length - 1);
  const pts = values
    .map((v, i) => `${(i * step).toFixed(2)},${(height - ((v - min) / range) * height).toFixed(2)}`)
    .join(" ");
  const last = values[values.length - 1];
  const lastX = (values.length - 1) * step;
  const lastY = height - ((last - min) / range) * height;
  return (
    <svg width={width} height={height} className="block">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={pts}
      />
      <circle cx={lastX} cy={lastY} r={1.5} fill={color} />
    </svg>
  );
}
