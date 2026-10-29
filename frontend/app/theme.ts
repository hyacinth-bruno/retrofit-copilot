"use client";

import { alpha, createTheme } from "@mui/material/styles";

// "Crystal water": deep ocean base, frosted glass surfaces, aqua light. Semantic colours stay distinct from the accent.
const aqua = "#5ce1e6";
const lagoon = "#3b9cff";
const deep = "#04131f";

const glass = {
  background: `linear-gradient(160deg, ${alpha("#9fe9ff", 0.09)} 0%, ${alpha("#5ab8ff", 0.04)} 45%, ${alpha("#0b2a3d", 0.28)} 100%)`,
  backdropFilter: "blur(18px) saturate(140%)",
  WebkitBackdropFilter: "blur(18px) saturate(140%)",
  border: `1px solid ${alpha("#bff4ff", 0.14)}`,
  boxShadow: `inset 0 1px 0 ${alpha("#ffffff", 0.12)}, 0 18px 50px -20px ${alpha("#000814", 0.8)}`,
};

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: aqua, contrastText: deep },
    secondary: { main: lagoon },
    success: { main: "#5eeaa8" },
    warning: { main: "#ffc46b" },
    error: { main: "#ff7f8f" },
    info: { main: "#8fb8ff" },
    background: { default: deep, paper: alpha("#0a2233", 0.55) },
    text: { primary: "#e6f8ff", secondary: alpha("#c6e9f5", 0.68) },
    divider: alpha("#bff4ff", 0.12),
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily: "var(--font-sans), system-ui, -apple-system, 'Segoe UI', sans-serif",
    h1: { fontSize: "clamp(26px, 3.2vw, 36px)", fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.15 },
    h2: { fontSize: 17, fontWeight: 600, letterSpacing: "-0.005em" },
    h3: { fontSize: 14, fontWeight: 600 },
    body1: { fontSize: 15, lineHeight: 1.55 },
    body2: { fontSize: 13.5, lineHeight: 1.5 },
    overline: { fontSize: 11, letterSpacing: "0.14em", fontWeight: 500, lineHeight: 1.6 },
    button: { textTransform: "none", fontWeight: 600, letterSpacing: "0.01em" },
  },
  components: {
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { backgroundImage: "none", ...glass } },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          ...glass,
          borderWidth: "0 0 1px 0",
          borderRadius: 0,
          background: alpha("#041824", 0.55),
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 12, paddingInline: 16 },
        containedPrimary: {
          color: deep,
          background: `linear-gradient(120deg, #a5f6ff 0%, ${aqua} 40%, ${lagoon} 100%)`,
          boxShadow: `0 8px 28px -10px ${alpha(aqua, 0.75)}, inset 0 1px 0 ${alpha("#ffffff", 0.6)}`,
          "&:hover": { filter: "brightness(1.08)", boxShadow: `0 10px 34px -8px ${alpha(aqua, 0.9)}` },
          "&.Mui-disabled": { color: alpha(deep, 0.6), background: alpha(aqua, 0.35) },
        },
        outlined: {
          borderColor: alpha("#bff4ff", 0.22),
          background: alpha("#bff4ff", 0.04),
          "&:hover": { borderColor: alpha(aqua, 0.6), background: alpha(aqua, 0.08) },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontFamily: "var(--font-mono), ui-monospace, monospace", fontSize: 11, height: 24, backdropFilter: "blur(8px)" },
        outlined: { borderColor: alpha("#bff4ff", 0.2), background: alpha("#bff4ff", 0.04) },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          background: alpha("#03121c", 0.45),
          borderRadius: 12,
          "& .MuiOutlinedInput-notchedOutline": { borderColor: alpha("#bff4ff", 0.16) },
          "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: alpha(aqua, 0.45) },
          "&.Mui-focused": { boxShadow: `0 0 0 4px ${alpha(aqua, 0.12)}` },
        },
      },
    },
    MuiMenu: {
      styleOverrides: { paper: { background: alpha("#082232", 0.92) } },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 12, backdropFilter: "blur(12px)", alignItems: "center" },
        outlined: { background: alpha("#03121c", 0.35) },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: alpha("#bff4ff", 0.09), paddingLeft: 0, fontSize: 13.5 },
        head: { fontSize: 11, textTransform: "uppercase", letterSpacing: "0.1em", color: alpha("#c6e9f5", 0.6), fontWeight: 500 },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { minHeight: 40, borderRadius: 10, zIndex: 1, color: alpha("#c6e9f5", 0.7), "&.Mui-selected": { color: "#e6f8ff" } },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: { minHeight: 40 },
        indicator: {
          height: "100%",
          borderRadius: 10,
          background: `linear-gradient(120deg, ${alpha(aqua, 0.22)}, ${alpha(lagoon, 0.18)})`,
          boxShadow: `inset 0 0 0 1px ${alpha(aqua, 0.35)}, 0 0 24px -6px ${alpha(aqua, 0.6)}`,
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 4, height: 3, background: alpha(aqua, 0.12) },
        bar: { background: `linear-gradient(90deg, ${aqua}, ${lagoon})` },
      },
    },
    MuiAccordion: {
      defaultProps: { disableGutters: true },
      styleOverrides: {
        root: {
          background: alpha("#03121c", 0.3),
          backdropFilter: "none",
          boxShadow: "none",
          borderRadius: "12px !important",
          "&::before": { display: "none" },
        },
      },
    },
  },
});

export default theme;
