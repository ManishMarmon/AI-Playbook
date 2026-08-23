import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { isPlaybookManifest, type PlaybookMeta } from "../lib/playbooks";
import { assembleContract, type Rule } from "../lib/contractAssembly";
import { downloadContractPdf } from "../lib/renderContractPdf";

const ALL = "";

function isRules(data: unknown): data is Rule[] {
  return Array.isArray(data);
}

export default function DraftContract() {
  const manifest = useJsonResource<PlaybookMeta[]>("/playbooks/manifest.json", isPlaybookManifest);

  const [jurisdiction, setJurisdiction] = useState<string>(ALL);
  const [contractType, setContractType] = useState<string>(ALL);
  const [partyA, setPartyA] = useState("");
  const [partyB, setPartyB] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const entries = manifest.status === "ready" ? manifest.data : [];

  const jurisdictions = useMemo(
    () => Array.from(new Set(entries.map((e) => e.jurisdiction).filter((j): j is string => !!j))).sort(),
    [entries]
  );

  // Contract types available once a jurisdiction is picked — union across
  // every playbook filed under that jurisdiction, not just one.
  const contractTypesForJurisdiction = useMemo(() => {
    const scoped = jurisdiction ? entries.filter((e) => e.jurisdiction === jurisdiction) : entries;
    return Array.from(new Set(scoped.flatMap((e) => e.contractTypes))).sort();
  }, [entries, jurisdiction]);

  // Reset a contract type that's no longer valid once jurisdiction changes.
  useEffect(() => {
    if (contractType && !contractTypesForJurisdiction.includes(contractType)) {
      setContractType(ALL);
    }
  }, [contractTypesForJurisdiction, contractType]);

  // Resolve to a single playbook from (jurisdiction, contract type) — never
  // guess: 0 or 2+ matches both mean "can't safely proceed," same convention
  // as the server-side select_playbook().
  const matches = useMemo(() => {
    if (!jurisdiction || !contractType) return [];
    return entries.filter((e) => e.jurisdiction === jurisdiction && e.contractTypes.includes(contractType));
  }, [entries, jurisdiction, contractType]);
  const selectedEntry = matches.length === 1 ? matches[0] : undefined;

  const rulesUrl = selectedEntry ? `/playbooks/${selectedEntry.file}` : "";
  const rules = useJsonResource<Rule[]>(rulesUrl || "/playbooks/__none__.json", isRules);

  const preview = useMemo(() => {
    if (!selectedEntry || rules.status !== "ready" || !contractType) return null;
    try {
      return assembleContract(rules.data, contractType, partyA.trim() || "[Party A]", partyB.trim() || "[Party B]");
    } catch {
      return null;
    }
  }, [selectedEntry, rules, contractType, partyA, partyB]);

  const canGenerate = useMemo(
    () => Boolean(selectedEntry && contractType && partyA.trim() && partyB.trim() && rules.status === "ready"),
    [selectedEntry, contractType, partyA, partyB, rules.status]
  );

  function handleGenerate() {
    if (rules.status !== "ready" || !contractType) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const contract = assembleContract(rules.data, contractType, partyA.trim(), partyB.trim());
      const filename = `${contractType.replace(/[^\w]+/g, "-")}-draft.pdf`;
      downloadContractPdf(contract, filename);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div>
      <div className="eyebrow">McLegal · Golden Rules</div>
      <h1>Draft Contract</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        Assembles a first-draft contract from a Golden Rules playbook's required clauses. This is a
        starting point for a human reviewer, not a finished, execution-ready document.
      </p>

      {manifest.status !== "ready" && (
        <ResourceStatus
          status={manifest.status}
          error={manifest.error}
          onRetry={manifest.refetch}
          loadingLabel="Loading playbooks..."
          errorLabel="Couldn't load the playbook list."
        />
      )}

      {manifest.status === "ready" && entries.length === 0 && (
        <div className="card" style={{ padding: 24, marginTop: 20 }}>
          <p className="muted">No playbooks have been parsed yet.</p>
        </div>
      )}

      {manifest.status === "ready" && entries.length > 0 && (
        <div className="card" style={{ padding: 24, marginTop: 20, maxWidth: 560 }}>
          <div className="field">
            <label htmlFor="jurisdiction-select">Jurisdiction</label>
            <select
              id="jurisdiction-select"
              className="select"
              value={jurisdiction}
              onChange={(e) => setJurisdiction(e.target.value)}
            >
              <option value={ALL}>Select a jurisdiction...</option>
              {jurisdictions.map((j) => (
                <option key={j} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="contract-type-select">Contract type</label>
            <select
              id="contract-type-select"
              className="select"
              value={contractType}
              onChange={(e) => setContractType(e.target.value)}
              disabled={!jurisdiction}
            >
              <option value={ALL}>Select a contract type...</option>
              {contractTypesForJurisdiction.map((ct) => (
                <option key={ct} value={ct}>
                  {ct}
                </option>
              ))}
            </select>
          </div>

          {jurisdiction && contractType && matches.length === 0 && (
            <p className="field-error">
              No playbook covers {contractType} in {jurisdiction} yet.
            </p>
          )}
          {jurisdiction && contractType && matches.length > 1 && (
            <p className="field-error">
              {matches.length} playbooks match {contractType} in {jurisdiction} — ambiguous, can't
              safely pick one.
            </p>
          )}

          {selectedEntry && (
            <div className="text-body-xs muted" style={{ marginTop: -4, marginBottom: 12 }}>
              Using playbook: <strong>{selectedEntry.label}</strong>
              {selectedEntry.status !== "attorney_reviewed" && (
                <span style={{ color: "var(--bad)" }}>
                  {" "}
                  — AI draft, not yet attorney-reviewed. Treat every clause below as a starting point,
                  not an approved position.
                </span>
              )}
            </div>
          )}

          <div className="field">
            <label htmlFor="party-a-input">Party A</label>
            <input
              id="party-a-input"
              className="input"
              value={partyA}
              onChange={(e) => setPartyA(e.target.value)}
              placeholder="e.g. Marmon Holdings, Inc."
            />
          </div>

          <div className="field">
            <label htmlFor="party-b-input">Party B</label>
            <input
              id="party-b-input"
              className="input"
              value={partyB}
              onChange={(e) => setPartyB(e.target.value)}
              placeholder="e.g. Counterparty, Inc."
            />
          </div>

          {rules.status === "error" && (
            <p className="field-error">Couldn't load this playbook's rules: {rules.error}</p>
          )}
          {generateError && <p className="field-error">{generateError}</p>}

          <button
            className="btn accent lg"
            disabled={!canGenerate || generating}
            onClick={handleGenerate}
            style={{ marginTop: 8 }}
          >
            {generating ? "Generating..." : "Generate Draft (PDF)"}
          </button>
        </div>
      )}

      {preview && preview.needsManualDraft.length > 0 && (
        <div className="card" style={{ padding: 20, marginTop: 16, maxWidth: 560, borderColor: "var(--warn, #b45309)" }}>
          <div className="row" style={{ gap: 6, color: "var(--warn, #b45309)" }}>
            <AlertTriangle size={16} />
            <strong>{preview.needsManualDraft.length} item(s) this playbook can't auto-draft</strong>
          </div>
          <p className="text-body-xs muted" style={{ marginTop: 4 }}>
            The playbook has no pre-approved model language for these — they'll be listed in the
            generated PDF too, but flagging them here so you know before you send it to attorney.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            {preview.needsManualDraft.map((item) => (
              <div key={item.ruleId} style={{ paddingLeft: 10, borderLeft: "2px solid var(--warn, #b45309)" }}>
                <div className="text-body-sm" style={{ fontWeight: 600 }}>
                  {item.ruleId} — {item.title} <span className="muted">({item.category})</span>
                </div>
                <div className="text-body-xs muted">Required position: {item.required}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
