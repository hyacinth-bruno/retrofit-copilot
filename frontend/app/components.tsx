"use client";

import Chip from "@mui/material/Chip";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { Citation, Issue, Step } from "@/lib/api";

export type Tone = "ok" | "warn" | "err" | "info" | "accent" | "default";

const TONE_COLOR = {
  ok: "success",
  warn: "warning",
  err: "error",
  info: "info",
  accent: "primary",
  default: "default",
} as const;

export function Tag({ tone = "default", children }: { tone?: Tone; children: React.ReactNode }) {
  return <Chip size="small" variant="outlined" color={TONE_COLOR[tone]} label={children} />;
}

export function PageHeader({ eyebrow, title, children, action }: { eyebrow: string; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Stack direction="row" spacing={2} sx={{ justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", rowGap: 2, mb: 3 }} className="rise">
      <Stack spacing={1} sx={{ maxWidth: 760 }}>
        <Typography variant="overline" color="primary">
          {eyebrow}
        </Typography>
        <Typography variant="h1" className="gradient-text">
          {title}
        </Typography>
        {children && (
          <Typography color="text.secondary" component="div">
            {children}
          </Typography>
        )}
      </Stack>
      {action}
    </Stack>
  );
}

export function Panel({ title, icon, action, children, id }: { title?: React.ReactNode; icon?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; id?: string }) {
  return (
    <Paper component="section" aria-labelledby={id} className="rise" sx={{ p: { xs: 2, sm: 3 }, display: "flex", flexDirection: "column", gap: 2.25, minWidth: 0 }}>
      {(title || action) && (
        <Stack direction="row" spacing={1.5} sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
          <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", color: "primary.main" }}>
            {icon}
            <Typography variant="h2" id={id} color="text.primary">
              {title}
            </Typography>
          </Stack>
          {action}
        </Stack>
      )}
      {children}
    </Paper>
  );
}

export function Kpi({ label, value, hint, danger }: { label: string; value: React.ReactNode; hint?: React.ReactNode; danger?: boolean }) {
  return (
    <Paper sx={{ p: 1.75, borderRadius: 3, display: "flex", flexDirection: "column", gap: 0.25, background: "rgba(3,18,28,0.35)" }}>
      <Typography variant="overline" color="text.secondary" sx={{ fontSize: 10 }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 21, fontWeight: 600, fontVariantNumeric: "tabular-nums", color: danger ? "error.main" : "text.primary" }}>{value}</Typography>
      {hint && (
        <Typography variant="body2" color="text.secondary" sx={{ fontSize: 12 }}>
          {hint}
        </Typography>
      )}
    </Paper>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <Typography color="text.secondary" sx={{ py: 1.5, fontSize: 14 }}>
      {children}
    </Typography>
  );
}

export function Issues({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <Typography variant="body2" color="text.secondary">No issues found by the guardrails.</Typography>;
  return (
    <ul className="issues">
      {issues.map((i, n) => (
        <li key={n} className={i.severity}>
          <span>
            <span className="mono muted">{i.code}</span> {i.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Timeline({ steps }: { steps: Step[] }) {
  if (!steps.length) return null;
  return (
    <ol className="timeline">
      {steps.map((s, i) => (
        <li key={i}>
          <span className={`kind ${s.kind}`}>{s.kind}</span>
          <span>
            {s.name}
            {s.status !== "ok" && <span style={{ marginLeft: 6 }}><Tag tone="err">{s.status}</Tag></span>}
            {Boolean(s.meta?.fallback) && <span style={{ marginLeft: 6 }}><Tag tone="warn">fallback model</Tag></span>}
            {s.model && <span className="mono muted"> · {s.model}</span>}
            {Array.isArray(s.meta?.tool_calls) && (s.meta.tool_calls as string[]).length > 0 && (
              <span className="mono muted"> → {(s.meta.tool_calls as string[]).join(", ")}</span>
            )}
            {typeof s.meta?.query === "string" && <span className="mono muted"> “{s.meta.query as string}”</span>}
          </span>
          <span className="meta">
            {s.duration_ms ? `${Math.round(s.duration_ms)} ms` : ""}
            {s.tokens ? ` · ${s.tokens} tok` : ""}
            {s.cost_usd ? ` · $${s.cost_usd.toFixed(4)}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function Citations({ items }: { items: Citation[] }) {
  if (!items.length) return <Typography variant="body2" color="text.secondary">No sources cited.</Typography>;
  return (
    <Stack spacing={1.5}>
      {items.map((c) => (
        <div className="cite" key={c.chunk_id}>
          <span className="id">[{c.chunk_id}]</span>
          <span>
            {c.url ? (
              <a href={c.url} target="_blank" rel="noreferrer">
                {c.title}
              </a>
            ) : (
              c.title
            )}
          </span>
          <span className="muted" style={{ fontSize: 12.5 }}>{c.snippet}…</span>
        </div>
      ))}
    </Stack>
  );
}

export function confidenceChip(conf: number | undefined) {
  if (conf === undefined) return <Tag>no evidence</Tag>;
  const tone = conf >= 0.85 ? "ok" : conf >= 0.7 ? "warn" : "err";
  return <Tag tone={tone}>{Math.round(conf * 100)}%</Tag>;
}
