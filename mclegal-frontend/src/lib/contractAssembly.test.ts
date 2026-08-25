import { describe, expect, it } from "vitest";
import { assembleContract, selectRules, type Rule } from "./contractAssembly";

function makeRule(overrides: Partial<Rule>): Rule {
  return {
    rule_id: "T-01",
    title: "Test rule",
    category: "General",
    priority: "MUST PRESS",
    applies_to: "All contract types",
    where_to_look: "Section 1",
    required: "Required text",
    fallback: "Fallback text",
    escalate_if: "Escalate text",
    flag_if: ["Flag condition"],
    preferred_language: "Preferred language text",
    source_tag: null,
    ...overrides,
  };
}

describe("selectRules", () => {
  it("selects every rule for a single-contract-type playbook regardless of applies_to wording", () => {
    // This is the exact shipped bug: US Real Estate declares one manifest
    // contractType ("Real Estate") but its rules' applies_to values are
    // instrument-level ("Lease", "Commercial lease", "Services agreement").
    // A single-declared-type playbook has nothing to disambiguate against,
    // so every rule must be included.
    const rules = [
      makeRule({ rule_id: "R1", applies_to: "Lease" }),
      makeRule({ rule_id: "R2", applies_to: "Commercial lease" }),
      makeRule({ rule_id: "R3", applies_to: "Services agreement" }),
      makeRule({ rule_id: "R4", applies_to: "All contract types" }),
    ];
    const selected = selectRules(rules, "Real Estate", ["Real Estate"]);
    expect(selected).toHaveLength(4);
  });

  it("still exact-matches applies_to for a playbook that bundles multiple contract types", () => {
    // Freo Group AU's real shape: one playbook file, three contract types.
    // A rule scoped to one of them must not leak into a draft for another.
    const rules = [
      makeRule({ rule_id: "W1", applies_to: "Wind / renewables subcontract" }),
      makeRule({ rule_id: "M1", applies_to: "Mining master supply agreement" }),
      makeRule({ rule_id: "ALL", applies_to: "All contract types" }),
    ];
    const playbookTypes = ["Wind / renewables subcontract", "Mining master supply agreement", "Equipment hire"];

    const wind = selectRules(rules, "Wind / renewables subcontract", playbookTypes);
    expect(wind.map((r) => r.rule_id).sort()).toEqual(["ALL", "W1"]);

    const mining = selectRules(rules, "Mining master supply agreement", playbookTypes);
    expect(mining.map((r) => r.rule_id).sort()).toEqual(["ALL", "M1"]);
  });
});

describe("assembleContract", () => {
  it("reports rulesSelected/rulesTotal so a UI can show inclusion counts", () => {
    const rules = [
      makeRule({ rule_id: "R1", applies_to: "Lease", category: "Payment & Money" }),
      makeRule({ rule_id: "R2", applies_to: "Services agreement", category: "Payment & Money" }),
    ];
    const contract = assembleContract(rules, "Real Estate", ["Real Estate"], "Party A", "Party B");
    expect(contract.rulesTotal).toBe(2);
    expect(contract.rulesSelected).toBe(2);
  });

  it("routes rules with no preferred_language into needsManualDraft instead of a section", () => {
    const rules = [
      makeRule({ rule_id: "R1", category: "Payment & Money", preferred_language: null }),
    ];
    const contract = assembleContract(rules, "NDA", ["NDA"], "Party A", "Party B");
    expect(contract.sections).toHaveLength(0);
    expect(contract.needsManualDraft.map((i) => i.ruleId)).toEqual(["R1"]);
  });
});
