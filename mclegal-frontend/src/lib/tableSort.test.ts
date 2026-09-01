import { describe, it, expect } from "vitest";
import { compareValues, nextSort, sortRows, type SortState } from "./tableSort";

describe("compareValues", () => {
  it("orders strings and numbers in the requested direction", () => {
    expect(compareValues("a", "b", "asc")).toBeLessThan(0);
    expect(compareValues("a", "b", "desc")).toBeGreaterThan(0);
    expect(compareValues(10, 2, "asc")).toBeGreaterThan(0);
    expect(compareValues(10, 2, "desc")).toBeLessThan(0);
  });

  it("compares numeric strings by value, not lexically", () => {
    // "#9" vs "#10": a plain string compare puts 9 after 1.
    expect(compareValues("Request 9", "Request 10", "asc")).toBeLessThan(0);
  });

  it("keeps blanks last when ascending", () => {
    expect(compareValues("", "a", "asc")).toBeGreaterThan(0);
    expect(compareValues(null, "a", "asc")).toBeGreaterThan(0);
  });

  it("keeps blanks last when DESCENDING too", () => {
    // The whole point: half these columns are optional CobbleStone fields.
    // A naively flipped comparator fills the top of the table with "—".
    expect(compareValues("", "a", "desc")).toBeGreaterThan(0);
    expect(compareValues(undefined, 5, "desc")).toBeGreaterThan(0);
    expect(compareValues("a", "", "desc")).toBeLessThan(0);
  });

  it("treats two blanks as equal", () => {
    expect(compareValues("", null, "asc")).toBe(0);
  });

  it("does not treat zero as blank", () => {
    // Confidence 0 is a real score, not a missing one.
    expect(compareValues(0, 50, "asc")).toBeLessThan(0);
    expect(compareValues(0, 50, "desc")).toBeGreaterThan(0);
  });
});

describe("nextSort", () => {
  it("starts a fresh column ascending", () => {
    expect(nextSort(null, "file")).toEqual({ key: "file", dir: "asc" });
    expect(nextSort({ key: "request", dir: "desc" }, "file")).toEqual({ key: "file", dir: "asc" });
  });

  it("cycles asc -> desc -> unsorted on the same column", () => {
    const asc: SortState<"file"> = { key: "file", dir: "asc" };
    const desc = nextSort(asc, "file");
    expect(desc).toEqual({ key: "file", dir: "desc" });
    expect(nextSort(desc, "file")).toBeNull();
  });
});

describe("sortRows", () => {
  const rows = [
    { id: 3, name: "Charlie", score: 10 },
    { id: 1, name: "alpha", score: 50 },
    { id: 2, name: "", score: 50 },
  ];
  const values = { name: (r: (typeof rows)[0]) => r.name, score: (r: (typeof rows)[0]) => r.score };

  it("returns the input untouched when unsorted", () => {
    expect(sortRows(rows, null, values, (r) => r.id)).toBe(rows);
  });

  it("does not mutate the source array", () => {
    const before = [...rows];
    sortRows(rows, { key: "name", dir: "asc" }, values, (r) => r.id);
    expect(rows).toEqual(before);
  });

  it("sorts case-insensitively", () => {
    const out = sortRows(rows, { key: "name", dir: "asc" }, values, (r) => r.id);
    expect(out.map((r) => r.id)).toEqual([1, 3, 2]);
  });

  it("breaks ties deterministically so paging is stable", () => {
    // ids 1 and 2 both score 50; the tie-break decides which page each lands on.
    const out = sortRows(rows, { key: "score", dir: "desc" }, values, (r) => r.id);
    expect(out.map((r) => r.id)).toEqual([1, 2, 3]);
  });
});
