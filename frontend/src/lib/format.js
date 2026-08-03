export const STATUS_COLOR = {
  green: "#10B981",
  amber: "#F5A623",
  red: "#EF4444",
  grey: "#71717A",
};

export const ZONE_LABEL = { green: "OK", amber: "WRN", red: "ERR", grey: "N/A" };

export function fmtNumber(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "--";
  return Number(n).toFixed(digits);
}

export function fmtDuration(seconds) {
  if (!seconds || seconds < 0) return "0s";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function timeShort(iso) {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch {
    return "--";
  }
}
