"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import GraphStage from "@/components/GraphStage";
import MiniCurve from "@/components/MiniCurve";
import MobileHero from "@/components/MobileHero";
import PilotLink from "@/components/PilotLink";
import type { Curve, GraphData, Mutation, StageState, Story } from "@/lib/types";

type Data = { graph: GraphData | null; stories: Story[]; curve: Curve; mutations: Mutation[] };

const pct = (v: number) => `${Math.round(v * 100)}%`;

function caption(s: Story, st: StageState, curve: Curve) {
  const rel = s.before.dead_end.missing_relation;
  const em = curve.series[0].em;
  switch (st.phase) {
    case "question": return { head: "A question the graph has not seen before.", tone: "" };
    case "walk": return { head: `Following the links: ${s.plan.join(", then ")}.`, tone: "" };
    case "deadend": return { head: `Dead end. The graph has no "${rel}" link for ${s.before.dead_end.name}.`, tone: "bad", sub: `It answered: "${s.before.answer.length > 90 ? s.before.answer.slice(0, 88) + "…" : s.before.answer}"` };
    case "grow": return { head: `The missing link ("${rel}") is read from the source text and added.`, tone: "good" };
    case "complete": return { head: "The path now reaches an answer.", tone: "good", sub: `Answer: ${s.after.answer}` };
    case "tick":
    case "rest": return { head: `Held-out accuracy ${pct(em[0])} → ${pct(em[s.fixed_iter])} by iteration ${s.fixed_iter}.`, tone: "good" };
    default: return { head: "", tone: "" };
  }
}

