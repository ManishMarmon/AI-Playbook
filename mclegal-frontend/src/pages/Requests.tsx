import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { buildMpactUrl } from "../lib/mpact";
import { SortableTh } from "../components/SortableTh";
import { nextSort, sortRows, type SortState, type SortValue } from "../lib/tableSort";
import { PAGE_BODY_HEIGHT } from "../lib/layout";
import { NDA_DIRECTIONS } from "../lib/ndaTypes";

type RequestRow = {
  request_id: number;
  request_title: string;
  request_status: string;
  process_status: string | null;
  entry_date: string;
  contract_type: string | null;
  business_sector: string | null;
  location: string | null;
  law_firm: string | null;
  attorney_email: string | null;
  party_a: string | null;
  party_b: string | null;
  requestor: string | null;
  amount: number | null;
  notes: string | null;
  vendor_id: number;
  attachment_count: number;
  has_word_redline: boolean;
  word_redline_count: number;
  nda_type: string | null;
  // "scanned" | "not_scanned" — whether this request's Word files have been
  // checked for tracked changes yet. Without it, "no redline" and "not looked
  // at yet" would be indistinguishable in the UI.
  redline_scan_state: string | null;
};

const PAGE_SIZE = 50;

// The six dropdown filters, in render order. Driven off this table rather than
// six near-identical blocks so the cascading-options logic below has exactly
// one place to look up "which row field does this filter constrain".
const SELECT_FILTERS = [
  { key: "contractType", field: "contract_type", id: "filter-contract-type", label: "Contract Type" },
  { key: "businessSector", field: "business_sector", id: "filter-sector", label: "Business Sector" },
  { key: "location", field: "location", id: "filter-location", label: "Location" },
  { key: "lawFirm", field: "law_firm", id: "filter-law-firm", label: "Law Firm" },
  { key: "attorney", field: "attorney_email", id: "filter-attorney", label: "Attorney (email)" },
  { key: "partyA", field: "party_a", id: "filter-party-a", label: "Party A" },
] as const;

type FilterKey = (typeof SELECT_FILTERS)[number]["key"];

// Column key -> the value that column sorts on. Blank/null values are handled
// by the comparator (they stay at the bottom in both directions), so an
// optional CobbleStone field can just return its raw value here.
type SortKey =
  | "request" | "requestId" | "redline" | "contractType" | "sector" | "location" | "partyA"
  | "partyB" | "lawFirm" | "attorney" | "requestor" | "amount" | "status";

const SORT_VALUES: Record<SortKey, (r: RequestRow) => SortValue> = {
  request: (r) => r.request_title || `Request ${r.request_id}`,
  requestId: (r) => r.request_id,
  // Count, not a boolean: descending then ranks the most heavily redlined
  // requests first, which is the reason to sort this column. Never-scanned
  // requests return null so they sort as unknown rather than as zero.
  redline: (r) => (r.redline_scan_state === "scanned" ? r.word_redline_count : null),
  // Sorts on what is displayed, direction included, so the NDAs group by
  // direction within the contract type instead of interleaving. "NDA" still
  // sorts adjacent to "NDA (Mutual)", so every NDA stays together.
  contractType: (r) =>
    r.contract_type && r.nda_type
      ? `${r.contract_type} (${r.nda_type === "Mutual" ? "Mutual" : "One-way"})`
      : r.contract_type,
  sector: (r) => r.business_sector,
  location: (r) => r.location,
  partyA: (r) => r.party_a,
  partyB: (r) => r.party_b,
  lawFirm: (r) => r.law_firm,
  attorney: (r) => r.attorney_email,
  requestor: (r) => r.requestor,
  amount: (r) => r.amount,
  status: (r) => r.process_status || r.request_status,
};

