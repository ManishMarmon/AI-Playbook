import { describe, it, expect } from "vitest";
import { buildMethodologySection, buildHandoffSection } from "./renderPlaybookDocx";
import type { PlaybookRule } from "./renderPlaybookDocx";
import type { PlaybookMeta, PlaybookMethodology } from "./playbooks";

// The methodology preface is the page that tells a reviewing attorney how much
// weight the rules deserve. These tests pin the two things that would quietly
// mislead: rendering a section the data doesn't support, and dropping a caveat.

const BASE_META: PlaybookMeta = {
  id: "nda-usa-mutual",
  label: "US Mutual NDA",
  jurisdiction: "United States",
  status: "ai_draft",
  contractTypes: ["NDA"],
  file: "nda-usa-mutual.json",
};

const FULL: PlaybookMethodology = {
  sample: {
    funnel: [
      { label: "requests of this type and jurisdiction in CobbleStone", count: 3026 },
      { label: "with at least one tracked-changes redline", count: 2219 },
      { label: "analysed in this playbook", count: 100 },
    ],
    subsetSize: 100,
    dateRange: "23 Jun 2026 - 28 Aug 2026",
  },
  comparisonBasis: [{ label: "Preferred position", count: 100 }],
  positionSides: [
    { label: "Marmon preferred position", count: 78 },
    { label: "Counterparty position", count: 22 },
  ],
  verification: { confirmed: 1200, flagged: 90, verifyFailed: 3, requestsTagged: 100, requestsTotal: 100 },
  evidenceThresholdPct: 15,
  models: { clauseTagging: "gpt-5.6-luna" },
  caveats: ["1,989 are not yet classified.", "Every contract had usable markup."],
};

/** Flattens the docx element tree to the text a reader would see.
 *
 * docx keeps run text as bare strings inside nested `root` arrays rather than
 * on a `.text` property, so this collects every string in the tree. Attribute
 * values come along too; harmless here, since the assertions look for specific
 * reader-facing sentences. */
function textOf(nodes: unknown[]): string {
  const out: string[] = [];
  const seen = new WeakSet<object>();
  const walk = (n: unknown) => {
    if (typeof n === "string") {
      out.push(n);
      return;
    }
    if (n === null || typeof n !== "object") return;
    if (seen.has(n)) return;
    seen.add(n);
    for (const v of Object.values(n as Record<string, unknown>)) walk(v);
  };
  nodes.forEach(walk);
  return out.join(" ");
}

describe("buildMethodologySection", () => {
  it("renders nothing when a playbook carries no methodology", () => {
    // Attorney-authored playbooks and older AI drafts must be unaffected.
    expect(buildMethodologySection(BASE_META)).toEqual([]);
  });

  it("renders the funnel, sides, verification, threshold and caveats", () => {
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: FULL }));
    expect(text).toContain("How these rules were derived");
    expect(text).toContain("The sample");
    expect(text).toContain("23 Jun 2026 - 28 Aug 2026");
    expect(text).toContain("3,026");
    expect(text).toContain("Whose position each finding represents");
    expect(text).toContain("Marmon preferred position");
    expect(text).toContain("Accuracy checking");
    expect(text).toContain("15%");
    expect(text).toContain("Limitations of this analysis");
  });

  it("includes every caveat verbatim — a dropped one is a hidden limitation", () => {
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: FULL }));
    for (const c of FULL.caveats!) expect(text).toContain(c);
  });

  it("shows funnel counts as percentages of the starting population", () => {
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: FULL }));
    // 100 of 3026 == 3%; a reader must see how small the sample is, not just "100".
    expect(text).toContain("3%");
  });

  it("omits sections the data does not support rather than rendering empty ones", () => {
    const sparse: PlaybookMethodology = { caveats: ["Only one thing to say."] };
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: sparse }));
    expect(text).toContain("Only one thing to say.");
    expect(text).not.toContain("The sample");
    expect(text).not.toContain("Accuracy checking");
    expect(text).not.toContain("Whose position each finding represents");
  });

  it("omits the failed-check row when nothing failed", () => {
    const clean: PlaybookMethodology = {
      verification: { confirmed: 10, flagged: 1, verifyFailed: 0 },
    };
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: clean }));
    expect(text).toContain("Findings confirmed accurate");
    expect(text).not.toContain("could not complete");
  });

  it("does not claim an evidence threshold when none was recorded", () => {
    const noThreshold: PlaybookMethodology = { ...FULL, evidenceThresholdPct: null };
    const text = textOf(buildMethodologySection({ ...BASE_META, methodology: noThreshold }));
    expect(text).not.toContain("Evidence threshold");
  });

  it("starts on its own page so it cannot be missed mid-rule", () => {
    const section = buildMethodologySection({ ...BASE_META, methodology: FULL });
    expect(JSON.stringify(section[0])).toContain("pageBreak");
  });
});

// ── Reviewer hand-off (5.3) ─────────────────────────────────────────────────
// The ask must match the playbook in front of the reviewer. Sending Monique
// looking for counterparty-position rules in a playbook that has none wastes
// her time; staying silent about ones it does have hides the decision.

function rule(id: string, over: Partial<PlaybookRule> = {}): PlaybookRule {
  return {
    rule_id: id,
    title: "Confidentiality term",
    priority: "must-have",
    applies_to: "NDA",
    category: "Confidentiality",
    where_to_look: "Section 3",
    required: "Five years",
    fallback: "Three years",
    escalate_if: "Perpetual",
    flag_if: [],
    comparison_basis: "redline_internal",
    position_side: "marmon",
    ...over,
  };
}

