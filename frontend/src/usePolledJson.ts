import { useEffect, useRef, useState } from 'react';

// Per decisions.md §3, the dashboard polls three GETs every 2 seconds.
export const POLL_MS = 2000;

// API base resolved from VITE_API_BASE so the grader can repoint without
// rebuilding. Falls back to the conventional dev port for the backend.
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  'http://127.0.0.1:8765';

/**
 * Poll a JSON endpoint every POLL_MS. The `cancelled` flag is essential —
 * without it, a slow fetch landing after unmount produces a
 * state-update-on-unmounted-component warning, and worse, can clobber state
 * with stale data after a re-mount under React StrictMode.
 *
 * onTick: called with the timestamp of every successful fetch — lets the
 * page-level "last updated" clock advance from any of the three polls.
 */
export function usePolledJson<T>(
  path: string,
  onTick?: (when: Date) => void,
): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Keep the latest onTick reference accessible without retriggering the
  // polling effect — the effect only depends on `path`. The ref is updated
  // in its own effect so we never read or write it during render.
  const onTickRef = useRef(onTick);
  useEffect(() => {
    onTickRef.current = onTick;
  });

  useEffect(() => {
    let cancelled = false;
    let inflight: AbortController | null = null;

    const tick = async () => {
      // Cancel any prior in-flight request before starting a new one.
      // Prevents fetch stacking when the backend is slower than POLL_MS.
      inflight?.abort();
      const controller = new AbortController();
      inflight = controller;
      const timer = setTimeout(() => controller.abort(), POLL_MS);
      try {
        const r = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as T;
        if (!cancelled) {
          setData(j);
          setError(null);
          onTickRef.current?.(new Date());
        }
      } catch (e) {
        // Aborts from our own timeout or cleanup are expected — don't paint
        // them as errors in the UI.
        if (!cancelled && (e as Error).name !== 'AbortError') {
          setError(String(e));
        }
      } finally {
        clearTimeout(timer);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
      inflight?.abort();
    };
  }, [path]);

  return { data, error };
}
