import { useCallback, useEffect, useRef, useState } from "react";
import { fetchState } from "@/lib/api";

/**
 * Polls the backend simulation state at a fixed interval and returns the latest snapshot.
 * Keeps last-known state during transient failures so the UI doesn't flicker.
 *
 * Guards against out-of-order responses landing after a fresher one and
 * silently overwriting it with stale data. Real bug this hook used to have:
 * a scenario dropdown selection would occasionally revert right after page
 * load, because the mount-time poll (already in flight) resolved AFTER the
 * fresh refetch() triggered by the user's change, re-applying the OLD
 * scenario. A monotonically increasing request id fixes this generally --
 * a response is only applied if no newer request has already been applied.
 *
 * `refetch()` lets a caller (e.g. after POSTing a scenario change) force an
 * immediate authoritative poll instead of waiting up to `intervalMs` for
 * the next scheduled one.
 */
export function useTelemetry(intervalMs = 2000) {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const timer = useRef(null);
  const requestId = useRef(0);
  const latestApplied = useRef(0);

  const tick = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const data = await fetchState();
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
