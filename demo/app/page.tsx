import MotionProvider from "@/components/MotionProvider";
import Hero from "@/components/Hero";
import { CostSection, CurveSection, HowItWorks, LatencySection } from "@/components/Sections";
import { getCurve, getMetrics, getMutations } from "@/lib/data";

export default function Page() {
  const curve = getCurve(), metrics = getMetrics(), mut = getMutations();
  const grown = mut.filter((m) => m.kind === "schema_growth").length;
  return (
    <MotionProvider>
    <main>
      <Hero />
      <CurveSection curve={curve} />
      <CostSection metrics={metrics} />
      <LatencySection lt={metrics.load_test} />
      <HowItWorks before={8} after={8 + grown} />
      <footer className="mx-auto max-w-6xl px-5 pb-16 text-[15px] leading-relaxed text-muted-foreground sm:px-8">
        Results from 87 held-out questions of the 2WikiMultihopQA benchmark, one split. Differences of a few points are within noise at this size.
      </footer>
    </main>
    </MotionProvider>
  );
}
