import type { Metadata } from "next";
import { JetBrains_Mono, Sora } from "next/font/google";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v14-appRouter";
import "./globals.css";
import Nav from "./nav";
import Providers from "./providers";

const sans = Sora({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Retrofit Copilot",
  description: "AI copilot for energy retrofits of multi-family buildings",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <AppRouterCacheProvider>
          <Providers>
            {/* Ambient water: drifting light pools plus a slow caustic shimmer. Purely decorative. */}
            <div className="ocean" aria-hidden="true">
              <span className="pool p1" />
              <span className="pool p2" />
              <span className="pool p3" />
              <span className="caustics" />
            </div>
            <Nav />
            <div className="shell">{children}</div>
          </Providers>
        </AppRouterCacheProvider>
      </body>
    </html>
  );
}
