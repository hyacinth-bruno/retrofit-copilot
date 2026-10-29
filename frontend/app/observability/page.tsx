"use client";

import RefreshIcon from "@mui/icons-material/Refresh";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { Fragment, useCallback, useEffect, useState } from "react";
import { Empty, Kpi, PageHeader, Panel, Tag } from "../components";
import { get } from "@/lib/api";

type KindStats = { runs: number; p50_ms: number | null; p95_ms: number | null; error_rate: number; avg_cost_usd: number; fallback_rate: number; review_rate: number };
type ModelStats = { calls: number; p50_ms: number | null; p95_ms: number | null; error_rate: number; input_tokens: number; output_tokens: number; cost_usd: number };
type Metrics = { total_runs: number; total_cost_usd: number; by_kind: Record<string, KindStats>; by_model: Record<string, ModelStats>; feedback_by_field: Record<string, number> };
type RunRow = { id: string; kind: string; started_at: number; duration_ms: number; status: string; cost_usd: number; input_tokens: number; output_tokens: number; llm_calls: number; fallback_used: number; needs_review: number };
type SpanRow = { id: string; name: string; kind: string; duration_ms: number; status: string; model: string | null; input_tokens: number; output_tokens: number; cost_usd: number; error: string | null; meta: Record<string, unknown> };

const pct = (x: number) => `${Math.round(x * 100)}%`;
const ms = (x: number | null) => (x === null ? "—" : x >= 1000 ? `${(x / 1000).toFixed(1)} s` : `${Math.round(x)} ms`);

export default function ObservabilityPage() {
  const [m, setM] = useState<Metrics | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [spans, setSpans] = useState<SpanRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([get<Metrics>("/api/metrics"), get<RunRow[]>("/api/runs?limit=40")])
      .then(([a, b]) => {
        setM(a);
        setRuns(b);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (open) get<SpanRow[]>(`/api/runs/${open}`).then(setSpans).catch(() => setSpans([]));
  }, [open]);

  return (
    <main>
      <PageHeader
        eyebrow="Observability"
        title="Every run, traced"
        action={
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={load}>
            Refresh
          </Button>
        }
      >
        Every AI run is traced: model, tokens, cost, latency, fallbacks and guardrail results.
      </PageHeader>
      <Stack spacing={3}>
        {error && (
          <Alert severity="error" variant="outlined">
            {error}
          </Alert>
        )}
        {m && (
          <>
            <div className="kpis">
              <Kpi label="Runs" value={m.total_runs} />
              <Kpi label="Total spend" value={`$${m.total_cost_usd.toFixed(3)}`} />
              {Object.entries(m.feedback_by_field).length > 0 && (
                <Kpi
                  label="Human corrections"
                  value={Object.values(m.feedback_by_field).reduce((a, b) => a + b, 0)}
                  hint={Object.entries(m.feedback_by_field)
                    .map(([f, n]) => `${f} ${n}`)
                    .join(" · ")}
                />
              )}
            </div>
            <Panel title="By feature">
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Feature</TableCell>
                      <TableCell align="right">Runs</TableCell>
                      <TableCell align="right">p50</TableCell>
                      <TableCell align="right">p95</TableCell>
                      <TableCell align="right">Avg cost</TableCell>
                      <TableCell align="right">Errors</TableCell>
                      <TableCell align="right">Fallback</TableCell>
                      <TableCell align="right">Review</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(m.by_kind).map(([k, s]) => (
                      <TableRow key={k}>
                        <TableCell className="mono">{k}</TableCell>
                        <TableCell align="right">{s.runs}</TableCell>
                        <TableCell align="right">{ms(s.p50_ms)}</TableCell>
                        <TableCell align="right">{ms(s.p95_ms)}</TableCell>
                        <TableCell align="right">${s.avg_cost_usd.toFixed(4)}</TableCell>
                        <TableCell align="right">{pct(s.error_rate)}</TableCell>
                        <TableCell align="right">{pct(s.fallback_rate)}</TableCell>
                        <TableCell align="right">{pct(s.review_rate)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Panel>
            <Panel title="By model">
              {Object.keys(m.by_model).length === 0 ? (
                <Empty>No model calls yet. Set ANTHROPIC_API_KEY to see them.</Empty>
              ) : (
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Model</TableCell>
                        <TableCell align="right">Calls</TableCell>
                        <TableCell align="right">p50</TableCell>
                        <TableCell align="right">p95</TableCell>
                        <TableCell align="right">Errors</TableCell>
                        <TableCell align="right">Tokens in / out</TableCell>
                        <TableCell align="right">Cost</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {Object.entries(m.by_model).map(([k, s]) => (
                        <TableRow key={k}>
                          <TableCell className="mono">{k}</TableCell>
                          <TableCell align="right">{s.calls}</TableCell>
                          <TableCell align="right">{ms(s.p50_ms)}</TableCell>
                          <TableCell align="right">{ms(s.p95_ms)}</TableCell>
                          <TableCell align="right">{pct(s.error_rate)}</TableCell>
                          <TableCell align="right">
                            {s.input_tokens.toLocaleString()} / {s.output_tokens.toLocaleString()}
                          </TableCell>
                          <TableCell align="right">${s.cost_usd.toFixed(4)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Panel>
          </>
        )}
        <Panel title="Recent runs">
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Time</TableCell>
                  <TableCell>Feature</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Duration</TableCell>
                  <TableCell align="right">LLM calls</TableCell>
                  <TableCell align="right">Cost</TableCell>
                  <TableCell>Flags</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {runs.map((r) => (
                  <Fragment key={r.id}>
                    <TableRow className="clickable" selected={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
                      <TableCell className="mono">{new Date(r.started_at * 1000).toLocaleTimeString()}</TableCell>
                      <TableCell className="mono">{r.kind}</TableCell>
                      <TableCell>
                        <Tag tone={r.status === "ok" ? "ok" : "err"}>{r.status}</Tag>
                      </TableCell>
                      <TableCell align="right">{ms(r.duration_ms)}</TableCell>
                      <TableCell align="right">{r.llm_calls}</TableCell>
                      <TableCell align="right">${r.cost_usd.toFixed(4)}</TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={0.5}>
                          {r.fallback_used ? <Tag tone="warn">fallback</Tag> : null}
                          {r.needs_review ? <Tag tone="info">review</Tag> : null}
                        </Stack>
                      </TableCell>
                    </TableRow>
                    {open === r.id && (
                      <TableRow>
                        <TableCell colSpan={7}>
                          <ol className="timeline">
                            {spans.map((s) => (
                              <li key={s.id}>
                                <span className={`kind ${s.kind}`}>{s.kind}</span>
                                <span>
                                  {s.name}
                                  {s.model && <span className="mono muted"> · {s.model}</span>}
                                  {s.error && <span style={{ color: "var(--err)", fontSize: 13 }}> {s.error}</span>}
                                </span>
                                <span className="meta">
                                  {ms(s.duration_ms)}
                                  {s.input_tokens + s.output_tokens > 0 && ` · ${s.input_tokens}/${s.output_tokens} tok`}
                                  {s.cost_usd > 0 && ` · $${s.cost_usd.toFixed(4)}`}
                                </span>
                              </li>
                            ))}
                          </ol>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {runs.length === 0 && <Empty>No runs yet. Analyze a sample first.</Empty>}
        </Panel>
      </Stack>
    </main>
  );
}
