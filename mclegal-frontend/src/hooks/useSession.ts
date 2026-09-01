import { useSyncExternalStore } from "react";

/**
 * Placeholder session. There is no authentication behind this yet — it records
 * only that someone clicked through the sign-in screen, so the shell has a
 * signed-in/signed-out state to build against and Logout has something real to
 * end. Replace `signIn` with the SSO callback when identity is wired up; every
 * consumer of `useSession` keeps working.
 *
 * An external store rather than context: the topbar menu needs to sign out and
 * the app shell needs to react, and threading a provider through for one
 * boolean is more plumbing than the state deserves.
 */

const STORAGE_KEY = "mclegal-session";

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "active";
  } catch {
    // Private browsing / locked-down policy: treat as signed out.
    return false;
  }
}

let snapshot = read();
const listeners = new Set<() => void>();

function emit() {
  snapshot = read();
  for (const l of listeners) l();
}

export function signIn() {
  try {
    localStorage.setItem(STORAGE_KEY, "active");
  } catch {
    // Falls back to a session that lasts until reload, which is still usable.
  }
  snapshot = true;
  for (const l of listeners) l();
}

export function signOut() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing to clear */
  }
  snapshot = false;
  for (const l of listeners) l();
}

export function useSession(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => {
        listeners.delete(cb);
      };
    },
    () => snapshot,
    () => false
  );
}

export { emit as refreshSession };
