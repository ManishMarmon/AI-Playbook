import { useMemo, useState } from "react";
import { Download, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { Chip, type ChipTone } from "../components/Chip";
import { isPlaybookManifest, type PlaybookMeta } from "../lib/playbooks";
import {
  renderPlaybookDocx,
  downloadBlob,
  isMarmonPreferredPosition,
  basisDisplayLabel,
  NO_LANGUAGE_TEXT,
  type PlaybookRule,
} from "../lib/renderPlaybookDocx";

const PRIORITY_TONE: Record<string, ChipTone | undefined> = {
  "MUST PRESS": "bad",
  PRESS: "warn",
  MANAGE: "info",
  "ACCEPT+NOTE": undefined,
};

const ALL = "All";

async function fetchRules(file: string): Promise<PlaybookRule[]> {
  const res = await fetch(`/playbooks/${file}`);
  if (!res.ok) throw new Error(`Failed to load /playbooks/${file} (HTTP ${res.status})`);
  return res.json();
}

// State for the "opt into suggested rules" prompt shown before a download
// that has any to offer — held separately from the "just download" path so
// a playbook with no suggested rules keeps today's one-click behavior.
type SuggestedPrompt = {
  playbook: PlaybookMeta;
  mainRules: PlaybookRule[];
  suggested: PlaybookRule[];
};

export default function Playbooks() {
  const resource = useJsonResource<PlaybookMeta[]>("/playbooks/manifest.json", isPlaybookManifest);
  const [contractType, setContractType] = useState(ALL);
  const [jurisdiction, setJurisdiction] = useState(ALL);
  const [sector, setSector] = useState(ALL);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [suggestedPrompt, setSuggestedPrompt] = useState<SuggestedPrompt | null>(null);

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

  const hasActiveFilters = contractType !== ALL || jurisdiction !== ALL || sector !== ALL;

  function resetFilters() {
    setContractType(ALL);
    setJurisdiction(ALL);
    setSector(ALL);
  }

  async function handleDownload(p: PlaybookMeta) {
    setDownloadError(null);
    setDownloading(p.id);
    try {
      const rules = await fetchRules(p.file);
      const suggested = p.suggestedRulesFile ? await fetchRules(p.suggestedRulesFile) : [];
      if (suggested.length > 0) {
        setSuggestedPrompt({ playbook: p, mainRules: rules, suggested });
      } else {
        await downloadPlaybook(p, rules, []);
      }
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
    }
  }

  async function downloadPlaybook(p: PlaybookMeta, rules: PlaybookRule[], optionalRules: PlaybookRule[]) {
    const blob = await renderPlaybookDocx(p, rules, optionalRules);
    downloadBlob(blob, `${p.id}-playbook.docx`);
  }

  async function handleConfirmSuggested(selected: PlaybookRule[]) {
    if (!suggestedPrompt) return;
    setDownloadError(null);
    setDownloading(suggestedPrompt.playbook.id);
    try {
      await downloadPlaybook(suggestedPrompt.playbook, suggestedPrompt.mainRules, selected);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
      setSuggestedPrompt(null);
    }
  }

  return (
    <div>
      <h1>Playbooks</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Every Golden Rules playbook we've built — one per contract-type/jurisdiction combination,
        mined from the tracked changes in real negotiated contracts.
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
          <div className="card" style={{ padding: 20, marginTop: 20 }}>
            <div className="between" style={{ marginBottom: 12 }}>
              <span className="text-body-xs muted">Filters</span>
              <button className="btn sm" disabled={!hasActiveFilters} onClick={resetFilters}>
                Reset filters
              </button>
            </div>
            <div className="grid-4" style={{ gap: 12 }}>
              <FilterSelect label="Contract type" value={contractType} options={contractTypes} onChange={setContractType} />
              <FilterSelect label="Jurisdiction" value={jurisdiction} options={jurisdictions} onChange={setJurisdiction} />
              <FilterSelect label="Business sector" value={sector} options={sectors} onChange={setSector} />
            </div>
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

      {suggestedPrompt && (
        <SuggestedRulesModal
          prompt={suggestedPrompt}
          downloading={downloading === suggestedPrompt.playbook.id}
          onConfirm={handleConfirmSuggested}
          onSkip={() => handleConfirmSuggested([])}
          onCancel={() => setSuggestedPrompt(null)}
        />
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
  const id = `playbook-filter-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="field" style={{ marginBottom: 0 }}>
      <label htmlFor={id}>{label}</label>
      <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={ALL}>All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
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
            {/* Positive badge only. An unreviewed playbook shows no badge
                rather than a red "pending attorney review" warning — the
                status is still in the manifest and still stated in the
                exported Word document's hand-off section, which is where the
                reviewing attorney reads it. */}
            {!isDraft && (
              <span className="row text-body-xs" style={{ color: "var(--good)" }}>
                <ShieldCheck size={12} /> Attorney reviewed
              </span>
            )}
          </div>
          <div className="text-body-xs muted" style={{ marginTop: 4 }}>
            {[
              playbook.jurisdiction,
              (playbook.businessSectors ?? []).join(", ") || null,
              playbook.contractTypes.length ? playbook.contractTypes.join(", ") : null,
            ]
              .filter(Boolean)
              .join(" · ")}
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

// Shown before download only when the playbook has suggested (below
// evidence-threshold) rules to offer — a plain one-click download for
// playbooks with none, same as before this existed. Nothing checked by
// default: opting in is a deliberate choice, not a default.
function SuggestedRulesModal({
  prompt,
  downloading,
  onConfirm,
  onSkip,
  onCancel,
}: {
  prompt: SuggestedPrompt;
  downloading: boolean;
  onConfirm: (selected: PlaybookRule[]) => void;
  onSkip: () => void;
  onCancel: () => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());

  function toggle(ruleId: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(ruleId)) next.delete(ruleId);
      else next.add(ruleId);
      return next;
    });
  }

  const selectedRules = prompt.suggested.filter((r) => checked.has(r.rule_id));

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onCancel}
    >
      <div
        className="card"
        style={{ padding: 24, maxWidth: 640, width: "90%", maxHeight: "80vh", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="between" style={{ flex: "none" }}>
          <h2 style={{ margin: 0 }}>Add any suggested rules?</h2>
          <button className="btn-icon" onClick={onCancel} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted text-body-sm" style={{ marginTop: 8, flex: "none" }}>
          {prompt.playbook.label} has {prompt.suggested.length} suggested rule
          {prompt.suggested.length === 1 ? "" : "s"} — real patterns that didn't yet have enough evidence to join
          the main playbook. Check any you want included; they'll be added under an "Optional" section in the
          downloaded document. Skip this to download just the main rules, like before.
        </p>

        <div style={{ overflow: "auto", flex: 1, minHeight: 0, marginTop: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {prompt.suggested.map((r) => (
              <label
                key={r.rule_id}
                className="card"
                style={{ padding: 12, display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}
              >
                <input
                  type="checkbox"
                  checked={checked.has(r.rule_id)}
                  onChange={() => toggle(r.rule_id)}
                  style={{ marginTop: 3 }}
                />
                <div style={{ flex: 1 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <span className="text-body-sm" style={{ fontWeight: 600 }}>
                      {r.rule_id} {r.title}
                    </span>
                    <Chip tone={PRIORITY_TONE[r.priority]}>{r.priority}</Chip>
                  </div>
                  <div className="text-body-xs muted" style={{ marginTop: 4 }}>
                    {r.required}
                  </div>
                  {typeof r.evidence_pct === "number" && (
                    <div className="text-body-xs muted" style={{ marginTop: 4 }}>
                      {r.evidence_count} finding{r.evidence_count === 1 ? "" : "s"} · {r.evidence_requests} request
                      {r.evidence_requests === 1 ? "" : "s"} · {r.evidence_pct}% of sample
                    </div>
                  )}
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="between" style={{ marginTop: 16, flex: "none" }}>
          <button className="btn" onClick={onSkip} disabled={downloading}>
            Skip — download main rules only
          </button>
          <button className="btn accent" onClick={() => onConfirm(selectedRules)} disabled={downloading}>
            <Download size={14} />
            {downloading
              ? "Preparing..."
              : selectedRules.length > 0
                ? `Add ${selectedRules.length} & Download`
                : "Download"}
          </button>
        </div>
      </div>
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
      {/* The red "do not generate redlines unsupervised" banner and the
          per-rule "Unvetted draft" chip are both gone from this preview. The
          source_tag itself still renders as a chip on each rule, and the
          exported Word document still counts unvetted language in its
          methodology preface — the reviewing attorney's copy keeps the
          disclosure, the on-screen preview doesn't lead with it. */}
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

// Mirrors renderPlaybookDocx.ts's ruleTable() field-for-field (WHERE TO LOOK /
// REQUIRED / FALLBACK / ESCALATE IF / FLAG IF / PREFERRED LANGUAGE) so what an
// attorney previews here matches what the Word download actually contains —
// the preview used to show only 5 of 13 fields, silently hiding fallback,
// escalate_if, flag_if, preferred_language, and source_tag.
function PreviewRuleRow({ rule }: { rule: PlaybookRule }) {
  return (
    <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
      <div className="row" style={{ gap: 8 }}>
        <Chip tone="info">{rule.rule_id}</Chip>
        {rule.priority && <Chip tone={PRIORITY_TONE[rule.priority]}>{rule.priority}</Chip>}
        {basisDisplayLabel(rule) && (
          <Chip
            tone={
              isMarmonPreferredPosition(rule)
                ? "good"
                : rule.position_side === "counterparty"
                  ? "bad"
                  : undefined
            }
          >
            {basisDisplayLabel(rule)}
          </Chip>
        )}
      </div>
      <div className="text-body-sm" style={{ fontWeight: 600, marginTop: 4 }}>
        {rule.title}
      </div>
      <div className="text-body-xs muted" style={{ marginTop: 2 }}>
        Applies to: {rule.applies_to}
      </div>
      {rule.basis_summary && (
        <div className="text-body-xs muted" style={{ marginTop: 2 }}>
          Basis: {rule.basis_summary}
        </div>
      )}
      <div className="text-body-sm" style={{ marginTop: 6 }}>
        <strong>Where to look:</strong> {rule.where_to_look}
      </div>
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Required:</strong> {rule.required}
      </div>
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Fallback:</strong> {rule.fallback}
      </div>
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Escalate if:</strong> {rule.escalate_if}
      </div>
      {rule.flag_if?.length > 0 && (
        <div className="text-body-sm" style={{ marginTop: 4 }}>
          <strong>Flag if:</strong>
          <ul style={{ margin: "2px 0 0 18px", padding: 0 }}>
            {rule.flag_if.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Preferred language:</strong> {rule.preferred_language || NO_LANGUAGE_TEXT}
      </div>
      {rule.confidence_note && (
        <div className="text-body-xs muted" style={{ marginTop: 4, fontStyle: "italic" }}>
          Evidence basis: {rule.confidence_note}
        </div>
      )}
    </div>
  );
}
