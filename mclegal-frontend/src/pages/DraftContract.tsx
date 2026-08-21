import { useMemo, useState } from "react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { assembleContract, type PlaybookManifestEntry, type Rule } from "../lib/contractAssembly";
import { downloadContractPdf } from "../lib/renderContractPdf";

function isManifest(data: unknown): data is PlaybookManifestEntry[] {
  return Array.isArray(data);
}

function isRules(data: unknown): data is Rule[] {
  return Array.isArray(data);
}

export default function DraftContract() {
  const manifest = useJsonResource<PlaybookManifestEntry[]>("/playbooks/manifest.json", isManifest);

  const [playbookId, setPlaybookId] = useState<string>("");
  const [contractType, setContractType] = useState<string>("");
  const [partyA, setPartyA] = useState("");
  const [partyB, setPartyB] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const entries = manifest.status === "ready" ? manifest.data : [];
  const selectedEntry = entries.find((e) => e.id === (playbookId || entries[0]?.id));
  const effectivePlaybookId = selectedEntry?.id ?? "";
  const effectiveContractType = contractType || selectedEntry?.contractTypes[0] || "";

  const rulesUrl = selectedEntry ? `/playbooks/${selectedEntry.file}` : "";
  const rules = useJsonResource<Rule[]>(rulesUrl || "/playbooks/__none__.json", isRules);

  const canGenerate = useMemo(
    () => Boolean(effectivePlaybookId && effectiveContractType && partyA.trim() && partyB.trim() && rules.status === "ready"),
    [effectivePlaybookId, effectiveContractType, partyA, partyB, rules.status]
  );

  function handleGenerate() {
    if (rules.status !== "ready" || !effectiveContractType) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const contract = assembleContract(rules.data, effectiveContractType, partyA.trim(), partyB.trim());
      const filename = `${effectiveContractType.replace(/[^\w]+/g, "-")}-draft.pdf`;
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
        <div className="card" style={{ padding: 24, marginTop: 20, maxWidth: 520 }}>
          <div className="field">
            <label htmlFor="playbook-select">Playbook</label>
            <select
              id="playbook-select"
              className="select"
              value={effectivePlaybookId}
              onChange={(e) => {
                setPlaybookId(e.target.value);
                setContractType("");
              }}
            >
              {entries.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="contract-type-select">Contract type</label>
            <select
              id="contract-type-select"
              className="select"
              value={effectiveContractType}
              onChange={(e) => setContractType(e.target.value)}
              disabled={!selectedEntry}
            >
              {selectedEntry?.contractTypes.map((ct) => (
                <option key={ct} value={ct}>
                  {ct}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="party-a-input">Party A</label>
            <input
              id="party-a-input"
              className="input"
              value={partyA}
              onChange={(e) => setPartyA(e.target.value)}
              placeholder="e.g. Freo Group Pty Ltd"
            />
          </div>

          <div className="field">
            <label htmlFor="party-b-input">Party B</label>
            <input
              id="party-b-input"
              className="input"
              value={partyB}
              onChange={(e) => setPartyB(e.target.value)}
              placeholder="e.g. Counterparty Pty Ltd"
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
    </div>
  );
}