export default function Hero() {
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState(false);
  const [mode, setMode] = useState<"story" | "replay">("story");
  const [iter, setIter] = useState(0);
  const [st, setSt] = useState<StageState>({ story: 0, phase: "question", graphIter: 0, curveIter: 0 });
  const [ready, setReady] = useState(false);
  const [narrow, setNarrow] = useState<boolean | null>(null);
  const [showFps, setShowFps] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setShowFps(new URLSearchParams(location.search).has("fps"));
    const small = window.matchMedia("(max-width: 767px)").matches;
    setNarrow(small);
    const get = (n: string) => fetch(`data/${n}.json`).then((r) => r.json());
    // phones skip the 500 KB graph file: they get a still frame instead
    Promise.all([small ? Promise.resolve(null) : get("graph"), get("stories"), get("curve"), get("mutations")])
      .then(([graph, stories, curve, mutations]) => setData({ graph, stories, curve, mutations }))
      .catch(() => setErr(true));
  }, []);

  const stop = () => { if (timer.current) clearInterval(timer.current); timer.current = null; };
  useEffect(() => stop, []);

  const replay = useCallback(() => {
    stop();
    setMode("replay");
    setIter(0);
    let i = 0;
    timer.current = setInterval(() => {
      i += 1;
      setIter(i);
      if (i >= 5) stop();
    }, 1700);
  }, []);
  const backToStories = () => { stop(); setMode("story"); };
  const onState = useCallback((s: StageState) => setSt(s), []);

  if (narrow && data) return <MobileHero story={data.stories[0]} curve={data.curve} />;

  const added = (it: number) => data?.mutations.filter((m) => m.kind === "schema_growth" && m.iteration === it).map((m) => m.relation) ?? [];
  const linksAt = (it: number) => {
    if (!data) return 0;
    const by = data.graph?.counts.edges_by_iter ?? {};
    return Object.entries(by).filter(([k]) => +k <= it).reduce((a, [, v]) => a + v, 0);
  };

  const story = data && st.story >= 0 ? data.stories[st.story] : null;
  const cap = story && mode === "story" ? caption(story, st, data!.curve) : null;
  const shownIter = mode === "replay" ? iter : st.curveIter;

  return (
    <section className="relative h-[100svh] min-h-[680px] w-full overflow-hidden bg-[radial-gradient(ellipse_at_50%_40%,#111826_0%,#090c12_70%)]">
      {data && data.graph && <GraphStage graph={data.graph} stories={data.stories} mode={mode} iter={iter} onState={onState} onReady={() => setReady(true)} showFps={showFps} />}

      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 p-5 sm:p-8">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium tracking-wide text-muted-foreground">GraphBloom</p>
          <PilotLink className="pointer-events-auto" />
        </div>
        <h1 className="mt-2 max-w-xl text-balance text-3xl font-semibold leading-[1.08] tracking-tight sm:text-5xl" style={{ fontStretch: "92%" }}>
          A knowledge graph that finds out which facts it is missing.
        </h1>
        <p className="mt-3 max-w-md text-pretty text-base leading-relaxed text-muted-foreground">
          Each dot is something named in the documents; each line is a fact about it. Watch it fail a question, learn the missing fact, and get the answer right.
        </p>
      </header>

      {!ready && !err && (
        <div className="absolute inset-0 z-10 grid place-items-center text-sm text-muted-foreground">Laying out {data?.graph ? data.graph.counts.entities - data.graph.counts.isolated : ""} entities…</div>
      )}
      {err && <div className="absolute inset-0 z-10 grid place-items-center text-sm text-destructive">The data files could not be loaded. Run scripts/export_demo.py and rebuild.</div>}

      {data && (
        <div className="absolute inset-x-0 bottom-0 z-10 grid gap-3 p-4 sm:p-8 lg:grid-cols-[minmax(0,430px)_1fr_minmax(0,300px)] lg:items-end">
          <div className="rounded-xl border border-border bg-card/85 p-4 backdrop-blur-md">
            {mode === "story" && story ? (
              <>
                <div className="mb-2 flex gap-1.5" aria-label={`Example ${st.story + 1} of ${data.stories.length}`}>
                  {data.stories.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full ${i === st.story ? "bg-primary" : "bg-muted"}`} />)}
                </div>
                <p className="text-[17px] font-medium leading-snug">{story.question}</p>
                <AnimatePresence mode="wait">
                  <motion.div key={st.phase} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} className="mt-3 min-h-[3.6rem] text-sm leading-relaxed">
                    <p className={cap?.tone === "bad" ? "font-semibold text-[var(--bad)]" : cap?.tone === "good" ? "font-semibold text-[var(--good)]" : "text-muted-foreground"}>{cap?.head}</p>
                    {cap?.sub && <p className="mt-1 text-muted-foreground">{cap.sub}</p>}
                  </motion.div>
                </AnimatePresence>
              </>
            ) : (
              <>
                <p className="text-[17px] font-medium">Replaying five rounds of learning</p>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {iter === 0 ? "The starting graph, read once from the documents." : <>Round {iter} added links for: <span className="text-foreground">{added(iter).join(", ") || "nothing new"}</span>.</>}
                </p>
                <p className="mt-1 text-sm text-muted-foreground tnum">{linksAt(iter).toLocaleString()} links, {linksAt(iter) - linksAt(0)} learned.</p>
              </>
            )}
          </div>

          <div className="mx-auto w-full max-w-md rounded-xl border border-border bg-card/85 p-4 backdrop-blur-md">
            <div className="mb-3 flex items-center justify-between gap-3">
              <Button onClick={replay}>Replay learning</Button>
              {mode === "replay" && <button className="-mr-2 rounded-md px-2 py-2 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-primary" onClick={backToStories}>Back to examples</button>}
            </div>
            <Slider min={0} max={5} step={1} value={[shownIter]} onValueChange={(v) => { stop(); setMode("replay"); setIter(Array.isArray(v) ? v[0] : v); }} aria-label="Learning iteration" />
            <div className="mt-2 flex justify-between text-xs text-muted-foreground tnum">
              {[0, 1, 2, 3, 4, 5].map((i) => <span key={i} className={i === shownIter ? "text-foreground" : ""}>{i}</span>)}
            </div>
            <p className="mt-1 text-center text-xs text-muted-foreground">Iteration</p>
          </div>

          <div className="hidden rounded-xl border border-border bg-card/85 p-4 backdrop-blur-md sm:block">
            <MiniCurve curve={data.curve} iter={shownIter} />
          </div>
        </div>
      )}
    </section>
  );
}
