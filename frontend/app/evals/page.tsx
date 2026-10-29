"use client";

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Alert from "@mui/material/Alert";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { Empty, Kpi, PageHeader, Panel, Tag } from "../components";
import { get } from "@/lib/api";

type Report = {
  available: boolean;
  created_at?: string;
  model?: string;
  duration_s?: number;
  suites?: Record<string, Record<string, unknown>>;
  thresholds?: Record<string, Record<string, number>>;
  failures?: string[];
};

const TITLES: Record<string, string> = {
  retrieval: "Retrieval · offline",
  guardrails: "Guardrails · offline",
  extraction: "Extraction · LLM",
  answers: "Grounded answers · LLM judge",
  planning: "Agent planning · LLM",
};

export default function EvalsPage() {
  const [r, setR] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<Report>("/api/evals/latest").then(setR).catch((e) => setError((e as Error).message));
  }, []);

  return (
    <main>
      <PageHeader eyebrow="Evals" title="Evaluation report">
        Run <span className="mono">python -m evals.run_evals --llm --gate</span> in <span className="mono">backend/</span>. CI
        runs the offline suites on every push and blocks a merge when a metric drops below its threshold.
      </PageHeader>
      <Stack spacing={3}>
        {error && (
          <Alert severity="error" variant="outlined">
            {error}
          </Alert>
        )}
        {r && !r.available && <Empty>No report yet.</Empty>}
        {r?.available && r.suites && (
          <>
            <Stack direction="row" className="mono muted" sx={{ flexWrap: "wrap", gap: 2, alignItems: "center" }}>
              <span>{r.created_at}</span>
              <span>model {r.model}</span>
              <span>{r.duration_s}s</span>
              {r.failures && r.failures.length > 0 ? <Tag tone="err">{r.failures.length} below threshold</Tag> : <Tag tone="ok">all thresholds met</Tag>}
            </Stack>
            {Object.entries(r.suites).map(([name, suite]) => {
              const th = r.thresholds?.[name] ?? {};
              const scalars = Object.entries(suite).filter(([, v]) => typeof v === "number" || typeof v === "string");
              const byMode = suite.by_mode as Record<string, { hit_at_5: number; mrr: number }> | undefined;
              const details = (suite.samples ?? suite.rows) as Record<string, unknown>[] | undefined;
              return (
                <Panel key={name} title={TITLES[name] ?? name}>
                  <div className="kpis">
                    {scalars.map(([k, v]) => {
                      const min = th[k];
                      const fail = typeof v === "number" && min !== undefined && v < min;
                      return <Kpi key={k} label={k.replaceAll("_", " ")} value={String(v)} hint={min !== undefined ? `min ${min}` : undefined} danger={fail} />;
                    })}
                  </div>
                  {byMode && (
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>Search mode</TableCell>
                            <TableCell align="right">hit@5</TableCell>
                            <TableCell align="right">MRR</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {Object.entries(byMode).map(([mode, s]) => (
                            <TableRow key={mode}>
                              <TableCell className="mono">{mode}</TableCell>
                              <TableCell align="right">{s.hit_at_5}</TableCell>
                              <TableCell align="right">{s.mrr}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                  {details && details.length > 0 && (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="overline" color="text.secondary">
                          Per item ({details.length})
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <pre className="mono" style={{ whiteSpace: "pre-wrap", overflowX: "auto", margin: 0 }}>
                          {details.map((d) => JSON.stringify(d)).join("\n")}
                        </pre>
                      </AccordionDetails>
                    </Accordion>
                  )}
                </Panel>
              );
            })}
          </>
        )}
      </Stack>
    </main>
  );
}
