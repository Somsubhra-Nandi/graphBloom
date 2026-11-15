"use client";
import { motion } from "framer-motion";
import type { Curve } from "@/lib/types";

export default function MiniCurve({ curve, iter }: { curve: Curve; iter: number }) {
  const W = 300, H = 120, pl = 8, pr = 8, pt = 14, pb = 18;
  const learned = curve.series.find((s) => s.key === "learned")!;
  const stat = curve.baselines.find((b) => b.key === "static_graph")!;
  const lo = 0.4, hi = 0.62;
  const x = (i: number) => pl + (i / 5) * (W - pl - pr);
  const y = (v: number) => pt + (1 - (v - lo) / (hi - lo)) * (H - pt - pb);
  const d = learned.em.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const cx = x(iter), cy = y(learned.em[iter]);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span className="text-muted-foreground">Held-out accuracy</span>
        <span className="tnum text-lg font-semibold text-primary">{Math.round(learned.em[iter] * 100)}%</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Held-out accuracy by iteration">
        <line x1={pl} x2={W - pr} y1={y(stat.em)} y2={y(stat.em)} stroke="#8b95a7" strokeDasharray="3 4" strokeOpacity={0.6} />
        <path d={d} fill="none" stroke="var(--primary)" strokeWidth={2} strokeOpacity={0.35} />
        <path d={learned.em.slice(0, iter + 1).map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--primary)" strokeWidth={2.5} />
        <motion.circle animate={{ cx, cy }} transition={{ type: "spring", stiffness: 140, damping: 16 }} r={5.5} fill="var(--primary)" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <text key={i} x={x(i)} y={H - 3} textAnchor="middle" fontSize={10} fill={i === iter ? "#e8ebf1" : "#8b95a7"}>{i}</text>
        ))}
      </svg>
      <div className="text-xs text-muted-foreground">Dashed line: the graph that never learns ({Math.round(stat.em * 100)}%)</div>
    </div>
  );
}
