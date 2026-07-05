import { useEffect, useRef, useState } from "react";
import { fetchState } from "@/lib/api";

/**
 * Polls the backend simulation state at a fixed interval and returns the latest snapshot.
 * Keeps last-known state during transient failures so the UI doesn't flicker.
 */
export function useTelemetry(intervalMs = 2000) {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const timer = useRef(null);
  const busy = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      if (busy.current) return;
      busy.current = true;
      try {
        const data = await fetchState();
        if (!cancelled) {
          setState(data);
          setConnected(true);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e);
          setConnected(false);
        }
      } finally {
        busy.current = false;
      }
    }
    tick();
    timer.current = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer.current);
    };
  }, [intervalMs]);

  return { state, error, connected };
}
