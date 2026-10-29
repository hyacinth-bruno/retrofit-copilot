"use client";

import SearchIcon from "@mui/icons-material/Search";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import InputAdornment from "@mui/material/InputAdornment";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useState } from "react";
import { Citations, Issues, PageHeader, Panel, Tag, type Tone } from "../components";
import { post, type Answer } from "@/lib/api";

const EXAMPLES = [
  "How does the iSFP bonus work after the July 2026 reform?",
  "Which grant rate does a landlord get for a heat pump?",
  "Wie hoch ist die Förderung für eine Fassadendämmung?",
  "How much can I raise the rent after a retrofit?",
  "What is the weather in Berlin tomorrow?",
];

const MODE: Record<Answer["mode"], { label: string; tone: Tone }> = {
  llm: { label: "grounded answer", tone: "ok" },
  extractive_fallback: { label: "extractive fallback", tone: "warn" },
  refused: { label: "not in sources", tone: "info" },
};

export default function AskPage() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<{ q: string; a?: Answer; error?: string }[]>([]);

  async function ask(question: string) {
    if (question.trim().length < 3) return;
    setBusy(true);
    setQ("");
    setHistory((h) => [{ q: question }, ...h]);
    try {
      const a = await post<Answer>("/api/ask", { question });
      setHistory((h) => [{ q: question, a }, ...h.slice(1)]);
    } catch (e) {
      setHistory((h) => [{ q: question, error: (e as Error).message }, ...h.slice(1)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <PageHeader eyebrow="Ask" title="Ask the funding knowledge base">
        Hybrid search (dense + BM25, fused with RRF) over BEG, KfW, GEG and tenancy rules. Answers must cite retrieved sources
        or they are withheld.
      </PageHeader>
      <Stack spacing={3}>
        <Panel>
          <Stack
            component="form"
            direction="row"
            spacing={1}
            onSubmit={(e) => {
              e.preventDefault();
              ask(q);
            }}
          >
            <TextField
              id="q"
              fullWidth
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ask in English or German"
              slotProps={{
                htmlInput: { "aria-label": "Question" },
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon sx={{ color: "primary.main" }} />
                    </InputAdornment>
                  ),
                },
              }}
            />
            <Button variant="contained" type="submit" disabled={busy} sx={{ px: 3 }}>
              {busy ? "Searching…" : "Ask"}
            </Button>
          </Stack>
          <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.75 }}>
            {EXAMPLES.map((e) => (
              <Button key={e} size="small" variant="outlined" onClick={() => ask(e)} disabled={busy} sx={{ fontWeight: 400, textAlign: "left" }}>
                {e}
              </Button>
            ))}
          </Stack>
        </Panel>
        {history.map((h, i) => (
          <Panel key={i} title={h.q} action={h.a && <Tag tone={MODE[h.a.mode].tone}>{MODE[h.a.mode].label}</Tag>}>
            {!h.a && !h.error && (
              <Stack spacing={1}>
                <LinearProgress />
                <Typography variant="body2" color="text.secondary">
                  Retrieving sources…
                </Typography>
              </Stack>
            )}
            {h.error && (
              <Alert severity="error" variant="outlined">
                {h.error}
              </Alert>
            )}
            {h.a && (
              <>
                <Typography className="answer">{h.a.answer}</Typography>
                {h.a.issues.length > 0 && <Issues issues={h.a.issues} />}
                <Citations items={h.a.citations} />
              </>
            )}
          </Panel>
        ))}
      </Stack>
    </main>
  );
}
