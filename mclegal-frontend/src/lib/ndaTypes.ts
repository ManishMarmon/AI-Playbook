/**
 * The NDA directionality labels, exactly as azure_nda_classifier.py writes
 * them into requests.nda_type.
 *
 * One list, used by the All Requests filter and the Draft Contract variant
 * picker. They were written out twice before; a typo in either copy silently
 * matched nothing, which looks identical to "no contracts of that kind".
 */
export const NDA_DIRECTIONS = [
  "Mutual",
  "One-way (Marmon Receiving)",
  "One-way (Marmon Disclosing)",
] as const;

export type NdaDirection = (typeof NDA_DIRECTIONS)[number];

/**
 * Contract types that are negotiated differently depending on a sub-kind, and
 * therefore need a second dropdown before a playbook can be resolved. An NDA's
 * direction changes the position on nearly every clause, so one "NDA" playbook
 * covering all three would average away the thing that matters.
 *
 * A type absent from here has no variant step — the playbook resolves from
 * jurisdiction + contract type alone.
 */
export const VARIANTS_BY_CONTRACT_TYPE: Record<string, readonly string[]> = {
  NDA: NDA_DIRECTIONS,
};
