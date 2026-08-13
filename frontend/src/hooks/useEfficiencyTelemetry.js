import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEfficiency } from "@/lib/api";

/**
 * Polls /api/efficiency at a fixed interval. Same out-of-order-response
 * guard as useTelemetry.js (monotonic request id, only apply a response if
 * no newer request has already landed) -- deliberately duplicated rather
 * than generalizing that hook, so PAI-S01/S03's already-verified polling
 * behavior can't regress from a change made for this module.
 */
export function useEfficiencyTelemetry(intervalMs = 2000) {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const timer = useRef(null);
  const requestId = useRef(0);
  const latestApplied = useRef(0);

  const tick = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const data = await fetchEfficiency();
      if (id >= latestApplied.current) {
        latestApplied.current = id;
        setState(data);
        setConnected(true);
        setError(null);
      }
    } catch (e) {
      if (id >= latestApplied.current) {
        latestApplied.current = id;
        setError(e);
        setConnected(false);
      }
    }
  }, []);

  useEffect(() => {
    tick();
    timer.current = setInterval(tick, intervalMs);
    return () => clearInterval(timer.current);
  }, [intervalMs, tick]);

  return { state, error, connected, refetch: tick };
}
