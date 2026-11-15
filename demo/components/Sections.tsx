"use client";

import { motion } from "framer-motion";
import type { Curve, CostRow, Metrics } from "@/lib/types";

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Block({ title, sentence, number, unit, children, note }: { title: string; sentence: string; number: string; unit: string; children: React.ReactNode; note?: string }) {
  return (
    <section className="mx-auto grid max-w-6xl gap-10 px-5 py-20 sm:px-8 lg:grid-cols-[minmax(0,420px)_1fr] lg:gap-16 lg:py-28">
      <div>
        <h2 className="text-3xl font-semibold leading-tight sm:text-4xl">{title}</h2>
        <p className="mt-4 max-w-sm text-[17px] leading-relaxed text-muted-foreground">{sentence}</p>
        <p className="mt-8 text-6xl font-semibold tracking-tight text-primary tnum sm:text-7xl">{number}</p>
        <p className="mt-1 text-sm text-muted-foreground">{unit}</p>
      </div>
      <div>
        {children}
        {note && <p className="mt-5 max-w-xl text-sm leading-relaxed text-muted-foreground">{note}</p>}
      </div>
    </section>
  );
}

export function CurveSection({ curve }: { curve: Curve }) {
  const W = 640, H = 340, L = 44, R = 150, T = 16, B = 34;
  const lo = 0.2, hi = 0.65;
  const x = (i: number) => L + (i / 5) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = (em: number[]) => em.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const learned = curve.series[0], randoms = curve.series.slice(1);
  const stat = curve.baselines.find((b) => b.key === "static_graph")!, bm = curve.baselines.find((b) => b.key === "bm25")!, ov = curve.baselines.find((b) => b.key === "open_vocab")!;
  const draw = { initial: { pathLength: 0 }, whileInView: { pathLength: 1 }, viewport: { once: true, margin: "-5%" }, transition: { duration: 1.6, ease: "easeOut" as const } };
  const tag = (yy: number, text: string, fill: string, weight = 400) => <text x={x(5) + 10} y={yy} fontSize={13} fill={fill} fontWeight={weight} dominantBaseline="middle">{text}</text>;
  return (
    <Block
      title="Gets better as it's used"
      sentence={`Each round, it studies the questions it got wrong and adds only the links they were missing. Scored on ${curve.n_questions} questions it never trained on.`}
      number={`${pct(learned.em[0])} → ${pct(learned.em[5])}`}
      unit="questions answered exactly right, before and after five rounds"
      note={`Choosing the missing links at random also helps (${pct(randoms[0].em[5])} and ${pct(randoms[1].em[5])}), so most of the gain comes from adding the right kind of link at all; learning from failures gets there faster. A version told the right link types up front scored ${pct(ov.em)}, which is within the noise of ${pct(learned.em[5])} at this sample size.`}
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Held-out accuracy per iteration for learned, random, static and BM25">
        {[0.2, 0.3, 0.4, 0.5, 0.6].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="#1f2837" />
            <text x={L - 8} y={y(g)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="#8b95a7">{pct(g)}</text>
          </g>
        ))}
        {[0, 1, 2, 3, 4, 5].map((i) => <text key={i} x={x(i)} y={H - 10} textAnchor="middle" fontSize={11} fill="#8b95a7">{i}</text>)}
        <text x={(L + W - R) / 2} y={H + 2} textAnchor="middle" fontSize={11} fill="#8b95a7" />
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
        <text x={L} y={H - 22} fontSize={0} />
      </svg>
      <p className="mt-1 text-xs text-muted-foreground">Horizontal axis: learning iteration. Vertical axis: exact-match accuracy on held-out questions.</p>
    </Block>
  );
}

const PART_COLOR = { planner: "#46526a", answer: "#6c7a96", query_time_extraction: "var(--primary)" };
const PART_LABEL = { planner: "Planning the question", answer: "Writing the answer", query_time_extraction: "Reading for missing facts" };

export function CostSection({ cost }: { cost: Metrics["cost"] }) {
  const rows = cost.per_1000_queries;
  const learned = rows[0];
  const max = Math.max(...rows.map((r) => r.recurring_usd));
  return (
    <Block
      title="Pays only for what's asked"
      sentence="A fact is read out of the source text only when a question needs it, so the bill grows with the questions, not with the size of the library."
      number={`$${learned.recurring_usd.toFixed(2)}`}
      unit={`per 1,000 questions, after a one-time $${learned.one_time_usd.toFixed(2)} of learning`}
      note="The two random runs and the open-vocabulary run cost a little less per question, but all three were handed their link types from the same questions. Learning finds them from feedback, which is what the one-time cost buys."
    >
      <div className="space-y-5">
        {rows.map((r: CostRow) => (
          <div key={r.key}>
            <div className="mb-1.5 flex items-baseline justify-between text-sm">
              <span className={r.key === "learned" ? "font-semibold" : "text-muted-foreground"}>{r.label}</span>
              <span className="tnum text-muted-foreground">${r.recurring_usd.toFixed(2)}</span>
            </div>
            <motion.div className="flex h-5 origin-left overflow-hidden rounded-sm" style={{ width: `${(r.recurring_usd / max) * 100}%` }} initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true, margin: "-5%" }} transition={{ duration: 0.9, ease: "easeOut" }}>
              {(Object.keys(PART_COLOR) as (keyof typeof PART_COLOR)[]).map((k) => (
                <div key={k} style={{ width: `${(r.parts[k] / r.recurring_usd) * 100}%`, background: PART_COLOR[k] }} title={`${PART_LABEL[k]}: $${r.parts[k].toFixed(2)}`} />
              ))}
            </motion.div>
          </div>
        ))}
      </div>
      <div className="mt-6 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        {(Object.keys(PART_COLOR) as (keyof typeof PART_COLOR)[]).map((k) => (
          <span key={k} className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PART_COLOR[k] }} />{PART_LABEL[k]}</span>
        ))}
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
                <span className="w-20 shrink-0 text-xs text-muted-foreground">{m.k}</span>
                <div className="flex-1"><motion.div className="h-5 origin-left rounded-sm" style={{ width: `${(m.v / max) * 100}%`, background: m.c }} initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true, margin: "-5%" }} transition={{ duration: 0.8, ease: "easeOut" }} /></div>
                <span className="tnum w-16 shrink-0 text-right text-sm">{m.v} ms</span>
              </div>
            ))}
          </div>
        ))}
        <div>
          <p className="mb-2 text-sm text-muted-foreground">Slowest 5%, in each 30 seconds of the writing test</p>
          <div className="flex gap-2">
            {lt.windows.map((w) => (
              <div key={w.seconds} className="flex-1 rounded-md border border-border px-3 py-2 text-center">
                <div className="tnum text-base font-medium">{w.read_p95_ms} ms</div>
                <div className="text-xs text-muted-foreground">{w.seconds} s</div>
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
    <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
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
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{s.s}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
