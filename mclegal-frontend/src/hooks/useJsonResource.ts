import { useCallback, useEffect, useState } from "react";

export type JsonResource<T> =
  | { status: "loading"; data: null; error: null; refetch: () => void }
  | { status: "error"; data: null; error: string; refetch: () => void }
  | { status: "ready"; data: T; error: null; refetch: () => void };

/**
 * Fetch + validate a JSON export from /data/*.json. Always checks r.ok (a
 * 404/500 becomes a real "error" state, not a silently-empty "loading"
 * state), and optionally runtime-checks the payload shape via `isValid`
 * before it's trusted as T — schema drift then surfaces as a visible error
 * instead of a blank crash deep in render.
 */
export function useJsonResource<T>(url: string, isValid?: (data: unknown) => data is T): JsonResource<T> {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data: T | null; error: string | null }>({
    status: "loading",
    data: null,
    error: null,
  });

  const refetch = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading", data: null, error: null });

    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load ${url} (HTTP ${r.status})`);
        return r.json();
      })
      .then((data: unknown) => {
        if (cancelled) return;
        if (isValid && !isValid(data)) {
          throw new Error(`${url} response didn't match the expected shape`);
        }
        setState({ status: "ready", data: data as T, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", data: null, error: err instanceof Error ? err.message : String(err) });
      });

    return () => {
      cancelled = true;
    };
  }, [url, attempt]);

  return { ...state, refetch } as JsonResource<T>;
}
