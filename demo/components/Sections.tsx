"use client";

import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import type { Curve, Metrics } from "@/lib/types";

// the chart is drawn at its real pixel width, so text stays readable on a phone
function useWidth(initial = 640) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.round(el.clientWidth)));
    ro.observe(el);
    setW(Math.round(el.clientWidth));
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Block({ id, title, sentence, number, unit, children, note }: { id?: string; title: string; sentence: string; number: string; unit: string; children: React.ReactNode; note?: string }) {
  return (
    <section id={id} className="mx-auto grid max-w-6xl gap-10 px-5 py-14 sm:px-8 sm:py-20 lg:grid-cols-[minmax(0,420px)_1fr] lg:gap-16 lg:py-28">
      <div>
        <h2 className="text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{title}</h2>
        <p className="mt-4 max-w-sm text-pretty text-[17px] leading-relaxed text-muted-foreground">{sentence}</p>
        <p className="mt-8 text-6xl font-semibold tracking-tight text-primary tnum sm:text-7xl">{number}</p>
        <p className="mt-2 max-w-sm text-[15px] leading-snug text-muted-foreground">{unit}</p>
      </div>
      <div className="min-w-0">
        {children}
        {note && <p className="mt-6 max-w-xl text-pretty text-[15px] leading-relaxed text-muted-foreground">{note}</p>}
      </div>
    </section>
  );
}

export function CurveSection({ curve }: { curve: Curve }) {
  const [box, W] = useWidth();
  const narrow = W < 520;
  const H = narrow ? 280 : 340, L = 40, R = narrow ? 104 : 150, T = 16, B = 34;
  const lo = 0.2, hi = 0.65;
  const x = (i: number) => L + (i / 5) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = (em: number[]) => em.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const learned = curve.series[0], randoms = curve.series.slice(1);
  const stat = curve.baselines.find((b) => b.key === "static_graph")!, bm = curve.baselines.find((b) => b.key === "bm25")!, ov = curve.baselines.find((b) => b.key === "open_vocab")!;
  const draw = { initial: { pathLength: 0 }, whileInView: { pathLength: 1 }, viewport: { once: true, margin: "-5%" }, transition: { duration: 1.6, ease: "easeOut" as const } };
  const tag = (yy: number, text: string, fill: string, weight = 400) => <text x={x(5) + 10} y={yy} fontSize={narrow ? 12 : 13} fill={fill} fontWeight={weight} dominantBaseline="middle">{text}</text>;
  return (
    <Block
      id="curve"
      title="Gets better as it's used"
      sentence={`Each round, it studies the questions it got wrong and adds only the links they were missing. Scored on ${curve.n_questions} questions it never trained on.`}
      number={`${pct(learned.em[0])} → ${pct(learned.em[5])}`}
      unit="questions answered exactly right, before and after five rounds"
      note={`Choosing the missing links at random also helps (${pct(randoms[0].em[5])} and ${pct(randoms[1].em[5])}), so most of the gain comes from adding the right kind of link at all; learning from failures gets there faster. A version told the right link types up front scored ${pct(ov.em)}, which is within the noise of ${pct(learned.em[5])} at this sample size.`}
    >
      <div ref={box}>
      <svg width={W} height={H + 4} className="block" role="img" aria-label="Held-out accuracy per iteration for learned, random, static and BM25">
        {[0.2, 0.3, 0.4, 0.5, 0.6].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="#1f2837" />
            <text x={L - 8} y={y(g)} textAnchor="end" dominantBaseline="middle" fontSize={12} fill="#9aa4b6">{pct(g)}</text>
          </g>
        ))}
        {[0, 1, 2, 3, 4, 5].map((i) => <text key={i} x={x(i)} y={H - 10} textAnchor="middle" fontSize={12} fill="#9aa4b6">{i}</text>)}
        <text x={(L + W - R) / 2} y={H + 2} textAnchor="middle" fontSize={12} fill="#9aa4b6" />
        <line x1={x(0)} x2={x(5)} y1={y(bm.em)} y2={y(bm.em)} stroke="#8b95a7" strokeDasharray="2 5" />
        <line x1={x(0)} x2={x(5)} y1={y(stat.em)} y2={y(stat.em)} stroke="#8b95a7" strokeDasharray="6 5" />
        {randoms.map((s) => <motion.path key={s.key} d={path(s.em)} fill="none" stroke="#9aa6bd" strokeWidth={1.8} strokeOpacity={0.75} {...draw} />)}
        <motion.path d={path(learned.em)} fill="none" stroke="var(--primary)" strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" {...draw} />
        {learned.em.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={3.5} fill="var(--primary)" />)}
        <circle cx={x(5)} cy={y(ov.em)} r={5} fill="none" stroke="#e8ebf1" strokeWidth={1.5} />
        {tag(y(learned.em[5]) - 9, "Learned", "var(--primary)", 600)}
        {tag(y(randoms[0].em[5]) + 10, "Random picks", "#9aa6bd")}
        {tag(y(ov.em) - 1, "Told up front", "#e8ebf1")}
        {tag(y(stat.em) + 6, "Never learns", "#8b95a7")}
        {tag(y(bm.em), "Keyword search", "#8b95a7")}
      </svg>
      </div>
      <p className="mt-2 text-[13px] leading-snug text-muted-foreground">Horizontal axis: learning iteration. Vertical axis: exact-match accuracy on held-out questions.</p>
    </Block>
  );
}

