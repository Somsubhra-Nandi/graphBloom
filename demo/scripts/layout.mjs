// Offline force layout for the hero graph. Reads {n, links: [[a, b], ...]} (node indices) on stdin,
// writes {pos: [x, y, z, ...]} on stdout. Same forces the site used to run in the browser.
import { forceSimulation, forceLink, forceManyBody } from "d3-force-3d";

const { n, links } = JSON.parse(await new Promise((res) => {
  let s = "";
  process.stdin.on("data", (c) => (s += c)).on("end", () => res(s));
}));
const nodes = Array.from({ length: n }, (_, i) => ({ i }));
const ls = links.map(([source, target]) => ({ source, target }));
const sim = forceSimulation(nodes, 3)
  .force("link", forceLink(ls).id((d) => d.i).distance(14).strength(0.9))
  .force("charge", forceManyBody().strength(-26).distanceMax(60))
  .force("gravity", Object.assign((alpha) => { for (const d of nodes) { d.vx -= d.x * 0.12 * alpha; d.vy -= d.y * 0.12 * alpha; d.vz -= d.z * 0.12 * alpha; } }, { initialize: () => {} }))
  .alphaDecay(0.015)
  .stop();
for (let i = 0; i < 400; i++) sim.tick();
process.stdout.write(JSON.stringify({ pos: nodes.flatMap((d) => [d.x, d.y, d.z]) }));
