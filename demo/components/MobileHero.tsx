import PilotLink from "@/components/PilotLink";
import type { Curve, Story } from "@/lib/types";

const pct = (v: number) => `${Math.round(v * 100)}%`;

// Phones get a still frame and the same story as three steps; the 3D graph stays on larger screens.
export default function MobileHero({ story, curve }: { story: Story; curve: Curve }) {
  const rel = story.before.dead_end.missing_relation;
  const em = curve.series[0].em;
  const steps = [
    { tone: "text-muted-foreground", dot: "bg-foreground", head: "The question", body: story.question },
    { tone: "text-[var(--bad)]", dot: "bg-[var(--bad)]", head: `Dead end: missing fact "${rel}"`, body: `The graph has no "${rel}" link for ${story.before.dead_end.name}.` },
    { tone: "text-[var(--good)]", dot: "bg-[var(--good)]", head: `Fixed in iteration ${story.fixed_iter}`, body: `The link is read from the source text. Answer: ${story.after.answer}` },
  ];
  return (
    <section className="relative w-full overflow-hidden bg-background">
      <div className="absolute inset-0 bg-cover bg-center opacity-50" style={{ backgroundImage: "url(graph-still.jpg)" }} aria-hidden />
      <div className="absolute inset-0 bg-gradient-to-b from-background/70 via-background/20 to-background" aria-hidden />
      <div className="relative px-4 pb-8 pt-6">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-muted-foreground">GraphBloom</p>
          <PilotLink />
        </div>
        <h1 className="mt-2 text-balance text-[2rem] tracking-tight font-semibold leading-[1.08]" style={{ fontStretch: "92%" }}>A knowledge graph that finds out which facts it is missing.</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">Each dot is something named in the documents; each line is a fact about it. It fails a question, learns the missing fact, and gets the answer right.</p>
        <ol className="mt-24 space-y-3">
          {steps.map((s) => (
            <li key={s.head} className="rounded-xl border border-border bg-card/90 p-4 backdrop-blur-md">
              <p className={`flex items-center gap-2 text-sm font-semibold ${s.tone}`}><i className={`h-2 w-2 rounded-full ${s.dot}`} />{s.head}</p>
              <p className="mt-1.5 text-[15px] leading-snug">{s.body}</p>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-center text-lg font-semibold text-primary tnum">{pct(em[0])} → {pct(em[5])} on unseen questions</p>
        <p className="mt-3 text-center text-sm text-muted-foreground">View on desktop for the full 3D graph and the replay.</p>
      </div>
    </section>
  );
}
