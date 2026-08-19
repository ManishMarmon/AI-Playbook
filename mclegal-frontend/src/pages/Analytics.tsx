import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { StatTile } from "../components/StatTile";

type Operational = {
  requests_scanned: number;
  attachments_found: number;
  potential_redlines: number;
  confirmed_redlines: number;
  extraction_failures: number;
  successfully_processed: number;
};

type ClauseCount = { clause_name: string; count: number };
type CustomerActivity = { vendor: string; requests_negotiated: number; findings: number };
type HighRiskNegotiation = { request_id: number; request_title: string | null; vendor: string | null; count: number };

type BusinessInsights = {
  most_negotiated_clauses: ClauseCount[];
  top_customers_by_negotiation_activity: CustomerActivity[];
  average_revisions_per_contract: number;
  high_risk_negotiations: HighRiskNegotiation[];
};

type AnalyticsData = { operational: Operational; business_insights: BusinessInsights };

function isAnalyticsData(data: unknown): data is AnalyticsData {
  if (!data || typeof data !== "object") return false;
  const d = data as Record<string, unknown>;
  return typeof d.operational === "object" && d.operational !== null && typeof d.business_insights === "object" && d.business_insights !== null;
}

export default function Analytics() {
  const resource = useJsonResource<AnalyticsData>("/data/analytics.json", isAnalyticsData);
  const data = resource.status === "ready" ? resource.data : null;

  return (
    <div>
      <div className="eyebrow">McLegal · Phase 6</div>
      <h1>Reporting &amp; Analytics</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Operational metrics and business insights rolled up from the discovery, pairing, and
        clause-tagging phases.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading analytics..."
          errorLabel="Couldn't load analytics. If this is a fresh checkout, run run_analytics.py first."
        />
      )}

      {data && (
        <>
          <h3 style={{ marginTop: 28, marginBottom: 12 }}>Operational metrics</h3>
          <div className="grid-4" style={{ gap: 16 }}>
            <StatTile label="Requests scanned" value={data.operational.requests_scanned} />
            <StatTile label="Attachments found" value={data.operational.attachments_found} />
            <StatTile label="Potential redlines" value={data.operational.potential_redlines} />
            <StatTile label="Confirmed redlines" value={data.operational.confirmed_redlines} tone="good" />
            <StatTile label="Extraction failures" value={data.operational.extraction_failures} tone="bad" />
            <StatTile label="Successfully processed" value={data.operational.successfully_processed} tone="good" />
            <StatTile
              label="Avg. revisions per contract"
              value={data.business_insights.average_revisions_per_contract}
            />
          </div>

          <h3 style={{ marginTop: 32, marginBottom: 12 }}>Most negotiated clauses</h3>
          <div className="card" style={{ padding: 20 }}>
            <BarList
              rows={data.business_insights.most_negotiated_clauses.map((c) => ({
                label: c.clause_name,
                value: c.count,
              }))}
              emptyLabel="No confirmed findings yet."
            />
          </div>

          <h3 style={{ marginTop: 32, marginBottom: 12 }}>Top customers by negotiation activity</h3>
          <div className="card" style={{ padding: 20 }}>
            <BarList
              rows={data.business_insights.top_customers_by_negotiation_activity.map((c) => ({
                label: c.vendor,
                value: c.findings,
                sublabel: `${c.requests_negotiated} request${c.requests_negotiated === 1 ? "" : "s"}`,
              }))}
              emptyLabel="No confirmed findings yet."
            />
          </div>

          <h3 style={{ marginTop: 32, marginBottom: 12 }}>High-risk negotiations</h3>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>Vendor</th>
                    <th style={{ textAlign: "right" }}>High-significance findings</th>
                  </tr>
                </thead>
                <tbody>
                  {data.business_insights.high_risk_negotiations.map((r) => (
                    <tr key={r.request_id}>
                      <td
                        style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={r.request_title ?? undefined}
                      >
                        #{r.request_id} {r.request_title ? `· ${r.request_title}` : ""}
                      </td>
                      <td
                        style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={r.vendor ?? undefined}
                      >
                        {r.vendor || "—"}
                      </td>
                      <td style={{ textAlign: "right" }} className="mono">
                        {r.count}
                      </td>
                    </tr>
                  ))}
                  {data.business_insights.high_risk_negotiations.length === 0 && (
                    <tr>
                      <td colSpan={3} className="muted" style={{ textAlign: "center", padding: 24 }}>
                        No high-significance confirmed findings yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function BarList({
  rows,
  emptyLabel,
}: {
  rows: { label: string; value: number; sublabel?: string }[];
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return <div className="muted text-body-sm">{emptyLabel}</div>;
  }
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {rows.map((r) => (
        <div key={r.label}>
          <div className="between" style={{ marginBottom: 6 }}>
            <span className="text-body-sm font-medium">
              {r.label}
              {r.sublabel && <span className="muted text-body-xs"> · {r.sublabel}</span>}
            </span>
            <span className="text-body-sm mono">{r.value.toLocaleString()}</span>
          </div>
          <div style={{ height: 10, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${Math.max((r.value / max) * 100, 3)}%`,
                background: "var(--ink)",
                borderRadius: 999,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
