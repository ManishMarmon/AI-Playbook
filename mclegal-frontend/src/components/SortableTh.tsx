import type { CSSProperties } from "react";
import type { SortState } from "../lib/tableSort";

function Arrow({ dir, on }: { dir: "up" | "down"; on: boolean }) {
  return (
    <svg width="7" height="4" viewBox="0 0 7 4" className={on ? "on" : undefined} aria-hidden="true">
      <path d={dir === "up" ? "M3.5 0 L7 4 L0 4 Z" : "M3.5 4 L7 0 L0 0 Z"} />
    </svg>
  );
}

/**
 * A `<th>` whose whole label is a sort button. Both arrows are always drawn —
 * the inactive one faint — so every column advertises that it can be sorted
 * instead of only revealing it once clicked.
 */
export function SortableTh<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  style,
}: {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onSort: (key: K) => void;
  style?: CSSProperties;
}) {
  const active = sort?.key === sortKey;
  const dir = active ? sort.dir : undefined;
  return (
    <th
      className="sortable"
      style={style}
      aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
    >
      <button
        type="button"
        className={active ? "th-sort active" : "th-sort"}
        onClick={() => onSort(sortKey)}
        title={`Sort by ${label}`}
      >
        <span>{label}</span>
        <span className="th-arrows">
          <Arrow dir="up" on={dir === "asc"} />
          <Arrow dir="down" on={dir === "desc"} />
        </span>
      </button>
    </th>
  );
}
