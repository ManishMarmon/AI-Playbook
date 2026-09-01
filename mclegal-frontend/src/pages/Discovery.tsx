import { useEffect, useMemo, useState } from "react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";
import { Chip, type ChipTone } from "../components/Chip";
import { SortableTh } from "../components/SortableTh";
import { nextSort, sortRows, type SortState, type SortValue } from "../lib/tableSort";
import { PAGE_BODY_HEIGHT } from "../lib/layout";

type CatalogRow = {
  request_id: number;
  request_title: string;
  request_status: string;
  file_name: string;
  file_type: string;
  category: "Redline" | "Draft/Negotiation Copy" | "Likely Executed/Signed" | "Unclassified/Supporting";
  score: number;
  confidence: number;
  is_likely_redline: boolean;
  signals: string;
  detection_methods?: string;
  contract_type?: string | null;
  business_sector?: string | null;
  location?: string | null;
  law_firm?: string | null;
  attorney_email?: string | null;
  party_a?: string | null;
  party_b?: string | null;
  requestor?: string | null;
};

// Everything CobbleStone knows about the request that isn't worth its own
// column. Party A/B used to be columns; they were mostly "—" and cost more
// width than they returned, so they live here now.
function requestTooltip(r: CatalogRow): string {
  return [
    r.contract_type && `Contract type: ${r.contract_type}`,
    r.location && `Location: ${r.location}`,
    r.party_a && `Party A: ${r.party_a}`,
    r.party_b && `Party B: ${r.party_b}`,
    r.law_firm && `Law firm: ${r.law_firm}`,
    r.attorney_email && `Attorney: ${r.attorney_email}`,
    r.requestor && `Requestor: ${r.requestor}`,
  ]
    .filter(Boolean)
    .join("\n");
}

const CHIP_TONE: Record<CatalogRow["category"], ChipTone | undefined> = {
  Redline: "warn",
  "Draft/Negotiation Copy": "info",
  "Likely Executed/Signed": "good",
  "Unclassified/Supporting": undefined,
};

const DETECTION_METHOD_LABELS: Record<string, string> = {
  filename_heuristic: "Filename",
  text_heuristic: "Text",
  email_heuristic: "Email",
  keywords_heuristic: "Keywords",
  extension_heuristic: "Extension",
  track_changes_xml: "Track Changes",
  pdf_annotation: "PDF Annotation",
  legacy_doc_format: "Legacy .doc (unverified)",
};

function detectionMethodLabel(method: string): string {
  return DETECTION_METHOD_LABELS[method] ?? method;
}

function detectionMethods(r: CatalogRow): string[] {
  return (r.detection_methods || "").split(";").filter(Boolean);
}

type SortKey = "request" | "file" | "sector" | "category" | "confidence" | "detected";

// Category sorts by review relevance, not alphabetically: whoever sorts this
// column wants the redlines gathered at the top, and "Redline" alphabetises
// below both "Draft/Negotiation Copy" and "Likely Executed/Signed".
const CATEGORY_RANK: Record<CatalogRow["category"], number> = {
  Redline: 0,
  "Draft/Negotiation Copy": 1,
  "Likely Executed/Signed": 2,
  "Unclassified/Supporting": 3,
};

const SORT_VALUES: Record<SortKey, (r: CatalogRow) => SortValue> = {
  request: (r) => r.request_title || `Request ${r.request_id}`,
  file: (r) => r.file_name,
  sector: (r) => r.business_sector,
  category: (r) => CATEGORY_RANK[r.category] ?? 9,
  confidence: (r) => r.confidence,
  // The joined labels, so sorting groups files that were detected the same way
  // — the reason to sort this column at all.
  detected: (r) => detectionMethods(r).map(detectionMethodLabel).join(", "),
};

const PAGE_SIZE = 25;

function isCatalogRows(data: unknown): data is CatalogRow[] {
  return Array.isArray(data);
}

