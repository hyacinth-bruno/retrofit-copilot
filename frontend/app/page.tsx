"use client";

import ArticleIcon from "@mui/icons-material/ArticleOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloudUploadIcon from "@mui/icons-material/CloudUploadOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RouteIcon from "@mui/icons-material/RouteOutlined";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useRef, useState } from "react";
import { Citations, Empty, Issues, Kpi, PageHeader, Panel, Tag, Timeline, confidenceChip } from "./components";
import { eur, get, post, upload, type Extraction, type Plan, type Profile } from "@/lib/api";

type Sample = { name: string; kind: string };

const FIELDS: { key: keyof Profile; label: string; type: "text" | "number" | "select"; options?: string[] }[] = [
  { key: "address", label: "Address", type: "text" },
  { key: "building_type", label: "Building type", type: "select", options: ["multi_family", "single_family", "non_residential", "unknown"] },
  { key: "year_built", label: "Year built", type: "number" },
  { key: "dwelling_units", label: "Dwelling units", type: "number" },
  { key: "living_area_m2", label: "Area (m²)", type: "number" },
  { key: "final_energy_kwh_m2a", label: "Final energy (kWh/m²a)", type: "number" },
  { key: "energy_class", label: "Energy class", type: "select", options: ["", "A+", "A", "B", "C", "D", "E", "F", "G", "H"] },
  { key: "heating_type", label: "Heating", type: "select", options: ["gas", "oil", "district_heating", "heat_pump", "electric", "biomass", "other", "unknown"] },
  { key: "certificate_type", label: "Certificate", type: "select", options: ["demand", "consumption", "unknown"] },
];

const MODE_LABEL: Record<Extraction["mode"], string> = {
  text: "text layer → Claude",
  vision: "image → Claude vision",
  regex_fallback: "rule-based fallback",
  none: "manual entry needed",
};

const CLASSES = ["A+", "A", "B", "C", "D", "E", "F", "G", "H"];

