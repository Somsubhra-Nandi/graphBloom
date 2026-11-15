import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Curve, Metrics, Mutation } from "./types";

const read = <T,>(f: string): T => JSON.parse(readFileSync(join(process.cwd(), "public/data", f), "utf8"));
export const getCurve = () => read<Curve>("curve.json");
export const getMetrics = () => read<Metrics>("metrics.json");
export const getMutations = () => read<Mutation[]>("mutations.json");