export default function Discovery({ search }: { search: string }) {
  const resource = useJsonResource<CatalogRow[]>("/data/redline_catalog.json", isCatalogRows);
  const [showAll, setShowAll] = useState(false);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<SortState<SortKey>>(null);

  const rows = resource.status === "ready" ? resource.data : [];

  const stats = useMemo(() => {
    const requests = new Set(rows.map((r) => r.request_id)).size;
    const redlines = rows.filter((r) => r.is_likely_redline).length;
    const highConfidence = rows.filter((r) => r.is_likely_redline && r.confidence >= 50).length;
    return { requests, attachments: rows.length, redlines, highConfidence };
  }, [rows]);

  const filtered = useMemo(() => {
    const byToggle = showAll ? rows : rows.filter((r) => r.is_likely_redline);
    const term = search.trim().toLowerCase();
    if (!term) return byToggle;
    return byToggle.filter(
      (r) =>
        r.request_title?.toLowerCase().includes(term) ||
        r.file_name?.toLowerCase().includes(term) ||
        r.category?.toLowerCase().includes(term)
    );
  }, [rows, showAll, search]);

  const ordered = useMemo(
    () => sortRows(filtered, sort, SORT_VALUES, (r) => r.request_id),
    [filtered, sort]
  );

  useEffect(() => {
    setPage(0);
  }, [showAll, search, sort]);

  const pageCount = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  const visible = ordered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const onSort = (key: SortKey) => setSort((s) => nextSort(s, key));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: PAGE_BODY_HEIGHT }}>
      <h1>Redline Discovery</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Filename + text-signal classification over CobbleStone requests, escalating to a real
        Word track-changes / PDF-annotation check on the downloaded file when the heuristic can't decide.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading catalog..."
          errorLabel="Couldn't load the redline catalog."
        />
      )}

      {resource.status === "ready" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          <div className="grid-4" style={{ marginTop: 16, flex: "none" }}>
            <StatTile label="Requests Scanned" value={stats.requests} />
            <StatTile label="Attachments Found" value={stats.attachments} />
            <StatTile label="Potential Redlines" value={stats.redlines} />
            <StatTile label="High Confidence (≥50)" value={stats.highConfidence} />
          </div>

          <div className="between" style={{ marginTop: 16, marginBottom: 10, flex: "none" }}>
            <h3>Files</h3>
            <div className="toggle-group" role="tablist" aria-label="File filter">
              <button
                role="tab"
                aria-selected={!showAll}
                className={!showAll ? "active" : ""}
                onClick={() => setShowAll(false)}
              >
                Redlines only
              </button>
              <button
                role="tab"
                aria-selected={showAll}
                className={showAll ? "active" : ""}
                onClick={() => setShowAll(true)}
              >
                All attachments
              </button>
            </div>
          </div>

          <div
            className="card"
            style={{ overflow: "hidden", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}
          >
            <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
              {/* Explicit widths, required by `table-layout: fixed` — see the
                  .data-table.fixed note in index.css. Percentages so the table
                  fills a wide window, plus a min-width so a narrow one scrolls
                  sideways rather than squeezing six columns into nothing. */}
              <table className="data-table fixed" style={{ minWidth: 1120 }}>
                <colgroup>
                  <col style={{ width: "22%" }} />
                  <col style={{ width: "24%" }} />
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "14%" }} />
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "21%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <SortableTh label="Request" sortKey="request" sort={sort} onSort={onSort} />
                    <SortableTh label="File" sortKey="file" sort={sort} onSort={onSort} />
                    <SortableTh label="Sector" sortKey="sector" sort={sort} onSort={onSort} />
                    <SortableTh label="Category" sortKey="category" sort={sort} onSort={onSort} />
                    <SortableTh label="Conf." sortKey="confidence" sort={sort} onSort={onSort} />
                    <SortableTh label="Detected Via" sortKey="detected" sort={sort} onSort={onSort} />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r, i) => (
                    <tr key={`${r.request_id}-${r.file_name}-${i}`}>
                      <td title={requestTooltip(r) || undefined}>
                        <div className="text-body">{r.request_title || `Request ${r.request_id}`}</div>
                        <div className="text-body-xs muted">#{r.request_id}</div>
                      </td>
                      <td className="text-body-sm" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.file_name}>
                        {r.file_name}
                      </td>
                      <td className="text-body-sm">{r.business_sector || "—"}</td>
                      <td>
                        <Chip tone={CHIP_TONE[r.category]}>{r.category}</Chip>
                      </td>
                      <td className="text-body-sm">{r.confidence}</td>
                      {/* The raw `signals` string used to be its own column: a
                          truncated semicolon-delimited dump of the same
                          detection run these chips label. It's kept as the
                          tooltip here so nothing is lost. */}
                      <td className="text-body-xs" title={r.signals || undefined}>
                        {r.detection_methods ? (
                          <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                            {detectionMethods(r).map((m) => (
                              <Chip key={m}>{detectionMethodLabel(m)}</Chip>
                            ))}
                          </div>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 40 }}>
                No matching files.
              </div>
            )}
          </div>

          {ordered.length > PAGE_SIZE && (
            <div className="between" style={{ marginTop: 8, flex: "none" }}>
              <div className="text-body-xs muted">
                Page {page + 1} of {pageCount} ({ordered.length.toLocaleString()} files)
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
        </div>
      )}
    </div>
  );
}
