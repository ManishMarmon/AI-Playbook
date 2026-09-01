/**
 * Comparator for click-to-sort data tables.
 *
 * The one rule that isn't obvious: blanks sort last in BOTH directions. Half
 * these columns are optional CobbleStone fields that render as "—", so a plain
 * flipped comparator would fill the top of the table with empty cells the
 * moment you sorted descending — the sort would work and still show nothing
 * worth reading.
 */

export type SortDir = "asc" | "desc";
export type SortState<K extends string> = { key: K; dir: SortDir } | null;

export type SortValue = string | number | null | undefined;

function isBlank(v: SortValue): boolean {
  return v === null || v === undefined || v === "";
}

export function compareValues(a: SortValue, b: SortValue, dir: SortDir): number {
  const [ba, bb] = [isBlank(a), isBlank(b)];
  // Deliberately not multiplied by dir — see the module note.
  if (ba || bb) return ba && bb ? 0 : ba ? 1 : -1;

  const base =
    typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return base * (dir === "asc" ? 1 : -1);
}

/**
 * Click cycle: unsorted -> ascending -> descending -> unsorted. The third
 * click restores the source order rather than trapping the user in a sort they
 * can only leave by reloading.
 */
export function nextSort<K extends string>(current: SortState<K>, key: K): SortState<K> {
  if (current?.key !== key) return { key, dir: "asc" };
  if (current.dir === "asc") return { key, dir: "desc" };
  return null;
}

/**
 * Sorts a copy. `tieBreak` keeps equal rows in a stable, reproducible order
 * across re-renders and paging.
 */
export function sortRows<T, K extends string>(
  rows: T[],
  sort: SortState<K>,
  values: Record<K, (row: T) => SortValue>,
  tieBreak: (row: T) => number | string
): T[] {
  if (!sort) return rows;
  const get = values[sort.key];
  if (!get) return rows;
  return [...rows].sort((x, y) => {
    const c = compareValues(get(x), get(y), sort.dir);
    if (c !== 0) return c;
    const [tx, ty] = [tieBreak(x), tieBreak(y)];
    return typeof tx === "number" && typeof ty === "number"
      ? tx - ty
      : String(tx).localeCompare(String(ty));
  });
}