export default function AnalyzePage() {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [busy, setBusy] = useState<"extract" | "plan" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [edited, setEdited] = useState<Set<string>>(new Set());
  const [ownerOccupied, setOwnerOccupied] = useState(false);
  const [hasIsfp, setHasIsfp] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    get<Sample[]>("/api/samples").then(setSamples).catch(() => undefined);
  }, []);

  const evidence = useMemo(
    () => Object.fromEntries((profile?.evidence ?? []).map((e) => [e.field, e])),
    [profile],
  );

  async function run(fn: () => Promise<Extraction>) {
    setBusy("extract");
    setError(null);
    setPlan(null);
    try {
      const res = await fn();
      setExtraction(res);
      setProfile(res.profile);
      setEdited(new Set());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function setField(key: keyof Profile, raw: string, type: string) {
    if (!profile) return;
    const value = type === "number" ? (raw === "" ? null : Number(raw)) : raw === "" ? null : raw;
    setProfile({ ...profile, [key]: value });
    setEdited(new Set(edited).add(key));
  }

  async function makePlan() {
    if (!profile || !extraction) return;
    setBusy("plan");
    setError(null);
    try {
      // Human corrections are logged as feedback; they can be promoted into the eval set.
      await Promise.all(
        [...edited].map((f) =>
          post("/api/feedback", {
            run_id: extraction.run_id,
            field: f,
            predicted: String(extraction.profile[f as keyof Profile] ?? ""),
            corrected: String(profile[f as keyof Profile] ?? ""),
          }).catch(() => undefined),
        ),
      );
      setPlan(await post<Plan>("/api/plan", { profile, owner_occupied: ownerOccupied, has_isfp: hasIsfp }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main>
      <PageHeader eyebrow="Analyze" title="Energy certificate → retrofit plan">
        Upload an Energieausweis. The AI reads it, you check the values, and an agent proposes measures with costs, grants
        and CO₂, citing its sources.
      </PageHeader>

      {error && (
        <Alert severity="error" variant="outlined" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <div className="grid2">
        <Panel
          id="h-input"
          title="1 · Certificate"
          icon={<ArticleIcon fontSize="small" />}
          action={
            extraction && (
              <Stack direction="row" spacing={0.75}>
                <Tag tone="accent">{MODE_LABEL[extraction.mode]}</Tag>
                {extraction.cached && <Tag>cached</Tag>}
              </Stack>
            )
          }
        >
          <div
            className={`drop ${over ? "over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              const f = e.dataTransfer.files[0];
              if (f) run(() => upload<Extraction>("/api/extract", f));
            }}
          >
            <CloudUploadIcon sx={{ fontSize: 34, color: "primary.main", mb: 0.5, filter: "drop-shadow(0 0 10px rgba(92,225,230,0.6))" }} />
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Drop a PDF or photo here, or
            </Typography>
            <Button variant="outlined" onClick={() => fileInput.current?.click()} disabled={busy !== null}>
              Choose file
            </Button>
            <input
              ref={fileInput}
              id="file"
              type="file"
              accept=".pdf,image/png,image/jpeg,image/webp"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) run(() => upload<Extraction>("/api/extract", f));
                e.target.value = "";
              }}
            />
          </div>

          {samples.length > 0 && (
            <Stack spacing={1}>
              <Typography variant="overline" color="text.secondary">
                Fictional samples
              </Typography>
              <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.75 }}>
                {samples.map((s) => (
                  <Button
                    key={s.name}
                    size="small"
                    variant="outlined"
                    disabled={busy !== null}
                    onClick={() => run(() => post<Extraction>(`/api/extract/sample/${encodeURIComponent(s.name)}`))}
                    title={s.kind}
                    sx={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 500 }}
                  >
                    {s.name.replace(/\.(pdf|jpg|png)$/, "")}
                  </Button>
                ))}
              </Stack>
            </Stack>
          )}

          {busy === "extract" && (
            <Stack spacing={1}>
              <LinearProgress />
              <Typography variant="body2" color="text.secondary">
                Reading the certificate…
              </Typography>
            </Stack>
          )}

          {profile && extraction && (
            <>
              {extraction.needs_review ? (
                <Alert severity="warning" variant="outlined">
                  Check the highlighted values before planning.
                </Alert>
              ) : (
                <Alert severity="success" variant="outlined">
                  All checks passed. You can still edit any value.
                </Alert>
              )}
              <div className="fields">
                {FIELDS.map((f) => {
                  const ev = evidence[f.key as string];
                  const flagged = extraction.issues.some((i) => i.field === f.key && i.severity !== "info");
                  const value = profile[f.key] as string | number | null;
                  return (
                    <div key={f.key} style={f.key === "address" ? { gridColumn: "1 / -1" } : undefined}>
                      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 0.75, gap: 1 }}>
                        <Typography component="label" htmlFor={`f-${f.key}`} variant="body2" sx={{ color: flagged ? "warning.main" : "text.secondary" }}>
                          {f.label}
                          {edited.has(f.key) && (
                            <span style={{ marginLeft: 6 }}>
                              <Tag tone="info">edited</Tag>
                            </span>
                          )}
                        </Typography>
                        {ev ? confidenceChip(ev.confidence) : null}
                      </Stack>
                      <TextField
                        id={`f-${f.key}`}
                        fullWidth
                        size="small"
                        select={f.type === "select"}
                        type={f.type === "select" ? undefined : f.type}
                        value={value ?? ""}
                        sx={flagged ? { "& .MuiOutlinedInput-notchedOutline": { borderColor: "warning.main" } } : undefined}
                        onChange={(e) => setField(f.key, e.target.value, f.type)}
                      >
                        {f.type === "select" &&
                          f.options!.map((o) => (
                            <MenuItem key={o} value={o}>
                              {o || "—"}
                            </MenuItem>
                          ))}
                      </TextField>
                      {ev && (
                        <span className="quote" title={ev.quote}>
                          “{ev.quote}”
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              <Stack spacing={1}>
                <Typography variant="overline" color="text.secondary">
                  Guardrail results
                </Typography>
                <Issues issues={extraction.issues} />
              </Stack>
              <Stack direction="row" sx={{ flexWrap: "wrap", columnGap: 2 }}>
                <FormControlLabel
                  control={<Switch checked={ownerOccupied} onChange={(e) => setOwnerOccupied(e.target.checked)} />}
                  label={<Typography variant="body2">Owner-occupied</Typography>}
                />
                <FormControlLabel
                  control={<Switch checked={hasIsfp} onChange={(e) => setHasIsfp(e.target.checked)} />}
                  label={<Typography variant="body2">Has iSFP roadmap</Typography>}
                />
              </Stack>
              <Button variant="contained" size="large" startIcon={<AutoAwesomeIcon />} onClick={makePlan} disabled={busy !== null}>
                {busy === "plan" ? "Agent is planning…" : "Generate retrofit plan"}
              </Button>
            </>
          )}
        </Panel>

        <Panel
          id="h-plan"
          title="2 · Retrofit plan"
          icon={<RouteIcon fontSize="small" />}
          action={
            plan && (
              <Stack direction="row" spacing={0.75}>
                <Tag tone={plan.planner === "agent" ? "accent" : "warn"}>{plan.planner === "agent" ? "LangGraph agent" : "rule-based fallback"}</Tag>
                <Tag tone={plan.needs_review ? "warn" : "ok"}>{plan.needs_review ? "needs review" : "checks passed"}</Tag>
              </Stack>
            )
          }
        >
          {!plan &&
            (busy === "plan" ? (
              <Stack spacing={1.5}>
                <LinearProgress />
                <Empty>The agent is searching funding rules and running the cost tools…</Empty>
              </Stack>
            ) : (
              <Empty>Pick a sample or upload a certificate, check the values, then generate a plan.</Empty>
            ))}
          {plan && <PlanView plan={plan} />}
        </Panel>
      </div>
    </main>
  );
}

function Section({ title, defaultExpanded, children }: { title: React.ReactNode; defaultExpanded?: boolean; children: React.ReactNode }) {
  return (
    <Accordion defaultExpanded={defaultExpanded}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="overline" color="text.secondary">
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}

function PlanView({ plan }: { plan: Plan }) {
  return (
    <Stack spacing={2.5}>
      <Typography>{plan.summary}</Typography>
      <div className="kpis">
        <Kpi label="Investment" value={eur(plan.total_cost_eur)} />
        <Kpi label="Grants" value={eur(plan.total_subsidy_eur)} />
        <Kpi label="Net cost" value={eur(plan.net_cost_eur)} />
        <Kpi
          label="Final energy"
          value={
            <>
              {Math.round(plan.energy_before_kwh_m2a)} <span className="muted">→</span> {Math.round(plan.energy_after_kwh_m2a)}
            </>
          }
          hint="kWh/m²a"
        />
        <Kpi
          label="CO₂ per year"
          value={
            <>
              {plan.co2_before_t} <span className="muted">→</span> {plan.co2_after_t}
            </>
          }
          hint="tonnes"
        />
        {plan.max_rent_increase_eur_m2_month !== null && (
          <Kpi label="Max rent increase" value={`${plan.max_rent_increase_eur_m2_month.toFixed(2)} €`} hint="per m² per month (§ 559)" />
        )}
      </div>

      <Stack spacing={1}>
        <Typography variant="overline" color="text.secondary">
          Energy class
        </Typography>
        <div className="energy-scale" role="img" aria-label={`Energy class from ${plan.energy_class_before ?? "unknown"} to ${plan.energy_class_after}`}>
          {CLASSES.map((c) => (
            <div key={c} className={c === plan.energy_class_after ? "after" : c === plan.energy_class_before ? "before" : ""}>
              {c}
            </div>
          ))}
        </div>
      </Stack>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              <TableCell>Measure</TableCell>
              <TableCell align="right">Cost</TableCell>
              <TableCell align="right">Grant</TableCell>
              <TableCell align="right">Saving</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {plan.measures.map((m) => (
              <TableRow key={m.measure_id} sx={{ verticalAlign: "top" }}>
                <TableCell className="mono" sx={{ color: "primary.main" }}>
                  {m.priority}
                </TableCell>
                <TableCell>
                  <Typography sx={{ fontWeight: 500, fontSize: 14 }}>{m.label}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {m.rationale}
                  </Typography>
                  <Typography className="mono" color="text.secondary" sx={{ mt: 0.5 }}>
                    {m.subsidy_program}
                    {m.citation_ids.map((c) => ` [${c}]`)}
                  </Typography>
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {eur(m.cost_eur)}
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: 12 }}>
                    {eur(m.cost_eur_low)}–{eur(m.cost_eur_high)}
                  </Typography>
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", color: "success.main", fontVariantNumeric: "tabular-nums" }}>
                  {eur(m.subsidy_eur)}
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                  {m.saving_pct ? `${m.saving_pct}%` : m.measure_id === "pv" ? "solar power" : "fuel switch"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Stack spacing={1}>
        <Section title={`Guardrails (${plan.issues.length})`} defaultExpanded={plan.issues.length > 0}>
          <Issues issues={plan.issues} />
        </Section>
        <Section title={`Sources (${plan.citations.length})`}>
          <Citations items={plan.citations} />
        </Section>
        <Section title="Assumptions">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {plan.assumptions.map((a, i) => (
              <li key={i}>
                <Typography variant="body2" color="text.secondary">
                  {a}
                </Typography>
              </li>
            ))}
          </ul>
        </Section>
        <Section title={`Trace · ${plan.steps.length} steps · $${plan.steps.reduce((s, x) => s + x.cost_usd, 0).toFixed(4)}`}>
          <Timeline steps={plan.steps} />
        </Section>
      </Stack>
    </Stack>
  );
}