// Widths in px, not percentages, in column order. Percentages divide whatever
// the window gives you, so twelve columns on a laptop meant every one of them
// was squeezed below the width its content needs. These are the widths the
// columns actually want; their sum becomes the table's min-width, so a narrow
// window scrolls the table sideways instead of crushing every column.
const COLUMN_WIDTHS = [210, 110, 95, 135, 155, 110, 175, 175, 155, 200, 150, 120, 155];
const TABLE_MIN_WIDTH = COLUMN_WIDTHS.reduce((a, b) => a + b, 0);

function isRequestRows(data: unknown): data is RequestRow[] {
  return Array.isArray(data);
}

function distinctSorted(rows: RequestRow[], field: keyof RequestRow): string[] {
  const values = new Set<string>();
  for (const r of rows) {
    const v = r[field];
    if (typeof v === "string" && v.trim()) values.add(v);
  }
  return [...values].sort((a, b) => a.localeCompare(b));
}

function formatAmount(amount: number | null): string {
  if (amount == null) return "—";
  return amount.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function Requests({ search }: { search: string }) {
  const resource = useJsonResource<RequestRow[]>("/data/requests_catalog.json", isRequestRows);
  const rows = resource.status === "ready" ? resource.data : [];

  const [contractType, setContractType] = useState("");
  const [businessSector, setBusinessSector] = useState("");
  const [location, setLocation] = useState("");
  const [lawFirm, setLawFirm] = useState("");
  const [attorney, setAttorney] = useState("");
  const [partyA, setPartyA] = useState("");
  const [partyBQuery, setPartyBQuery] = useState("");
  const [requestorQuery, setRequestorQuery] = useState("");
  // Jeff (2026-08-31): flag contracts that have a first-cut redlined Word
  // document so users can filter — e.g. US NDAs — and analyse the ones with
  // redlines separately from those without.
  const [redline, setRedline] = useState("");   // "" | "yes" | "no" | "unscanned"
  const [ndaType, setNdaType] = useState("");
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<SortState<SortKey>>(null);

  const selected: Record<FilterKey, string> = {
    contractType,
    businessSector,
    location,
    lawFirm,
    attorney,
    partyA,
  };
  const setters: Record<FilterKey, (v: string) => void> = {
    contractType: setContractType,
    businessSector: setBusinessSector,
    location: setLocation,
    lawFirm: setLawFirm,
    attorney: setAttorney,
    partyA: setPartyA,
  };

  // One predicate for everything. `except` skips a single dropdown's own
  // constraint, which is what makes each dropdown's option list reflect the
  // OTHER active filters while still letting you change your own selection.
  const matches = useMemo(() => {
    const term = search.trim().toLowerCase();
    const partyBTerm = partyBQuery.trim().toLowerCase();
    const requestorTerm = requestorQuery.trim().toLowerCase();
    return (r: RequestRow, except?: FilterKey) => {
      for (const { key, field } of SELECT_FILTERS) {
        if (key === except) continue;
        const value = selected[key];
        if (value && r[field] !== value) return false;
      }
      if (partyBTerm && !(r.party_b || "").toLowerCase().includes(partyBTerm)) return false;
      if (requestorTerm && !(r.requestor || "").toLowerCase().includes(requestorTerm)) return false;
      if (redline === "yes" && !r.has_word_redline) return false;
      // "no" means confirmed-none, so unscanned requests are excluded from it
      // rather than being counted as having no redline.
      if (redline === "no" && (r.has_word_redline || r.redline_scan_state !== "scanned")) return false;
      if (redline === "unscanned" && r.redline_scan_state === "scanned") return false;
      if (ndaType && r.nda_type !== ndaType) return false;
      if (
        term &&
        !(
          r.request_title?.toLowerCase().includes(term) ||
          r.party_a?.toLowerCase().includes(term) ||
          r.party_b?.toLowerCase().includes(term) ||
          r.requestor?.toLowerCase().includes(term)
        )
      )
        return false;
      return true;
    };
  }, [contractType, businessSector, location, lawFirm, attorney, partyA, partyBQuery, requestorQuery,
      redline, ndaType, search]);

  // Cascading options: "Location" only lists locations that actually exist for
  // the selected sector, and vice versa — a combination that would return zero
  // rows is never offered in the first place.
  const options = useMemo(() => {
    const out = {} as Record<FilterKey, string[]>;
    for (const { key, field } of SELECT_FILTERS) {
      out[key] = distinctSorted(
        rows.filter((r) => matches(r, key)),
        field
      );
    }
    return out;
  }, [rows, matches]);

  const filtered = useMemo(() => rows.filter((r) => matches(r)), [rows, matches]);

  // A selection can go stale when a *different* filter narrows past it (pick a
  // location, then pick a sector that location doesn't appear in). Clear it
  // instead of leaving the table stuck on an empty result with no visible cause.
  useEffect(() => {
    for (const { key } of SELECT_FILTERS) {
      const value = selected[key];
      if (value && !options[key].includes(value)) setters[key]("");
    }
  }, [options]);

  useEffect(() => {
    setPage(0);
  }, [contractType, businessSector, location, lawFirm, attorney, partyA, partyBQuery, requestorQuery,
      redline, ndaType, search, sort]);

  const ordered = useMemo(
    () => sortRows(filtered, sort, SORT_VALUES, (r) => r.request_id),
    [filtered, sort]
  );

  const pageCount = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  const visible = ordered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const onSort = (key: SortKey) => setSort((s) => nextSort(s, key));

  const stats = useMemo(
    () => ({
      total: rows.length,
      sectors: new Set(rows.map((r) => r.business_sector).filter(Boolean)).size,
      lawFirms: new Set(rows.map((r) => r.law_firm).filter(Boolean)).size,
      filtered: filtered.length,
    }),
    [rows, filtered]
  );

  const hasActiveFilters = Boolean(
    contractType || businessSector || location || lawFirm || attorney || partyA || partyBQuery ||
    requestorQuery || redline || ndaType
  );

  function resetFilters() {
    for (const { key } of SELECT_FILTERS) setters[key]("");
    setPartyBQuery("");
    setRequestorQuery("");
    setRedline("");
    setNdaType("");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: PAGE_BODY_HEIGHT }}>
      {/* Reset rides on the title line, which had a screenful of unused
          horizontal space, rather than on a row of its own above the filters. */}
      <div className="between">
        <h1>All Requests</h1>
        <button className="btn sm" disabled={!hasActiveFilters} onClick={resetFilters}>
          Reset filters
        </button>
      </div>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Every CobbleStone contract request, with metadata (contract type, sector, location, law firm,
        attorney, parties, requestor) already returned by the API but not previously surfaced.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading requests..."
          errorLabel="Couldn't load the requests catalog."
        />
      )}

      {resource.status === "ready" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          <div className="grid-4" style={{ gap: 10, marginTop: 10, flex: "none" }}>
            <StatTile compact label="Total Requests" value={stats.total} />
            <StatTile compact label="Business Sectors" value={stats.sectors} />
            <StatTile compact label="Law Firms" value={stats.lawFirms} />
            <StatTile compact label="Matching Filters" value={stats.filtered} />
          </div>

          {/* The "Filters" caption and its own header row were removed: a row of
              labelled dropdowns needs no caption, and on a 642px-tall screen
              that chrome cost a row of actual data. Reset now rides in the grid
              as a final cell, so it takes no extra height. */}
          <div className="card" style={{ padding: 12, marginTop: 10, flex: "none" }}>
            <div className="filters-grid filters-compact" style={{ gap: 8, rowGap: 6 }}>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-contract-type">Contract Type</label>
                <select
                  id="filter-contract-type"
                  className="select"
                  value={contractType}
                  onChange={(e) => setContractType(e.target.value)}
                >
                  <option value="">All</option>
                  {options.contractType.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-sector">Business Sector</label>
                <select
                  id="filter-sector"
                  className="select"
                  value={businessSector}
                  onChange={(e) => setBusinessSector(e.target.value)}
                >
                  <option value="">All</option>
                  {options.businessSector.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-location">Location</label>
                <select
                  id="filter-location"
                  className="select"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                >
                  <option value="">All</option>
                  {options.location.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-law-firm">Law Firm</label>
                <select
                  id="filter-law-firm"
                  className="select"
                  value={lawFirm}
                  onChange={(e) => setLawFirm(e.target.value)}
                >
                  <option value="">All</option>
                  {options.lawFirm.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-attorney">Attorney (email)</label>
                <select
                  id="filter-attorney"
                  className="select"
                  value={attorney}
                  onChange={(e) => setAttorney(e.target.value)}
                >
                  <option value="">All</option>
                  {options.attorney.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-party-a">Party A</label>
                <select
                  id="filter-party-a"
                  className="select"
                  value={partyA}
                  onChange={(e) => setPartyA(e.target.value)}
                >
                  <option value="">All</option>
                  {options.partyA.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-party-b">Party B</label>
                <input
                  id="filter-party-b"
                  className="input"
                  value={partyBQuery}
                  onChange={(e) => setPartyBQuery(e.target.value)}
                  placeholder="Search Party B..."
                />
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-requestor">Requestor</label>
                <input
                  id="filter-requestor"
                  className="input"
                  value={requestorQuery}
                  onChange={(e) => setRequestorQuery(e.target.value)}
                  placeholder="Search requestor..."
                />
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-redline">Word redline</label>
                <select
                  id="filter-redline"
                  className="select"
                  value={redline}
                  onChange={(e) => setRedline(e.target.value)}
                >
                  <option value="">All</option>
                  <option value="yes">Has redline</option>
                  <option value="no">No redline (checked)</option>
                  <option value="unscanned">Not yet checked</option>
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="filter-nda-type">NDA type</label>
                <select
                  id="filter-nda-type"
                  className="select"
                  value={ndaType}
                  onChange={(e) => setNdaType(e.target.value)}
                >
                  <option value="">All</option>
                  {NDA_DIRECTIONS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>

            </div>
          </div>

          <div
            className="card"
            style={{ overflow: "hidden", marginTop: 10, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}
          >
            <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
              <table className="data-table fixed" style={{ minWidth: TABLE_MIN_WIDTH }}>
                <colgroup>
                  {COLUMN_WIDTHS.map((w, i) => (
                    <col key={i} style={{ width: w }} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <SortableTh label="Request" sortKey="request" sort={sort} onSort={onSort} />
                    <SortableTh label="Request #" sortKey="requestId" sort={sort} onSort={onSort} />
                    <SortableTh label="Redline" sortKey="redline" sort={sort} onSort={onSort} />
                    <SortableTh label="Contract Type" sortKey="contractType" sort={sort} onSort={onSort} />
                    <SortableTh label="Business Sector" sortKey="sector" sort={sort} onSort={onSort} />
                    <SortableTh label="Location" sortKey="location" sort={sort} onSort={onSort} />
                    <SortableTh label="Party A" sortKey="partyA" sort={sort} onSort={onSort} />
                    <SortableTh label="Party B" sortKey="partyB" sort={sort} onSort={onSort} />
                    <SortableTh label="Law Firm" sortKey="lawFirm" sort={sort} onSort={onSort} />
                    <SortableTh label="Attorney" sortKey="attorney" sort={sort} onSort={onSort} />
                    <SortableTh label="Requestor" sortKey="requestor" sort={sort} onSort={onSort} />
                    <SortableTh label="Amount" sortKey="amount" sort={sort} onSort={onSort} />
                    <SortableTh label="Status" sortKey="status" sort={sort} onSort={onSort} />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.request_id}>
                      <td>
                        <div className="text-body">{r.request_title || `Request ${r.request_id}`}</div>
                      </td>
                      {/* Its own column, styled as a link. As a grey sub-line
                          under the title with a small ↗ it read as decoration —
                          nobody hovers text they don't think is clickable. */}
                      <td className="text-body-sm">
                        {(() => {
                          const mpactUrl = buildMpactUrl(r.request_id);
                          return mpactUrl ? (
                            <a
                              className="link"
                              href={mpactUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={`Open request ${r.request_id} in mpact (new tab)`}
                            >
                              #{r.request_id}
                              <ExternalLink size={11} style={{ marginLeft: 3, verticalAlign: "baseline" }} />
                            </a>
                          ) : (
                            <span className="muted">#{r.request_id}</span>
                          );
                        })()}
                      </td>
                      <td>
                        {r.has_word_redline ? (
                          <span
                            className="chip good"
                            title={`${r.word_redline_count} redlined Word document(s) with tracked changes`}
                          >
                            {r.word_redline_count > 1 ? `${r.word_redline_count} redlines` : "Redline"}
                          </span>
                        ) : r.redline_scan_state === "scanned" ? (
                          <span className="text-body-xs muted" title="Checked — no tracked changes found">
                            none
                          </span>
                        ) : (
                          <span className="text-body-xs muted" title="Word files not yet checked for tracked changes">
                            —
                          </span>
                        )}
                      </td>
                      {/* Every one of these is `ellip`: one line, full value on
                          hover. Twelve columns cannot all wrap and still leave
                          a table you can scan. */}
                      {/* NDA direction belongs here, not in the Redline column
                          where it used to sit: it describes the CONTRACT, not
                          the tracked changes, and a mutual NDA is a different
                          negotiating instrument from a one-way one. Muted
                          parenthetical rather than plain text so the column
                          still scans as a list of contract types. Full
                          classifier label on hover — "One-way" alone does not
                          say which side Marmon is on. */}
                      <td
                        className="text-body-sm ellip"
                        title={r.nda_type ? `${r.contract_type} — ${r.nda_type}` : r.contract_type || ""}
                      >
                        {r.contract_type || "—"}
                        {r.nda_type && (
                          <span className="muted"> ({r.nda_type === "Mutual" ? "Mutual" : "One-way"})</span>
                        )}
                      </td>
                      <td className="text-body-sm ellip" title={r.business_sector || ""}>{r.business_sector || "—"}</td>
                      <td className="text-body-sm ellip" title={r.location || ""}>{r.location || "—"}</td>
                      <td className="text-body-sm ellip" title={r.party_a || ""}>{r.party_a || "—"}</td>
                      <td className="text-body-sm ellip" title={r.party_b || ""}>{r.party_b || "—"}</td>
                      <td className="text-body-sm ellip" title={r.law_firm || ""}>{r.law_firm || "—"}</td>
                      <td className="text-body-xs muted ellip" title={r.attorney_email || ""}>
                        {r.attorney_email || "—"}
                      </td>
                      <td className="text-body-sm ellip" title={r.requestor || ""}>{r.requestor || "—"}</td>
                      <td className="text-body-sm ellip" title={formatAmount(r.amount)}>{formatAmount(r.amount)}</td>
                      <td className="text-body-xs muted ellip" title={r.process_status || r.request_status || ""}>
                        {r.process_status || r.request_status || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 40 }}>
                No matching requests.
              </div>
            )}
          </div>

          {ordered.length > 0 && (
            <div className="between" style={{ marginTop: 8, flex: "none" }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({ordered.length.toLocaleString()} requests)
              </div>
              <div className="row">
                <button className="btn sm" disabled={page === 0} onClick={() => setPage(0)}>
                  First
                </button>
                <button className="btn sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <button className="btn sm" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
                <button className="btn sm" disabled={page >= pageCount - 1} onClick={() => setPage(pageCount - 1)}>
                  Last
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