const usd = (v: number) => (v >= 100 ? `$${Math.round(v).toLocaleString()}` : v >= 10 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`);
const docsLabel = (n: number) => (n >= 1e6 ? `${n / 1e6}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`);

export function CostSection({ metrics }: { metrics: Metrics }) {
  const pr = metrics.projection;
  const rows = metrics.cost.per_1000_queries;
  const [learned, rand, , open] = rows;
  const at = (docs: number, q: number) => pr.totals.find((t) => t.documents === docs && t.queries === q)!;
  const head = at(1_000_000, 10_000);
  const saving = 1 - head.ours_total / head.full_extraction_total;
  const crossDocs = Math.round(pr.ours_extra_by_queries["10000"] / (pr.scaling[24].full_extra_batch / pr.scaling[24].documents) / 1000) * 1000;

  const [box, W] = useWidth();
  const narrow = W < 520;
  const H = narrow ? 290 : 340, L = 50, R = narrow ? 92 : 124, T = 14, B = 40;
  const x0 = Math.log10(pr.scaling[0].documents), x1 = Math.log10(1_000_000);
  const y0 = Math.log10(0.5), y1 = Math.log10(2000);
  const x = (d: number) => L + ((Math.log10(d) - x0) / (x1 - x0)) * (W - L - R);
  const y = (v: number) => T + (1 - (Math.log10(v) - y0) / (y1 - y0)) * (H - T - B);
  const full = pr.scaling.map((p, i) => `${i ? "L" : "M"}${x(p.documents)},${y(p.full_extra_batch)}`).join(" ");
  const qs: { q: string; label: string; accent: boolean }[] = [
    { q: "10000", label: "10k questions", accent: true },
    { q: "100000", label: "100k", accent: false },
    { q: "1000000", label: "1M", accent: false },
  ];
  const draw = { initial: { pathLength: 0 }, whileInView: { pathLength: 1 }, viewport: { once: true, margin: "-5%" }, transition: { duration: 1.4, ease: "easeOut" as const } };
  return (
    <Block
      id="cost"
      title="Pays only for what's asked"
      sentence="Extracting every relation from every document costs more as the library grows. Ours costs more as the questions grow."
      number={`${Math.round(saving * 100)}% less`}
      unit={`than extracting everything first, for ${(10_000).toLocaleString()} questions over 1 million documents (${usd(head.ours_total)} against ${usd(head.full_extraction_total)})`}
      note={`The chart counts only the extra cost of the 14 relations the first pass skips; both approaches pay for the same shallow first pass. At our own ${pr.scaling[0].documents.toLocaleString()} documents, extracting everything up front is cheaper. Ours pulls ahead past roughly ${crossDocs.toLocaleString()} documents at 10,000 questions, and falls behind once the questions asked exceed about ${(Math.round(pr.break_even_queries["1000000"] / 1000) * 1000).toLocaleString()} over 1 million documents. Projected linearly from measured costs, using the cheaper batch rate for ingest.`}
    >
      <div ref={box}>
      <svg width={W} height={H + 4} className="block" role="img" aria-label="Extra extraction cost as the number of documents grows, for full extraction and for question-driven extraction">
        {[1, 10, 100, 1000].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="#1f2837" />
            <text x={L - 8} y={y(g)} textAnchor="end" dominantBaseline="middle" fontSize={12} fill="#9aa4b6">{usd(g)}</text>
          </g>
        ))}
        {[2000, 10_000, 100_000, 1_000_000].map((d) => (
          <text key={d} x={x(d)} y={H - 18} textAnchor="middle" fontSize={12} fill="#9aa4b6">{docsLabel(d)}</text>
        ))}
        <text x={(L + W - R) / 2} y={H - 3} textAnchor="middle" fontSize={12} fill="#9aa4b6">documents</text>
        {qs.map((s) => {
          const v = pr.ours_extra_by_queries[s.q];
          return (
            <g key={s.q}>
              <motion.line x1={x(pr.scaling[0].documents)} x2={x(1_000_000)} y1={y(v)} y2={y(v)} stroke={s.accent ? "var(--primary)" : "#8b95a7"} strokeWidth={s.accent ? 3 : 1.6} strokeDasharray={s.accent ? undefined : "5 5"} {...draw} />
              <text x={x(1_000_000) + 8} y={y(v)} fontSize={12} fill={s.accent ? "var(--primary)" : "#9aa6bd"} fontWeight={s.accent ? 600 : 400} dominantBaseline="middle">{s.label}</text>
            </g>
          );
        })}
        <motion.path d={full} fill="none" stroke="#e8ebf1" strokeWidth={3} strokeLinecap="round" {...draw} />
        <text x={x(1_000_000) + 8} y={y(pr.scaling[24].full_extra_batch)} fontSize={12} fill="#e8ebf1" fontWeight={600} dominantBaseline="middle">Extract all</text>
        {[100_000, 1_000_000].map((d) => {
          const v = pr.scaling[24].full_extra_batch * (d / 1_000_000);
          return <g key={d}><circle cx={x(d)} cy={y(v)} r={4} fill="#e8ebf1" /><text x={x(d) - 8} y={y(v) - 10} textAnchor="end" fontSize={12} fill="#e8ebf1">{usd(v)}</text></g>;
        })}
      </svg>
      </div>
      <p className="mt-2 text-[13px] leading-snug text-muted-foreground">Extra cost of the 14 relations beyond the shallow first pass. White: extract all 22 relations up front, which grows with documents. Green: extract only what questions need, which grows with questions asked and not with documents.</p>

      <div id="who-for" className="mt-8 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-[15px] font-semibold text-primary">Who it is for</p>
          <p className="mt-1 text-[15px] leading-relaxed text-muted-foreground">Large collections where most documents are rarely asked about: legal discovery, enterprise archives, research libraries.</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-[15px] font-semibold">Who it is not for</p>
          <p className="mt-1 text-[15px] leading-relaxed text-muted-foreground">Small collections that are asked about heavily. There, extracting everything up front is cheaper.</p>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-border bg-card p-4">
        <p className="text-[15px] font-semibold">Per 1,000 questions</p>
        <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1 tnum text-sm">
          <span>Learned <b className="text-primary">${learned.recurring_usd.toFixed(2)}</b></span>
          <span className="text-muted-foreground">Random <b className="text-foreground">${rand.recurring_usd.toFixed(2)}</b></span>
          <span className="text-muted-foreground">Open vocabulary <b className="text-foreground">${open.recurring_usd.toFixed(2)}</b></span>
        </div>
        <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">The learned policy pays slightly more per question because it extracts more of what questions need.</p>
      </div>
    </Block>
  );
}

export function LatencySection({ lt }: { lt: Metrics["load_test"] }) {
  const bars = [
    { label: "Quiet", p50: lt.quiet.p50_ms, p95: lt.quiet.p95_ms },
    { label: "While writing", p50: lt.busy.p50_ms, p95: lt.busy.p95_ms },
  ];
  const max = 240;
  return (
    <Block
      id="latency"
      title="Fast under load"
      sentence={`${lt.concurrent_queries} questions at once, while ${lt.writer.nodes_per_second.toLocaleString()} new facts a second are written into the same graph, for two minutes.`}
      number={`${lt.busy.p95_ms} ms`}
      unit={`slowest 5% of lookups under load; typical (median) ${lt.busy.p50_ms} ms; ${lt.busy.errors} errors in ${lt.busy.n.toLocaleString()} questions`}
      note="Measured on the graph alone: the language model was replaced by saved answers. A real question adds one to three seconds for the model."
    >
      <div className="space-y-7">
        {bars.map((b) => (
          <div key={b.label}>
            <p className="mb-2 text-sm text-muted-foreground">{b.label}</p>
            {[{ k: "Median", v: b.p50, c: "#6c7a96" }, { k: "Slowest 5%", v: b.p95, c: "var(--primary)" }].map((m) => (
              <div key={m.k} className="mb-1.5 flex items-center gap-3">
                <span className="w-24 shrink-0 text-[13px] text-muted-foreground">{m.k}</span>
                <div className="flex-1"><motion.div className="h-5 origin-left rounded-sm" style={{ width: `${(m.v / max) * 100}%`, background: m.c }} initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true, margin: "-5%" }} transition={{ duration: 0.8, ease: "easeOut" }} /></div>
                <span className="tnum w-16 shrink-0 text-right text-sm">{m.v} ms</span>
              </div>
            ))}
          </div>
        ))}
        <div>
          <p className="mb-2 text-sm text-muted-foreground">Slowest 5%, in each 30 seconds of the writing test</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {lt.windows.map((w) => (
              <div key={w.seconds} className="rounded-md border border-border px-3 py-2 text-center">
                <div className="tnum text-base font-medium">{w.read_p95_ms} ms</div>
                <div className="text-[13px] text-muted-foreground">{w.seconds} s</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Block>
  );
}

export function HowItWorks({ before, after }: { before: number; after: number }) {
  const steps = [
    { t: "Read", s: "The documents are read once into a small graph with a few kinds of link." },
    { t: "Ask", s: "Practice questions are answered by following links. A missing link is a dead end." },
    { t: "Fix", s: "For each dead end, the source text is re-read for that one kind of link and the result is added." },
    { t: "Check", s: "The new graph is scored on questions it has never seen." },
  ];
  const g = "#46526a";
  const glyph = [
    <g key="a"><circle cx="20" cy="30" r="5" fill={g} /><circle cx="60" cy="16" r="5" fill={g} /><circle cx="60" cy="44" r="5" fill={g} /><circle cx="100" cy="30" r="5" fill={g} /><path d="M20 30L60 16M20 30L60 44M60 16L100 30" stroke={g} strokeWidth="1.5" /></g>,
    <g key="b"><circle cx="20" cy="30" r="5" fill="#e8ebf1" /><circle cx="60" cy="30" r="5" fill={g} /><circle cx="100" cy="30" r="6" fill="var(--bad)" /><path d="M20 30L60 30" stroke={g} strokeWidth="1.5" /><path d="M60 30L92 30" stroke="var(--bad)" strokeWidth="1.5" strokeDasharray="3 3" /></g>,
    <g key="c"><circle cx="20" cy="30" r="5" fill={g} /><circle cx="60" cy="30" r="5" fill={g} /><circle cx="100" cy="30" r="5" fill="var(--primary)" /><path d="M20 30L60 30" stroke={g} strokeWidth="1.5" /><path d="M60 30L100 30" stroke="var(--primary)" strokeWidth="2.5" /></g>,
    <g key="d"><path d="M16 46L44 36L72 28L104 14" stroke="var(--primary)" strokeWidth="2.5" fill="none" /><circle cx="104" cy="14" r="5" fill="var(--primary)" /><path d="M16 50H104" stroke={g} strokeDasharray="3 4" /></g>,
  ];
  return (
    <section id="how" className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20 lg:py-28">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr] lg:gap-16">
        <div>
          <h2 className="text-3xl font-semibold leading-tight sm:text-4xl">How it works</h2>
          <p className="mt-4 max-w-sm text-[17px] leading-relaxed text-muted-foreground">It starts with a shallow graph and deepens it only where questions get stuck.</p>
          <p className="mt-8 text-6xl font-semibold tracking-tight text-primary tnum sm:text-7xl">{before} → {after}</p>
          <p className="mt-1 text-sm text-muted-foreground">kinds of link in the graph, after five rounds</p>
        </div>
        <ol className="grid gap-4 sm:grid-cols-2 lg:self-end">
          {steps.map((s, i) => (
            <li key={s.t} className="rounded-xl border border-border bg-card p-4">
              <svg viewBox="0 0 120 60" className="mb-3 h-14 w-full" aria-hidden>{glyph[i]}</svg>
              <p className="font-semibold"><span className="text-muted-foreground tnum">{i + 1}. </span>{s.t}</p>
              <p className="mt-1 text-[15px] leading-relaxed text-muted-foreground">{s.s}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
