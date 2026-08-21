// Pure assembly logic for the contract-drafting tool ("Job B") — no PDF/React
// concerns here, so a different output format could reuse this later without
// rewriting the assembly step. See renderContractPdf.ts for rendering.

export type Rule = {
  rule_id: string;
  title: string;
  category: string;
  priority: string;
  applies_to: string;
  where_to_look: string;
  required: string;
  fallback: string;
  escalate_if: string;
  flag_if: string[];
  preferred_language: string | null;
  source_tag: string | null;
};

export type PlaybookManifestEntry = {
  id: string;
  label: string;
  contractTypes: string[];
  file: string;
};

export type AssembledClause = {
  number: string;
  title: string;
  body: string;
  sourceTag: string | null;
  ruleId: string;
};

export type AssembledSection = {
  number: number;
  title: string;
  clauses: AssembledClause[];
};

export type NeedsManualDraftItem = {
  ruleId: string;
  title: string;
  category: string;
  required: string;
};

export type AssembledContract = {
  contractType: string;
  partyA: string;
  partyB: string;
  generatedAt: string;
  sections: AssembledSection[];
  needsManualDraft: NeedsManualDraftItem[];
};

// Conventional contract drafting order — deliberately NOT the playbook's own
// risk-review category order (Liability & Indemnity first makes sense for an
// audit checklist, not for a document someone is meant to read start to end).
export const CONTRACT_SECTION_ORDER = [
  "Scope, Site & Operations",
  "Payment & Money",
  "Liquidated Damages & Delay",
  "Standby, Suspension & Termination",
  "Defects & Warranties",
  "Insurance",
  "Liability & Indemnity",
  "Security & Guarantees",
  "IP, Confidentiality & Data",
  "Equipment",
  "Commercial & Structural",
  "Flow-down & Upstream Risk",
];

const BRACKET_RE = /\[[^\]]+\]/g;

// Bracket placeholders (cross-references to another clause, or
// jurisdiction-specific statute alternatives) are flagged for a human to
// resolve, never auto-filled — correctly inferring which clause or which
// jurisdiction's wording applies isn't reliably derivable from the data, and
// a wrong guess baked silently into a legal document is worse than a
// visibly incomplete one.
function flagBracketPlaceholders(text: string): string {
  return text.replace(BRACKET_RE, (match) => `[[NEEDS REVIEW: ${match}]]`);
}

export function selectRules(rules: Rule[], contractType: string): Rule[] {
  return rules.filter((r) => r.applies_to === "All contract types" || r.applies_to === contractType);
}

export function assembleContract(
  rules: Rule[],
  contractType: string,
  partyA: string,
  partyB: string
): AssembledContract {
  const selected = selectRules(rules, contractType);
  const insertable = selected.filter((r) => r.preferred_language);
  const needsManualDraft: NeedsManualDraftItem[] = selected
    .filter((r) => !r.preferred_language)
    .map((r) => ({ ruleId: r.rule_id, title: r.title, category: r.category, required: r.required }));

  const byCategory = new Map<string, Rule[]>();
  for (const r of insertable) {
    if (!byCategory.has(r.category)) byCategory.set(r.category, []);
    byCategory.get(r.category)!.push(r);
  }

  const unknownCategories = [...byCategory.keys()].filter((c) => !CONTRACT_SECTION_ORDER.includes(c));
  if (unknownCategories.length > 0) {
    // A future playbook could introduce a category this order doesn't know
    // about yet — fail loudly rather than silently dropping those clauses.
    throw new Error(`Unrecognized categories not in CONTRACT_SECTION_ORDER: ${unknownCategories.join(", ")}`);
  }

  const sections: AssembledSection[] = [];
  let sectionNumber = 0;
  for (const category of CONTRACT_SECTION_ORDER) {
    const categoryRules = byCategory.get(category);
    if (!categoryRules || categoryRules.length === 0) continue;
    sectionNumber += 1;
    const clauses: AssembledClause[] = categoryRules.map((r, i) => ({
      number: `${sectionNumber}.${i + 1}`,
      title: r.title,
      body: flagBracketPlaceholders(r.preferred_language as string),
      sourceTag: r.source_tag,
      ruleId: r.rule_id,
    }));
    sections.push({ number: sectionNumber, title: category, clauses });
  }

  return {
    contractType,
    partyA,
    partyB,
    generatedAt: new Date().toISOString(),
    sections,
    needsManualDraft,
  };
}
