export type GNode = { id: number; name: string; type: string; created_iter: number; degree: number; x?: number; y?: number; z?: number };
export type GLink = { source: number | GNode; target: number | GNode; type: string; created_iter: number };
export type GraphData = { nodes: GNode[]; links: GLink[]; counts: { entities: number; edges: number; isolated: number; edges_by_iter: Record<string, number> } };
export type Series = { key: string; label: string; em: number[]; ci95: number[][]; cost_usd: number | null };
export type Baseline = { key: string; label: string; em: number; ci95: number[] };
export type Curve = { n_questions: number; iterations: number[]; series: Series[]; baselines: Baseline[] };
export type Mutation = { iteration: number; kind: string; relation: string; reason: string; question_id: string };
export type Story = {
  id: string; type: string; question: string; gold: string; plan: string[];
  before: { answer: string; walked: { id: number; name: string }[]; walked_edges: string[]; dead_end: { id: number; name: string; missing_relation: string } };
  after: { answer: string; nodes: { id: number; name: string }[]; edges: { type: string; created_iter: number }[] };
  fixed_by: string; fixed_iter: number;
};
export type CostRow = { key: string; label: string; one_time_usd: number; recurring_usd: number; total_usd: number; parts: { planner: number; answer: number; query_time_extraction: number }; em: number };
export type Lat = { n: number; p50_ms: number; p95_ms: number; max_ms: number; errors: number };
export type Metrics = {
  load_test: { concurrent_queries: number; duration_s: number; quiet: Lat; busy: Lat & { rounds: number }; writer: { nodes_written: number; edges_written: number; nodes_per_second: number }; windows: { seconds: string; queries: number; read_p50_ms: number; read_p95_ms: number }[]; note: string };
  cost: { per_1000_queries: CostRow[]; learning_total_usd: number; match_iteration: number; note: string };
};
export type StageState = { story: number; phase: string; graphIter: number; curveIter: number };
