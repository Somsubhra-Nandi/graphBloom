import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";
import "./globals.css";

const font = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"], axes: ["opsz", "wdth"] });

export const metadata: Metadata = {
  title: "GraphBloom",
  description: "A knowledge graph that finds out which facts it is missing, from the questions it fails.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${font.variable} dark h-full antialiased`}>
      <head>
        {/* start the graph download with the HTML, before any script runs; phones skip it */}
        <link rel="preload" as="fetch" href="data/graph.json" crossOrigin="anonymous" media="(min-width: 768px)" />
        <link rel="preload" as="fetch" href="data/stories.json" crossOrigin="anonymous" />
      </head>
      <body className="min-h-full bg-background font-sans text-foreground">{children}</body>
    </html>
  );
}
