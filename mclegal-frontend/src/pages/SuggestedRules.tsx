import { useMemo } from "react";
import { Lightbulb } from "lucide-react";
import { useJsonResource } from "../hooks/useJsonResource";
import { ResourceStatus } from "../components/ResourceStatus";
import { Chip, type ChipTone } from "../components/Chip";
import { isPlaybookManifest, type PlaybookMeta } from "../lib/playbooks";
import { NO_LANGUAGE_TEXT, type PlaybookRule } from "../lib/renderPlaybookDocx";

const PRIORITY_TONE: Record<string, ChipTone | undefined> = {
  "MUST PRESS": "bad",
  PRESS: "warn",
  MANAGE: "info",
  "ACCEPT+NOTE": undefined,
};

export default function SuggestedRules() {
  const manifest = useJsonResource<PlaybookMeta[]>("/playbooks/manifest.json", isPlaybookManifest);
  const entries = manifest.status === "ready" ? manifest.data : [];
  const withSuggestions = useMemo(() => entries.filter((e) => e.suggestedRulesFile), [entries]);

  return (
    <div>
      <h1>Suggested Rules</h1>
      <p className="muted page-subtitle" style={{ marginTop: 6 }}>
        Rule candidates synthesis found real support for — 2 or more confirmed negotiation
        findings — but that fell short of the evidence bar required to join a playbook's main
        rule set (currently 15% of the sample the playbook was synthesized from). Nothing here has
        been reviewed, and nothing here is used by Draft Contract or Golden Rules review. Promoting
        one into the real playbook is a manual step today — re-run finalize_playbook.py once more
        evidence accumulates, or move the rule by hand.
      </p>

      {manifest.status !== "ready" && (
        <ResourceStatus
          status={manifest.status}
          error={manifest.error}
          onRetry={manifest.refetch}
          loadingLabel="Loading playbooks..."
          errorLabel="Couldn't load the playbook manifest."
        />
      )}

      {manifest.status === "ready" && withSuggestions.length === 0 && (
        <div className="placeholder" style={{ padding: 32, marginTop: 20 }}>
          No playbook currently has below-threshold rule candidates on record.
        </div>
      )}

      {manifest.status === "ready" && withSuggestions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 20 }}>
          {withSuggestions.map((entry) => (
            <SuggestedRulesCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function SuggestedRulesCard({ entry }: { entry: PlaybookMeta }) {
  const resource = useJsonResource<PlaybookRule[]>(
    `/playbooks/${entry.suggestedRulesFile}`,
    (d): d is PlaybookRule[] => Array.isArray(d)
  );

  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="row" style={{ gap: 8 }}>
        <Lightbulb size={16} className="muted" />
        <div className="text-body-sm" style={{ fontWeight: 600 }}>
          {entry.label}
        </div>
        {resource.status === "ready" && (
          <span className="text-body-xs muted">
            {resource.data.length} candidate rule{resource.data.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {resource.status !== "ready" && (
        <ResourceStatus
          status={resource.status}
          error={resource.error}
          onRetry={resource.refetch}
          loadingLabel="Loading candidates..."
          errorLabel="Couldn't load this playbook's suggested rules."
        />
      )}

      {resource.status === "ready" && (
        <div className="divider-parent" style={{ marginTop: 12 }}>
          <div className="divider" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 10 }}>
            {resource.data.map((rule, i) => (
              <SuggestedRuleRow key={`${entry.id}-${i}`} rule={rule} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestedRuleRow({ rule }: { rule: PlaybookRule }) {
  return (
    <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)" }}>
      <div className="row" style={{ gap: 8 }}>
        {rule.priority && <Chip tone={PRIORITY_TONE[rule.priority]}>{rule.priority}</Chip>}
        <span className="text-body-xs muted">{rule.category}</span>
        {typeof rule.evidence_pct === "number" && (
          <Chip tone="warn">
            {rule.evidence_count} finding{rule.evidence_count === 1 ? "" : "s"}
            {typeof rule.evidence_requests === "number" ? ` · ${rule.evidence_requests} request${rule.evidence_requests === 1 ? "" : "s"}` : ""}
            {" · "}
            {rule.evidence_pct}% of sample
          </Chip>
        )}
      </div>
      <div className="text-body-sm" style={{ fontWeight: 600, marginTop: 4 }}>
        {rule.title}
      </div>
      <div className="text-body-xs muted" style={{ marginTop: 2 }}>
        Applies to: {rule.applies_to}
      </div>
      <div className="text-body-sm" style={{ marginTop: 6 }}>
        <strong>Required:</strong> {rule.required}
      </div>
      <div className="text-body-sm" style={{ marginTop: 4 }}>
        <strong>Fallback:</strong> {rule.fallback}
      </div>
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
