import { useMemo, useState } from "react";
import { Download, Eye, EyeOff, AlertTriangle, ShieldCheck } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { Chip } from "../components/Chip";
import { isPlaybookManifest, type PlaybookMeta } from "../lib/playbooks";
import { renderPlaybookDocx, downloadBlob, type PlaybookRule } from "../lib/renderPlaybookDocx";

const ALL = "All";

async function fetchRules(file: string): Promise<PlaybookRule[]> {
  const res = await fetch(`/playbooks/${file}`);
  if (!res.ok) throw new Error(`Failed to load /playbooks/${file} (HTTP ${res.status})`);
  return res.json();
}

export default function Playbooks() {
  const resource = useJsonResource<PlaybookMeta[]>("/playbooks/manifest.json", isPlaybookManifest);
  const [contractType, setContractType] = useState(ALL);
  const [jurisdiction, setJurisdiction] = useState(ALL);
  const [sector, setSector] = useState(ALL);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const playbooks = resource.status === "ready" ? resource.data : [];

  const { contractTypes, jurisdictions, sectors } = useMemo(() => {
    const ct = new Set<string>();
    const j = new Set<string>();
    const s = new Set<string>();
    for (const p of playbooks) {
      p.contractTypes.forEach((c) => ct.add(c));
      if (p.jurisdiction) j.add(p.jurisdiction);
      (p.businessSectors ?? []).forEach((b) => s.add(b));
    }
    return {
      contractTypes: Array.from(ct).sort(),
      jurisdictions: Array.from(j).sort(),
      sectors: Array.from(s).sort(),
    };
  }, [playbooks]);

  const visible = useMemo(
    () =>
      playbooks.filter(
        (p) =>
          (contractType === ALL || p.contractTypes.includes(contractType)) &&
          (jurisdiction === ALL || p.jurisdiction === jurisdiction) &&
          (sector === ALL || (p.businessSectors ?? []).includes(sector))
      ),
    [playbooks, contractType, jurisdiction, sector]
  );

  async function handleDownload(p: PlaybookMeta) {
    setDownloadError(null);
    setDownloading(p.id);
    try {
      const rules = await fetchRules(p.file);
      const blob = await renderPlaybookDocx(p, rules);
      downloadBlob(blob, `${p.id}-playbook.docx`);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div>
      <div className="eyebrow">McLegal · Golden Rules Playbooks</div>
      <h1>Playbooks</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Every Golden Rules playbook we've built — one per contract-type/jurisdiction combination.
        AI-derived first drafts are clearly marked; only attorney-reviewed playbooks should be
        treated as an approved negotiating position.
      </p>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading playbooks..."
          errorLabel="Couldn't load the playbook manifest."
        />
      )}

      {resource.status === "ready" && (
        <>
          <div className="row" style={{ gap: 10, marginTop: 20, flexWrap: "wrap" }}>
            <FilterSelect label="Contract type" value={contractType} options={contractTypes} onChange={setContractType} />
            <FilterSelect label="Jurisdiction" value={jurisdiction} options={jurisdictions} onChange={setJurisdiction} />
            <FilterSelect label="Business sector" value={sector} options={sectors} onChange={setSector} />
          </div>

          {downloadError && (
            <div className="text-body-xs" style={{ marginTop: 12, color: "var(--bad)" }}>
              {downloadError}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 20 }}>
            {visible.map((p) => (
              <PlaybookCard
                key={p.id}
                playbook={p}
                expanded={expanded === p.id}
                onToggleExpand={() => setExpanded(expanded === p.id ? null : p.id)}
                onDownload={() => handleDownload(p)}
                downloading={downloading === p.id}
              />
            ))}
            {visible.length === 0 && (
              <div className="placeholder" style={{ padding: 32 }}>
                No playbooks match these filters.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="text-body-xs muted" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={ALL}>All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function PlaybookCard({
  playbook,
  expanded,
  onToggleExpand,
  onDownload,
  downloading,
}: {
  playbook: PlaybookMeta;
  expanded: boolean;
  onToggleExpand: () => void;
  onDownload: () => void;
  downloading: boolean;
}) {
  const isDraft = playbook.status !== "attorney_reviewed";

  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="between">
        <div>
          <div className="row" style={{ gap: 8 }}>
            <div className="text-body-sm" style={{ fontWeight: 600 }}>
              {playbook.label}
            </div>
            {isDraft ? (
              <span className="row text-body-xs" style={{ color: "var(--bad)" }}>
                <AlertTriangle size={12} /> AI draft — pending attorney review
              </span>
            ) : (
              <span className="row text-body-xs" style={{ color: "var(--good)" }}>
                <ShieldCheck size={12} /> Attorney reviewed
              </span>
            )}
          </div>
          <div className="text-body-xs muted" style={{ marginTop: 4 }}>
            {playbook.jurisdiction ? `${playbook.jurisdiction} · ` : ""}
            {(playbook.businessSectors ?? []).join(", ")}
            {playbook.contractTypes.length ? ` · ${playbook.contractTypes.join(", ")}` : ""}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={onToggleExpand}>
            {expanded ? <EyeOff size={14} /> : <Eye size={14} />}
            {expanded ? "Hide preview" : "Preview"}
          </button>
          <button className="btn sm" onClick={onDownload} disabled={downloading}>
            <Download size={14} />
            {downloading ? "Preparing..." : "Download Word"}
          </button>
        </div>
      </div>

      {expanded && <PlaybookPreview file={playbook.file} />}
    </div>
  );
}

function PlaybookPreview({ file }: { file: string }) {
  const resource = useJsonResource<PlaybookRule[]>(`/playbooks/${file}`, (d): d is PlaybookRule[] => Array.isArray(d));

  if (resource.status !== "ready") {
    return (
      <ResourceStatus
        status={resource.status}
        error={resource.error}
        onRetry={resource.refetch}
        loadingLabel="Loading rules..."
        errorLabel="Couldn't load this playbook's rules."
      />
    );
  }

  const categories = Array.from(new Set(resource.data.map((r) => r.category)));

  return (
    <div className="divider-parent" style={{ marginTop: 12 }}>
      <div className="divider" />
      {categories.map((category) => (
        <div key={category} style={{ marginTop: 14 }}>
          <div className="text-label muted">{category}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
            {resource.data
              .filter((r) => r.category === category)
              .map((r) => (
                <PreviewRuleRow key={r.rule_id} rule={r} />
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function PreviewRuleRow({ rule }: { rule: PlaybookRule }) {
  return (
    <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
      <div className="row" style={{ gap: 8 }}>
        <Chip tone="info">{rule.rule_id}</Chip>
        <span className="text-body-xs muted">{rule.priority}</span>
      </div>
      <div className="text-body-sm" style={{ fontWeight: 600, marginTop: 4 }}>
        {rule.title}
      </div>
      <div className="text-body-xs muted" style={{ marginTop: 2 }}>
        Applies to: {rule.applies_to}
      </div>
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Required:</strong> {rule.required}
      </div>
      {rule.confidence_note && (
        <div className="text-body-xs muted" style={{ marginTop: 4, fontStyle: "italic" }}>
          Evidence basis: {rule.confidence_note}
        </div>
      )}
    </div>
  );
}
