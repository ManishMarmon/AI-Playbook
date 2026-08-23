import { useEffect, useMemo, useState } from "react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";

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
};

const PAGE_SIZE = 25;

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
  const [page, setPage] = useState(0);

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
  }, [contractType, businessSector, location, lawFirm, attorney, partyA, partyBQuery, requestorQuery, search]);

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
  }, [contractType, businessSector, location, lawFirm, attorney, partyA, partyBQuery, requestorQuery, search]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  const stats = useMemo(
    () => ({
      total: rows.length,
      sectors: new Set(rows.map((r) => r.business_sector).filter(Boolean)).size,
      lawFirms: new Set(rows.map((r) => r.law_firm).filter(Boolean)).size,
      filtered: filtered.length,
    }),
    [rows, filtered]
  );

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 1 PoC</div>
      <h1>All Requests</h1>
      <p className="muted" style={{ marginTop: 6 }}>
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
        <>
          <div className="grid-4" style={{ marginTop: 24 }}>
            <StatTile label="Total Requests" value={stats.total} />
            <StatTile label="Business Sectors" value={stats.sectors} />
            <StatTile label="Law Firms" value={stats.lawFirms} />
            <StatTile label="Matching Filters" value={stats.filtered} />
          </div>

          <div className="card" style={{ padding: 20, marginTop: 20 }}>
            <div className="grid-4" style={{ gap: 12 }}>
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
            </div>
          </div>

          <div className="card" style={{ overflow: "hidden", marginTop: 20 }}>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>Contract Type</th>
                    <th>Business Sector</th>
                    <th>Location</th>
                    <th>Party A</th>
                    <th>Party B</th>
                    <th>Law Firm</th>
                    <th>Attorney</th>
                    <th>Requestor</th>
                    <th>Amount</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.request_id}>
                      <td>
                        <div className="text-body">{r.request_title || `Request ${r.request_id}`}</div>
                        <div className="text-body-xs muted">#{r.request_id}</div>
                      </td>
                      <td className="text-body-sm">{r.contract_type || "—"}</td>
                      <td className="text-body-sm">{r.business_sector || "—"}</td>
                      <td className="text-body-sm">{r.location || "—"}</td>
                      <td className="text-body-sm" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.party_a || ""}>
                        {r.party_a || "—"}
                      </td>
                      <td className="text-body-sm" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.party_b || ""}>
                        {r.party_b || "—"}
                      </td>
                      <td className="text-body-sm">{r.law_firm || "—"}</td>
                      <td className="text-body-xs muted" title={r.attorney_email || ""}>
                        {r.attorney_email || "—"}
                      </td>
                      <td className="text-body-sm">{r.requestor || "—"}</td>
                      <td className="text-body-sm">{formatAmount(r.amount)}</td>
                      <td className="text-body-xs muted">{r.process_status || r.request_status || "—"}</td>
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

          {filtered.length > PAGE_SIZE && (
            <div className="between" style={{ marginTop: 12 }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({filtered.length.toLocaleString()} requests)
              </div>
              <div className="row">
                <button className="btn sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <button className="btn sm" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