describe("buildHandoffSection", () => {
  it("renders nothing for an attorney-reviewed playbook", () => {
    const reviewed: PlaybookMeta = { ...BASE_META, status: "attorney_reviewed" };
    expect(buildHandoffSection(reviewed, [rule("NDA-CONF-01")])).toEqual([]);
  });

  it("always asks about rule priorities and explains what it cannot decide", () => {
    const text = textOf(buildHandoffSection(BASE_META, [rule("NDA-CONF-01")]));
    expect(text).toContain("What we need from you");
    expect(text).toContain("Rule priorities");
    // Keeps the substance — why their input is needed — without the review-status
    // warning that used to open this page.
    expect(text).toContain("which positions are policy and which were circumstance");
  });

  it("carries no review-status warning anywhere in the hand-off", () => {
    // Both readers of this document ARE the review, so warning them that it is
    // unreviewed is redundant and reads as a disclaimer on our own work. The
    // asks below still tell them exactly what to decide.
    const rules = [
      rule("NDA-CONF-01", {
        preferred_language: "The Term shall be five (5) years.",
        source_tag: "Unvetted draft - counsel review needed",
      }),
      rule("NDA-IP-02", { position_side: "counterparty" }),
    ];
    const text = textOf(buildHandoffSection(BASE_META, rules));
    for (const banned of [
      /pending attorney review/i,
      /has not been reviewed/i,
      /unvetted/i,
      /sanctioned by counsel/i,
      /AI draft/i,
    ]) {
      expect(text).not.toMatch(banned);
    }
  });

  it("asks about counterparty-position rules and names them", () => {
    const rules = [rule("NDA-CONF-01"), rule("NDA-IP-02", { position_side: "counterparty" })];
    const text = textOf(buildHandoffSection(BASE_META, rules));
    expect(text).toContain("Counterparty-position rules (1)");
    expect(text).toContain("NDA-IP-02");
    expect(text).toContain("rather than what Marmon asks for");
  });

  it("numbers the asks consecutively even when optional ones are absent", () => {
    // The numbering is generated, because a static "1./2./3." jumped straight
    // from 1 to 3 whenever the conditional preferred-language ask was absent.
    const rules = [rule("NDA-CONF-01"), rule("NDA-IP-02", { position_side: "counterparty" })];
    const text = textOf(buildHandoffSection(BASE_META, rules));
    expect(text).toContain("1. Rule priorities");
    expect(text).toContain("2. Counterparty-position rules");
    expect(text).not.toContain("3. ");
  });

  it("stays silent about counterparty rules when there are none", () => {
    const text = textOf(buildHandoffSection(BASE_META, [rule("NDA-CONF-01")]));
    expect(text).not.toContain("Counterparty-position rules");
  });

  it("asks about rules whose side could not be confirmed", () => {
    const rules = [rule("NDA-CONF-01"), rule("NDA-TRM-03", { position_side: "unknown" })];
    const text = textOf(buildHandoffSection(BASE_META, rules));
    expect(text).toContain("side could not be confirmed (1)");
    expect(text).toContain("NDA-TRM-03");
  });

  it("asks about agreed-outcome rules only when a fallback basis was used", () => {
    const withFallback = [rule("NDA-CONF-01"),
      rule("NDA-GOV-04", { comparison_basis: "initial_vs_final", position_side: null })];
    expect(textOf(buildHandoffSection(BASE_META, withFallback))).toContain("Agreed-outcome rules (1)");
    expect(textOf(buildHandoffSection(BASE_META, [rule("NDA-CONF-01")])))
      .not.toContain("Agreed-outcome rules");
  });

  it("asks to approve constructed clause language and names those rules", () => {
    const rules = [rule("NDA-CONF-01", {
      preferred_language: "The Term shall be five (5) years.",
      source_tag: "Unvetted draft - counsel review needed",
    })];
    const text = textOf(buildHandoffSection(BASE_META, rules));
    expect(text).toContain("Model clause language (1 rule)");
    expect(text).toContain("approve, amend, or strike");
    expect(text).toContain("NDA-CONF-01");
    // The provenance is still stated — only the alarm wording went.
    expect(text).toContain("rather than lifted from a precedent document");
  });

  it("distinguishes optional rules included from suggested rules held back", () => {
    const included = textOf(
      buildHandoffSection({ ...BASE_META, suggestedRulesFile: "x-suggested.json" },
        [rule("NDA-CONF-01")], [rule("NDA-OPT-09")])
    );
    expect(included).toContain("Optional rules included in this document (1)");
    expect(included).toContain("NDA-OPT-09");
    expect(included).not.toContain("held back");

    const heldBack = textOf(
      buildHandoffSection({ ...BASE_META, suggestedRulesFile: "x-suggested.json" },
        [rule("NDA-CONF-01")], [])
    );
    expect(heldBack).toContain("Suggested rules held back");
  });

  it("mentions no suggested rules at all when the playbook has none", () => {
    const text = textOf(buildHandoffSection(BASE_META, [rule("NDA-CONF-01")], []));
    expect(text).not.toContain("held back");
    expect(text).not.toContain("Optional rules included");
  });

  it("starts on its own page", () => {
    const section = buildHandoffSection(BASE_META, [rule("NDA-CONF-01")]);
    expect(JSON.stringify(section[0])).toContain("pageBreak");
  });
});
