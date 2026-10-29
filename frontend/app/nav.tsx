"use client";

import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ForumIcon from "@mui/icons-material/ForumOutlined";
import InsightsIcon from "@mui/icons-material/Insights";
import ScienceIcon from "@mui/icons-material/ScienceOutlined";
import WaterDropIcon from "@mui/icons-material/WaterDrop";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { get, type Health } from "@/lib/api";
import { Tag } from "./components";

const LINKS = [
  { href: "/", label: "Analyze", icon: <AutoAwesomeIcon fontSize="small" /> },
  { href: "/ask", label: "Ask", icon: <ForumIcon fontSize="small" /> },
  { href: "/observability", label: "Observability", icon: <InsightsIcon fontSize="small" /> },
  { href: "/evals", label: "Evals", icon: <ScienceIcon fontSize="small" /> },
];

export default function Nav() {
  const path = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    get<Health>("/health").then(setHealth).catch(() => setDown(true));
  }, []);

  const current = LINKS.some((l) => l.href === path) ? path : false;

  return (
    <AppBar position="sticky" color="transparent">
      <Toolbar sx={{ gap: { xs: 1.5, md: 3 }, flexWrap: "wrap", py: 1.25, maxWidth: 1240, width: "100%", mx: "auto", px: { xs: 2, sm: 3 } }}>
        <Stack direction="row" spacing={1.25} sx={{ alignItems: "center" }}>
          <Box
            sx={{
              width: 34,
              height: 34,
              borderRadius: "11px",
              display: "grid",
              placeItems: "center",
              color: "#04131f",
              background: "linear-gradient(140deg, #c9fbff 0%, #5ce1e6 45%, #3b9cff 100%)",
              boxShadow: "0 0 22px -4px rgba(92,225,230,0.8), inset 0 1px 0 rgba(255,255,255,0.7)",
            }}
          >
            <WaterDropIcon fontSize="small" />
          </Box>
          <Stack sx={{ lineHeight: 1 }}>
            <Typography sx={{ fontWeight: 600, fontSize: 15, letterSpacing: "-0.01em" }}>Retrofit Copilot</Typography>
            <Typography className="mono" sx={{ fontSize: 10, color: "text.secondary", letterSpacing: "0.12em" }}>
              ENERGY · AI · DEMO
            </Typography>
          </Stack>
        </Stack>

        <Tabs value={current} variant="scrollable" scrollButtons={false} aria-label="Main" sx={{ order: { xs: 3, md: 0 }, width: { xs: "100%", md: "auto" } }}>
          {LINKS.map((l) => (
            <Tab key={l.href} value={l.href} label={l.label} icon={l.icon} iconPosition="start" component={Link} href={l.href} />
          ))}
        </Tabs>

        <Stack direction="row" spacing={0.75} sx={{ ml: "auto", flexWrap: "wrap", rowGap: 0.75 }} aria-live="polite">
          {down && <Tag tone="err">API offline</Tag>}
          {health && (
            <>
              <Tag tone={health.llm_enabled ? "ok" : "warn"}>{health.llm_enabled ? health.primary_model : "no API key: fallbacks only"}</Tag>
              <Tag>qdrant {health.qdrant_mode}</Tag>
              <Tag>{health.embeddings}</Tag>
              <Tag>kb {health.kb_chunks}</Tag>
            </>
          )}
        </Stack>
      </Toolbar>
    </AppBar>
  );
}
