// Builds a link to a specific request in mpact/CobbleStone. The URL pattern
// is set via VITE_MPACT_REQUEST_URL_TEMPLATE (see .env.example) rather than
// hardcoded — it names this org's internal tenant hostname, which shouldn't
// live in source given this repo is public.
export function buildMpactUrl(requestId: number | string): string | null {
  const template = import.meta.env.VITE_MPACT_REQUEST_URL_TEMPLATE as string | undefined;
  if (!template) return null;
  return template.replace("{requestId}", String(requestId));
}
