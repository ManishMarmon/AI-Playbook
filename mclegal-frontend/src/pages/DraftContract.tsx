import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, X } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { isPlaybookManifest, type PlaybookMeta } from "../lib/playbooks";
import { assembleContract, type Rule } from "../lib/contractAssembly";
import { downloadContractPdf } from "../lib/renderContractPdf";
import { VARIANTS_BY_CONTRACT_TYPE } from "../lib/ndaTypes";

const ALL = "";

function isRules(data: unknown): data is Rule[] {
  return Array.isArray(data);
}

type SuggestedRule = Rule & {
  evidence_pct?: number | null;
  evidence_requests?: number | null;
};

function isSuggestedRules(data: unknown): data is SuggestedRule[] {
  return Array.isArray(data);
}

export default function DraftContract() {
  const manifest = useJsonResource<PlaybookMeta[]>("/playbooks/manifest.json", isPlaybookManifest);

  const [jurisdiction, setJurisdiction] = useState<string>(ALL);
  const [contractType, setContractType] = useState<string>(ALL);
  const [variant, setVariant] = useState<string>(ALL);
  const [addOnIds, setAddOnIds] = useState<string[]>([]);
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

  // Every playbook under this jurisdiction + contract type, before the variant
  // narrows them down.
  const candidates = useMemo(() => {
    if (!jurisdiction || !contractType) return [];
    return entries.filter(
      (e) => e.jurisdiction === jurisdiction && e.contractTypes.includes(contractType)
    );
  }, [entries, jurisdiction, contractType]);

  /**
   * The variant dropdown's options. Union of two sources on purpose:
   *   - the sub-kinds this contract type HAS (from the classifier's labels),
   *     so a direction with no playbook yet is visible and marked, rather than
   *     the list silently pretending only one kind of NDA exists;
   *   - any variant a playbook actually declares, so a label we didn't
   *     anticipate (the superseded undifferentiated one) still appears.
   */
  const variantOptions = useMemo(() => {
    const declared = candidates.map((c) => c.variant).filter((v): v is string => !!v);
    const known = VARIANTS_BY_CONTRACT_TYPE[contractType] ?? [];
    const all = [...known, ...declared.filter((d) => !known.includes(d))];
    return all.map((label) => ({
      label,
      playbook: candidates.find((c) => c.variant === label),
    }));
  }, [candidates, contractType]);

  const needsVariant = variantOptions.length > 0;

  useEffect(() => {
    if (contractType && !contractTypesForJurisdiction.includes(contractType)) setContractType(ALL);
  }, [contractTypesForJurisdiction, contractType]);

  useEffect(() => {
    if (variant && !variantOptions.some((o) => o.label === variant)) setVariant(ALL);
  }, [variantOptions, variant]);

  /**
   * Resolve to a single playbook. Never guess: with a variant, the variant
   * decides; without one, a lone candidate is used and 0 or 2+ both mean
   * "can't safely proceed" — the same convention as the server-side
   * select_playbook().
   */
  const selectedEntry = useMemo(() => {
    if (needsVariant) {
      return variant ? variantOptions.find((o) => o.label === variant)?.playbook : undefined;
    }
    return candidates.length === 1 ? candidates[0] : undefined;
  }, [needsVariant, variant, variantOptions, candidates]);

  const rules = useJsonResource<Rule[]>(selectedEntry ? `/playbooks/${selectedEntry.file}` : null, isRules);
  const suggested = useJsonResource<SuggestedRule[]>(
    selectedEntry?.suggestedRulesFile ? `/playbooks/${selectedEntry.suggestedRulesFile}` : null,
    isSuggestedRules
  );

  const suggestedRules = suggested.status === "ready" ? suggested.data : [];

  // Changing playbook invalidates the add-ons, which belong to the previous
  // one's sidecar. Clearing them beats silently carrying a rule across.
  useEffect(() => setAddOnIds([]), [selectedEntry?.id]);

  const addOns = useMemo(
    () => addOnIds.map((id) => suggestedRules.find((r) => r.rule_id === id)).filter((r): r is SuggestedRule => !!r),
    [addOnIds, suggestedRules]
  );

  // Base rules plus the chosen add-ons: one list, so assembly, the preview and
  // the PDF all see exactly what the summary says was selected.
  const effectiveRules = useMemo(
    () => (rules.status === "ready" ? [...rules.data, ...addOns] : []),
    [rules, addOns]
  );

  const preview = useMemo(() => {
    if (!selectedEntry || rules.status !== "ready" || !contractType) return null;
    try {
      return assembleContract(
        effectiveRules,
        contractType,
        selectedEntry.contractTypes,
        partyA.trim() || "[Party A]",
        partyB.trim() || "[Party B]"
      );
    } catch {
      return null;
    }
  }, [selectedEntry, rules.status, effectiveRules, contractType, partyA, partyB]);

  const canGenerate = Boolean(
    selectedEntry && contractType && partyA.trim() && partyB.trim() && rules.status === "ready"
  );

  function handleGenerate() {
    if (rules.status !== "ready" || !contractType || !selectedEntry) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const contract = assembleContract(
        effectiveRules,
        contractType,
        selectedEntry.contractTypes,
        partyA.trim(),
        partyB.trim()
      );
      const slug = [contractType, variant].filter(Boolean).join("-").replace(/[^\w]+/g, "-");
      downloadContractPdf(contract, `${slug}-draft.pdf`);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  const toggleAddOn = (id: string) =>
    setAddOnIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const superseded = /superseded/i.test(selectedEntry?.variant ?? "") ||
    /superseded/i.test(selectedEntry?.label ?? "");

  return (
    <div>
      <h1>Draft Contract</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
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
        <div className="draft-layout">
          {/* ── Left: the choices ─────────────────────────────────────────── */}
          <div className="card" style={{ padding: 24 }}>
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
                  <option key={j} value={j}>{j}</option>
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
                  <option key={ct} value={ct}>{ct}</option>
                ))}
              </select>
            </div>

            {needsVariant && (
              <div className="field">
                <label htmlFor="variant-select">
                  {contractType === "NDA" ? "NDA direction" : `${contractType} variant`}
                </label>
                <select
                  id="variant-select"
                  className="select"
                  value={variant}
                  onChange={(e) => setVariant(e.target.value)}
                >
                  <option value={ALL}>Select...</option>
                  {variantOptions.map((o) => (
                    <option key={o.label} value={o.label} disabled={!o.playbook}>
                      {o.label}
                      {!o.playbook ? " — no playbook yet" : ""}
                    </option>
                  ))}
                </select>
                <div className="field-help">
                  An NDA's direction changes the position on nearly every clause, so each has its
                  own playbook rather than one averaged across all three.
                </div>
              </div>
            )}

            {needsVariant && variant && !selectedEntry && (
              <p className="field-error">
                No playbook has been built for {variant} {contractType} in {jurisdiction} yet.
              </p>
            )}
            {!needsVariant && jurisdiction && contractType && candidates.length === 0 && (
              <p className="field-error">No playbook covers {contractType} in {jurisdiction} yet.</p>
            )}

            {/* Add-on rules, from this playbook's below-threshold sidecar. */}
            {selectedEntry && suggestedRules.length > 0 && (
              <div className="field">
                <label>Optional add-on rules ({addOnIds.length} of {suggestedRules.length} added)</label>
                <div className="field-help" style={{ marginTop: 0, marginBottom: 8 }}>
                  Real but less frequent positions — each shows the share of analysed contracts it
                  was seen in. Below the playbook's evidence bar, so they're opt-in.
                </div>
                <div className="addon-list">
                  {suggestedRules.map((r) => {
                    const on = addOnIds.includes(r.rule_id);
                    return (
                      <button
                        key={r.rule_id}
                        type="button"
                        className={on ? "addon-row on" : "addon-row"}
                        aria-pressed={on}
                        onClick={() => toggleAddOn(r.rule_id)}
                      >
                        <span className="addon-check">{on ? <X size={13} /> : <Plus size={13} />}</span>
                        <span className="addon-body">
                          <span className="text-body-sm">{r.title}</span>
                          <span className="text-body-xs muted">
                            {r.category}
                            {r.evidence_pct != null && ` · seen in ${r.evidence_pct}% of contracts`}
                            {r.evidence_requests != null && ` (${r.evidence_requests})`}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
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

            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="party-b-input">Party B</label>
              <input
                id="party-b-input"
                className="input"
                value={partyB}
                onChange={(e) => setPartyB(e.target.value)}
                placeholder="e.g. Counterparty, Inc."
              />
            </div>
          </div>

          {/* ── Right: what you've selected ───────────────────────────────── */}
          <div className="card draft-summary">
            <div className="draft-summary-head">
              <h3>Your selection</h3>
              <p className="text-body-xs muted" style={{ marginTop: 2 }}>
                Everything that will go into the generated draft.
              </p>
            </div>

            {!selectedEntry ? (
              <div className="draft-summary-empty">
                <p className="text-body-sm muted">
                  Pick a jurisdiction, a contract type
                  {needsVariant ? " and a direction" : ""} to start.
                </p>
              </div>
            ) : (
              <>
                <div className="draft-lines">
                  <div className="draft-line base">
                    <div>
                      <div className="text-body font-semibold">{selectedEntry.label}</div>
                      <div className="text-body-xs muted">
                        Base playbook
                        {rules.status === "ready" && ` · ${rules.data.length} rules`}
                      </div>
                    </div>
                    <span className="chip">Base</span>
                  </div>

                  {addOns.map((r) => (
                    <div className="draft-line" key={r.rule_id}>
                      <div style={{ minWidth: 0 }}>
                        <div className="text-body-sm">{r.title}</div>
                        <div className="text-body-xs muted">
                          Add-on
                          {r.evidence_pct != null && ` · ${r.evidence_pct}% of contracts`}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn-icon"
                        aria-label={`Remove ${r.title}`}
                        onClick={() => toggleAddOn(r.rule_id)}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}

                  {addOns.length === 0 && (
                    <div className="draft-line-note text-body-xs muted">
                      No add-on rules — the base playbook alone.
                    </div>
                  )}
                </div>

                <div className="draft-total">
                  <div className="between">
                    <span className="text-body-sm">Clauses in the draft</span>
                    <strong className="text-body">{preview ? preview.rulesSelected : "—"}</strong>
                  </div>
                  <div className="between text-body-xs muted" style={{ marginTop: 4 }}>
                    <span>Rules considered</span>
                    <span>{preview ? preview.rulesTotal : "—"}</span>
                  </div>
                  {addOns.length > 0 && (
                    <div className="between text-body-xs muted" style={{ marginTop: 4 }}>
                      <span>of which add-ons</span>
                      <span>{addOns.length}</span>
                    </div>
                  )}
                </div>

                {/* The review-status banner that used to sit here is gone. The
                    superseded warning below stays: it guards a specific choice
                    in the dropdown, not the general provenance of the data. */}
                {superseded && (
                  <div className="draft-flag bad">
                    <AlertTriangle size={14} />
                    <span>
                      This playbook is superseded by a direction-specific one. Kept for comparison —
                      don't draft a live contract from it.
                    </span>
                  </div>
                )}
                {rules.status === "error" && (
                  <p className="field-error" style={{ padding: "0 16px" }}>
                    Couldn't load this playbook's rules: {rules.error}
                  </p>
                )}
                {generateError && (
                  <p className="field-error" style={{ padding: "0 16px" }}>{generateError}</p>
                )}

                <div className="draft-summary-foot">
                  <button
                    className="btn accent"
                    style={{ width: "100%", justifyContent: "center" }}
                    disabled={!canGenerate || generating}
                    onClick={handleGenerate}
                  >
                    {generating ? "Generating..." : "Generate Draft (PDF)"}
                  </button>
                  {!canGenerate && selectedEntry && (
                    <p className="text-body-xs muted" style={{ marginTop: 8, textAlign: "center" }}>
                      Enter both party names to generate.
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {preview && preview.needsManualDraft.length > 0 && (
        <div className="card" style={{ padding: 20, marginTop: 16, borderColor: "var(--warn)" }}>
          <div className="row" style={{ gap: 6, color: "var(--warn)" }}>
            <AlertTriangle size={16} />
            <strong>{preview.needsManualDraft.length} item(s) this playbook can't auto-draft</strong>
          </div>
          <p className="text-body-xs muted" style={{ marginTop: 4 }}>
            The playbook has no pre-approved model language for these — they'll be listed in the
            generated PDF too, but flagging them here so you know before you send it to attorney.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            {preview.needsManualDraft.map((item) => (
              <div key={item.ruleId} style={{ paddingLeft: 10, borderLeft: "2px solid var(--warn)" }}>
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
