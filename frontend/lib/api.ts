export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Issue = { code: string; severity: "info" | "warning" | "error"; message: string; field?: string | null };
export type Evidence = { field: string; quote: string; confidence: number };

export type Profile = {
  address: string | null;
  building_type: string;
  year_built: number | null;
  dwelling_units: number | null;
  living_area_m2: number | null;
  final_energy_kwh_m2a: number | null;
  energy_class: string | null;
  heating_type: string;
  certificate_type: string;
  evidence: Evidence[];
};

export type Extraction = {
  run_id: string;
  profile: Profile;
  issues: Issue[];
  needs_review: boolean;
  mode: "text" | "vision" | "regex_fallback" | "none";
  model: string | null;
  cached: boolean;
};

export type Citation = { chunk_id: string; title: string; url: string | null; snippet: string };

export type Measure = {
  measure_id: string;
  label: string;
  category: string;
  priority: number;
  rationale: string;
  cost_eur_low: number;
  cost_eur_high: number;
  cost_eur: number;
  subsidy_eur: number;
  subsidy_program: string;
  saving_pct: number;
  citation_ids: string[];
};

export type Step = {
  name: string;
  kind: string;
  status: string;
  duration_ms: number;
  model: string | null;
  tokens: number;
  cost_usd: number;
  meta: Record<string, unknown>;
};

export type Plan = {
  run_id: string;
  summary: string;
  measures: Measure[];
  total_cost_eur: number;
  total_subsidy_eur: number;
  net_cost_eur: number;
  energy_before_kwh_m2a: number;
  energy_after_kwh_m2a: number;
  energy_class_before: string | null;
  energy_class_after: string;
  co2_before_t: number;
  co2_after_t: number;
  max_rent_increase_eur_m2_month: number | null;
  assumptions: string[];
  citations: Citation[];
  issues: Issue[];
  needs_review: boolean;
  planner: "agent" | "rule_based_fallback";
  steps: Step[];
};

export type Answer = {
  run_id: string;
  answer: string;
  citations: Citation[];
  answerable: boolean;
  mode: "llm" | "extractive_fallback" | "refused";
  issues: Issue[];
};

export type Health = {
  status: string;
  llm_enabled: boolean;
  primary_model: string;
  fallback_model: string;
  qdrant_mode: string;
  embeddings: string;
  kb_chunks: number;
  kb_version: string;
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const get = <T,>(path: string) => fetch(`${API}${path}`, { cache: "no-store" }).then((r) => handle<T>(r));

export const post = <T,>(path: string, body?: unknown) =>
  fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));

export const upload = <T,>(path: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(`${API}${path}`, { method: "POST", body: fd }).then((r) => handle<T>(r));
};

export const eur = (n: number) =>
  new Intl.NumberFormat("en-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n);
