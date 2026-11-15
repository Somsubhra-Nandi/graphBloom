import MotionProvider from "@/components/MotionProvider";
import PilotLink from "@/components/PilotLink";
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
      <section className="mx-auto max-w-6xl px-5 pb-10 sm:px-8">
        <div className="flex flex-col gap-5 rounded-2xl border border-border bg-card p-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-lg font-semibold">Roadmap</p>
            <p className="mt-1 max-w-xl text-[15px] leading-relaxed text-muted-foreground">Next: learn from user thumbs-down, and from dead ends, without labelled feedback questions.</p>
          </div>
          <PilotLink label="Request a pilot" />
        </div>
      </section>
      <footer className="mx-auto max-w-6xl px-5 pb-16 text-[15px] leading-relaxed text-muted-foreground sm:px-8">
        Results from 87 held-out questions of the 2WikiMultihopQA benchmark, one split. Differences of a few points are within noise at this size.
      </footer>
    </main>
    </MotionProvider>
  );
}
