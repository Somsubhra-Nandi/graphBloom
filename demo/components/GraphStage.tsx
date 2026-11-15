"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { forceSimulation, forceLink, forceManyBody } from "d3-force-3d";
import type { GLink, GNode, GraphData, StageState, Story } from "@/lib/types";

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

const K = 0.3; // overlay size, in graph units
const GREEN = 0x5be3a4;
const RED = 0xff5a6b;
const WHITE = 0xdfe6f3;
const TYPE_COLOR: Record<string, number> = { film: 0x5b7fb0, person: 0x8a86b8, place: 0x4f9a9a, award: 0x8a8f9a, school: 0x8a8f9a, organisation: 0x8a8f9a, other: 0x6b7482 };

type Props = {
  graph: GraphData;
  stories: Story[];
  mode: "story" | "replay";
  iter: number; // used in replay mode
  onState: (s: StageState) => void;
  onReady?: () => void;
  showFps?: boolean;
};

type Beam = { mesh: THREE.Mesh; parts: THREE.Sprite[]; a: THREE.Vector3; b: THREE.Vector3; p: number };

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
const clamp = (x: number) => Math.min(1, Math.max(0, x));

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)");
  r.addColorStop(0.25, "rgba(255,255,255,0.55)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

function phasePlan(s: Story) {
  const dead = s.after.nodes.findIndex((n) => n.id === s.before.dead_end.id);
  const fix = Math.max(0, dead);
  const walk = s.before.walked_edges.length;
  const rest = s.after.edges.length - fix - 1;
  return {
    fix,
    phases: [
      ["question", 3.0],
      ["walk", 1.4 + walk * 1.0],
      ["deadend", 2.8],
      ["grow", 2.6],
      ["complete", 1.4 + rest * 1.1],
      ["tick", 2.6],
      ["rest", 0.8],
    ] as [string, number][],
  };
}

export default function GraphStage({ graph, stories, mode, iter, onState, onReady, showFps }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [ready, setReady] = useState(false);
  const labels = useRef<HTMLDivElement[]>([]);
  const fpsEl = useRef<HTMLDivElement>(null);
  const props = useRef({ mode, iter, stories, onState });
  props.current = { mode, iter, stories, onState };

  const nid = (x: number | GNode) => (typeof x === "object" ? x.id : x);
  // only connected entities are drawn; the rest are chunk titles that never got a link
  const data = useRef<{ nodes: GNode[]; links: GLink[] }>(null as never);
  if (!data.current) {
    const nodes = graph.nodes.filter((n) => n.degree > 0).map((n) => ({ ...n }));
    const links = graph.links.map((l) => ({ ...l }));
    // lay the graph out once, up front; gravity keeps the many small clusters from drifting apart
    const sim = forceSimulation(nodes, 3)
      .force("link", forceLink(links).id((n: GNode) => n.id).distance(14).strength(0.9))
      .force("charge", forceManyBody().strength(-26).distanceMax(60))
      .force("gravity", Object.assign((alpha: number) => { for (const n of nodes as any[]) { n.vx -= n.x * 0.12 * alpha; n.vy -= n.y * 0.12 * alpha; n.vz -= n.z * 0.12 * alpha; } }, { initialize: () => {} })) // eslint-disable-line @typescript-eslint/no-explicit-any
      .alphaDecay(0.015)
      .stop();
    for (let i = 0; i < 400; i++) sim.tick();
    data.current = { nodes, links: links.map((l) => ({ ...l, source: nid(l.source), target: nid(l.target) })) };
  }

  useEffect(() => {
    const el = wrap.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!ready) return;
    const fg = fgRef.current;
    const scene: THREE.Scene = fg.scene();
    const camera: THREE.PerspectiveCamera = fg.camera();
    const controls = fg.controls();
    controls.enableZoom = false; // keep the mouse wheel for scrolling the page
    controls.enablePan = false;
    fg.renderer().setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    const byId = new Map<number, GNode>(data.current.nodes.map((n) => [n.id, n]));
    const nid = (x: number | GNode) => (typeof x === "object" ? x.id : x);

    // ---- base layers: one instanced mesh for nodes, one line set for links (2 draw calls) ----
    const links = [...data.current.links].sort((a, b) => a.created_iter - b.created_iter);
    const countByIter = [0, 1, 2, 3, 4, 5].map((i) => links.filter((l) => l.created_iter <= i).length);
    const linePos = new Float32Array(links.length * 6);
    const lineCol = new Float32Array(links.length * 6);
    const order = new Map<number, number>();
    const base = new THREE.Color(0x56627a);
    const fresh = new THREE.Color(GREEN);
    links.forEach((l, i) => {
      const a = byId.get(nid(l.source))!, b = byId.get(nid(l.target))!;
      linePos.set([a.x!, a.y!, a.z!, b.x!, b.y!, b.z!], i * 6);
      const c = l.created_iter ? fresh : base;
      lineCol.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
      for (const n of [a.id, b.id]) if (!order.has(n)) order.set(n, i);
    });
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
    lg.setAttribute("color", new THREE.BufferAttribute(lineCol, 3));
    lg.setDrawRange(0, 0);
    const lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7, depthWrite: false }));
    lines.frustumCulled = false;

    const nodes = data.current.nodes;
    const inst = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85 }), nodes.length);
    inst.frustumCulled = false;
    const radius = nodes.map((n) => Math.min(2, 0.4 + Math.sqrt(n.degree) * 0.14));
    nodes.forEach((n, i) => {
      const c = new THREE.Color(TYPE_COLOR[n.type] ?? TYPE_COLOR.other).multiplyScalar(0.8);
      inst.setColorAt(i, c);
    });
    const m4 = new THREE.Matrix4();
    const setScales = (disp: number) => {
      nodes.forEach((n, i) => {
        const s = clamp((disp - (order.get(n.id) ?? 0)) / 10) * radius[i];
        m4.makeScale(s, s, s).setPosition(n.x!, n.y!, n.z!);
        inst.setMatrixAt(i, m4);
      });
      inst.instanceMatrix.needsUpdate = true;
    };
    setScales(0);
    const world = new THREE.Group();
    world.add(lines, inst);
    scene.add(world);

    // graph size, for the wide camera
    const wideC = new THREE.Vector3();
    const dists = nodes.map((n) => Math.hypot(n.x!, n.y!, n.z!)).sort((a, b) => a - b);
    const wideR = dists[Math.floor(dists.length * 0.92)];
    camera.far = Math.max(camera.far, wideR * 12);
    camera.updateProjectionMatrix();

    // ---- story overlay ----
    const glow = glowTexture();
    const overlay = new THREE.Group();
    scene.add(overlay);
    const cylGeo = new THREE.CylinderGeometry(0.16, 0.16, 1, 6, 1, true);
    const sprite = (color: number, scale: number, opacity = 1) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending }));
      s.scale.set(scale * K, scale * K, 1);
      return s;
    };
    const mkBeam = (a: THREE.Vector3, b: THREE.Vector3, color: number): Beam => {
      const mesh = new THREE.Mesh(cylGeo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, depthWrite: false }));
      mesh.visible = false;
      const parts = [0, 1, 2].map(() => sprite(color, 9));
      parts.forEach((p) => (p.visible = false));
      overlay.add(mesh, ...parts);
      return { mesh, parts, a, b, p: 0 };
    };
    const setBeam = (bm: Beam, p: number, color: number, t: number, particles = true) => {
      bm.p = p;
      bm.mesh.visible = p > 0.001;
      (bm.mesh.material as THREE.MeshBasicMaterial).color.setHex(color);
      const dir = new THREE.Vector3().subVectors(bm.b, bm.a);
      const len = dir.length();
      dir.normalize();
      bm.mesh.position.copy(bm.a).addScaledVector(dir, (len * p) / 2);
      bm.mesh.scale.set(1, Math.max(0.001, len * p), 1);
      bm.mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      bm.parts.forEach((s, k) => {
        s.visible = particles && p > 0.02 && p < 0.999;
        if (!s.visible) return;
        (s.material as THREE.SpriteMaterial).color.setHex(color);
        const f = (t * 0.9 + k / 3) % 1;
        s.position.copy(bm.a).addScaledVector(dir, len * p * f);
      });
    };

    type Live = { story: Story; fix: number; phases: [string, number][]; pts: THREE.Vector3[]; before: Beam[]; after: Beam[]; marks: THREE.Sprite[]; pulse: THREE.Sprite; center: THREE.Vector3; radius: number };
    let live: Live | null = null;
    const clearLive = () => {
      overlay.children.slice().forEach((o) => {
        overlay.remove(o);
        const m = o as THREE.Mesh;
        if (m.material && !(m.material as THREE.SpriteMaterial).map) (m.material as THREE.Material).dispose();
      });
      live = null;
    };
    const P = (id: number) => {
      const n = byId.get(id)!;
      return new THREE.Vector3(n.x, n.y, n.z);
    };
    const startStory = (s: Story): Live => {
      clearLive();
      const { fix, phases } = phasePlan(s);
      const pts = s.after.nodes.map((n) => P(n.id));
      const before = s.before.walked_edges.map((_, i) => mkBeam(pts[i], pts[i + 1], WHITE));
      const after = s.after.edges.map((_, i) => mkBeam(pts[i], pts[i + 1], GREEN));
      const marks = pts.map(() => {
        const m = sprite(WHITE, 0, 0.9);
        overlay.add(m);
        return m;
      });
      const pulse = sprite(RED, 0, 0);
      overlay.add(pulse);
      const box2 = new THREE.Box3().setFromPoints(pts);
      const center = box2.getCenter(new THREE.Vector3());
      const radius = Math.max(box2.getSize(new THREE.Vector3()).length() / 2, 20);
      return { story: s, fix, phases, pts, before, after, marks, pulse, center, radius };
    };

    // ---- labels ----
    const lab = labels.current;
    const labelState: { pos: THREE.Vector3 | null; text: string; cls: string }[] = lab.map(() => ({ pos: null, text: "", cls: "" }));
    const setLabel = (i: number, pos: THREE.Vector3 | null, text: string, cls: string) => {
      const st = labelState[i];
      st.pos = pos;
      if (st.text !== text || st.cls !== cls) {
        st.text = text;
        st.cls = cls;
        lab[i].textContent = text;
        lab[i].dataset.kind = cls;
      }
    };
    const v = new THREE.Vector3();
    const placeLabels = () => {
      const w = size.w, h = size.h;
      labelState.forEach((st, i) => {
        const el = lab[i];
        if (!st.pos || !st.text) {
          el.style.opacity = "0";
          return;
        }
        v.copy(st.pos).project(camera);
        if (v.z > 1) {
          el.style.opacity = "0";
          return;
        }
        el.style.opacity = "1";
        el.style.transform = `translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px) translate(-50%, ${st.cls === "node" ? "-140%" : "45%"})`;
      });
    };

    // ---- camera: ease a target and a distance; the user can grab it ----
    const camT = wideC.clone();
    const camPos = camera.position.clone();
    let dist = wideR * 1.75;
    let ang = 0.6;
    let userUntil = 0;
    const el = wrap.current!;
    const grab = () => (userUntil = performance.now() + 5000);
    el.addEventListener("pointerdown", grab);
    el.addEventListener("wheel", grab, { passive: true });
    camera.position.set(wideC.x + Math.sin(ang) * dist, wideC.y + dist * 0.35, wideC.z + Math.cos(ang) * dist);
    controls.target.copy(wideC);

    // ---- per-frame ----
    let disp = 0;
    let lastDispRounded = -1;
    let t0 = performance.now(), last = t0, storyIdx = -1, storyStart = 0, lastEmit = "", frames = 0, fpsT = last, curveIter = 0, graphIter = 0, lastMode = "";
    let raf = 0;
    const emit = (story: number, phase: string) => {
      const key = `${story}|${phase}|${graphIter}|${curveIter}`;
      if (key !== lastEmit) {
        lastEmit = key;
        props.current.onState({ story, phase, graphIter, curveIter });
      }
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      frame2(now);
    };
    const frame2 = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      frames++;
      if (fpsEl.current && now - fpsT > 500) {
        fpsEl.current.textContent = `${Math.round((frames * 1000) / (now - fpsT))} fps`;
        frames = 0;
        fpsT = now;
      }
      const { mode: md, iter: it, stories: ss } = props.current;
      const t = (now - t0) / 1000;
      let wantC = wideC, wantD = wideR * 1.75;
      let phase = "";

      if (md === "replay") {
        if (lastMode !== "replay") { clearLive(); storyIdx = -1; setLabel(0, null, "", ""); setLabel(1, null, "", ""); setLabel(2, null, "", ""); setLabel(3, null, "", ""); }
        graphIter = it;
        curveIter = it;
        phase = "replay";
        emit(-1, phase);
      } else {
        if (lastMode !== "story") { storyIdx = -1; }
        if (storyIdx === -1 || !live) {
          storyIdx = (storyIdx + 1) % ss.length;
          live = startStory(ss[storyIdx]);
          storyStart = now;
          graphIter = 0;
          curveIter = 0;
        }
        const L = live!;
        let el_ = (now - storyStart) / 1000;
        let name = "rest", u = 0, acc = 0, idx = 0, found = false;
        for (const [n, d] of L.phases) {
          if (el_ < acc + d) { name = n; u = el_ - acc; found = true; break; }
          acc += d; idx++;
        }
        if (!found) {
          // story over: next one
          storyIdx = (storyIdx + 1) % ss.length;
          live = startStory(ss[storyIdx]);
          storyStart = now;
          graphIter = 0; curveIter = 0;
          return;
        }
        phase = name;
        const s = L.story, fix = L.fix, deadN = L.pts[fix];
        const rest = L.after.length - fix - 1;
        // marks
        L.marks.forEach((m, i) => { m.scale.setScalar(K * (0)); (m.material as THREE.SpriteMaterial).color.setHex(WHITE); void i; });
        L.before.forEach((b) => setBeam(b, 0, WHITE, t));
        L.after.forEach((b) => setBeam(b, 0, GREEN, t));
        (L.pulse.material as THREE.SpriteMaterial).opacity = 0;
        L.pulse.scale.setScalar(K * (0));
        const seed = L.pts[0];
        const pop = (i: number, size_: number, col: number) => { L.marks[i].scale.setScalar(K * (size_)); (L.marks[i].material as THREE.SpriteMaterial).color.setHex(col); L.marks[i].position.copy(L.pts[i]); };
        let l0 = "", l1 = "", l2 = "", l3 = "";
        void l0; void l1; void l2; void l3;
        setLabel(1, null, "", ""); setLabel(2, null, "", ""); setLabel(3, null, "", "");
        const idxPhase = idx; void idxPhase;

        if (name === "question") {
          pop(0, 16 * ease(u / 0.8), WHITE);
          setLabel(0, seed, s.after.nodes[0].name, "node");
        } else if (name === "walk") {
          pop(0, 14, WHITE);
          L.before.forEach((b, i) => {
            const p = ease((u - 0.3 - i * 1.0) / 0.9);
            setBeam(b, p, WHITE, t);
            if (p > 0.95) pop(i + 1, 13, WHITE);
          });
          setLabel(0, seed, s.after.nodes[0].name, "node");
          const probe = Math.min(s.before.walked_edges.length, L.fix);
          if (!L.before.length) {
            // nothing to walk yet: the search is looking at the start entity
            const k = 0.5 + 0.5 * Math.sin(u * 5);
            (L.pulse.material as THREE.SpriteMaterial).color.setHex(WHITE);
            (L.pulse.material as THREE.SpriteMaterial).opacity = 0.35 * k;
            L.pulse.position.copy(seed); L.pulse.scale.setScalar(K * (14 + 10 * k));
          }
          void probe;
        } else if (name === "deadend" || name === "grow" || name === "complete" || name === "tick") {
          for (let i = 0; i <= fix; i++) pop(i, 13, WHITE);
          L.before.forEach((b) => setBeam(b, 1, WHITE, t, false));
        }
        if (name === "deadend") {
          const k = 0.5 + 0.5 * Math.sin(u * 7);
          (L.pulse.material as THREE.SpriteMaterial).color.setHex(RED);
          (L.pulse.material as THREE.SpriteMaterial).opacity = 0.35 + 0.4 * k;
          L.pulse.position.copy(deadN); L.pulse.scale.setScalar(K * (20 + 22 * ((u * 1.4) % 1)));
          pop(fix, 15, RED);
          setLabel(0, seed, s.after.nodes[0].name, "node");
          if (fix > 0) setLabel(1, deadN, s.before.dead_end.name, "node");
          setLabel(2, deadN, `missing fact: ${s.before.dead_end.missing_relation}`, "bad");
        }
        if (name === "grow" || name === "complete" || name === "tick") {
          const prog = name === "grow" ? ease(u / 1.8) : 1;
          setBeam(L.after[fix], prog, GREEN, t, name === "grow");
          if (name === "grow") {
            pop(fix, 15, prog < 1 ? RED : GREEN);
            if (prog > 0.98) pop(fix + 1, 14, GREEN);
            graphIter = s.fixed_iter;
            setLabel(2, L.pts[fix + 1] ?? deadN, `new link: ${s.before.dead_end.missing_relation}`, "good");
            setLabel(0, seed, s.after.nodes[0].name, "node");
          }
        }
        if (name === "complete" || name === "tick") {
          const all = name === "tick" || u > 0.2 + rest * 1.1 + 0.5;
          for (let i = 0; i <= fix; i++) if (i < L.before.length) setBeam(L.before[i], 0, WHITE, t);
          for (let i = 0; i < L.after.length; i++) {
            if (i < fix) setBeam(L.after[i], 1, GREEN, t, false);
            else if (i > fix) setBeam(L.after[i], ease((u - 0.2 - (i - fix - 1) * 1.1) / 0.9), GREEN, t, !all);
          }
          L.pts.forEach((_, i) => pop(i, i === L.pts.length - 1 ? 18 : 12, GREEN));
          const end = L.pts[L.pts.length - 1];
          const k = all ? 0.5 + 0.5 * Math.sin(u * 5) : 0;
          (L.pulse.material as THREE.SpriteMaterial).color.setHex(GREEN);
          (L.pulse.material as THREE.SpriteMaterial).opacity = 0.5 * k;
          L.pulse.position.copy(end); L.pulse.scale.setScalar(K * (24 + 10 * k));
          setLabel(0, seed, s.after.nodes[0].name, "node");
          setLabel(2, all ? end : null, all ? s.after.nodes[s.after.nodes.length - 1].name : "", "good");
        }
        if (name === "tick") curveIter = s.fixed_iter;
        if (name === "rest") {
          L.pts.forEach((_, i) => pop(i, 12, GREEN));
          L.after.forEach((b) => setBeam(b, 1, GREEN, t, false));
          curveIter = s.fixed_iter;
        }
        // camera
        wantC = name === "question" && u < 0.01 ? wideC : L.center;
        wantD = name === "rest" ? wideR * 1.3 : Math.max(L.radius * 2.6 + 60, 130);
        emit(storyIdx, phase);
      }
      lastMode = md;

      // base layer: reveal links up to the current iteration, a few at a time
      const target = countByIter[Math.min(5, Math.max(0, Math.round(graphIter)))];
      const speed = Math.max(40, Math.abs(target - disp) * 2.2);
      if (disp < target) disp = Math.min(target, disp + speed * dt);
      else if (disp > target) disp = Math.max(target, disp - speed * 3 * dt);
      const r = Math.round(disp);
      if (r !== lastDispRounded) {
        lastDispRounded = r;
        lg.setDrawRange(0, r * 2);
        setScales(r);
      }

      // camera easing
      if (now > userUntil) {
        if (userUntil !== 0) { camT.copy(controls.target); camPos.copy(camera.position); dist = camPos.distanceTo(camT); userUntil = 0; }
        ang += dt * 0.07;
        const k = 1 - Math.exp(-dt * 1.6);
        camT.lerp(wantC, k);
        dist += (wantD - dist) * k;
        camPos.set(camT.x + Math.sin(ang) * dist, camT.y + dist * 0.32, camT.z + Math.cos(ang) * dist);
        camera.position.lerp(camPos, 1 - Math.exp(-dt * 4));
        controls.target.copy(camT);
        controls.update();
      }
      placeLabels();
    };
    raf = requestAnimationFrame(frame);
    onReady?.();

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("pointerdown", grab);
      el.removeEventListener("wheel", grab);
      clearLive();
      scene.remove(world, overlay);
      lg.dispose();
      inst.geometry.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, size.w, size.h]);

  return (
    <div ref={wrap} className="absolute inset-0">
      {size.w > 0 && (
        <ForceGraph3D
          ref={fgRef}
          width={size.w}
          height={size.h}
          graphData={data.current}
          backgroundColor="rgba(0,0,0,0)"
          controlType="orbit"
          showNavInfo={false}
          enablePointerInteraction={false}
          enableNodeDrag={false}
          nodeVisibility={false}
          linkVisibility={false}
          nodeThreeObject={() => new THREE.Object3D()}
          warmupTicks={0}
          cooldownTicks={0}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.35}
          onEngineStop={() => {
            if (!ready) setReady(true);
          }}
          onEngineTick={() => {}}
          rendererConfig={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        />
      )}
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          ref={(e) => {
            if (e) labels.current[i] = e;
          }}
          className="stage-label pointer-events-none absolute left-0 top-0 z-10 whitespace-nowrap opacity-0 data-[kind=bad]:text-[var(--bad)] data-[kind=good]:text-[var(--good)]"
        />
      ))}
      {showFps && <div ref={fpsEl} className="absolute right-3 top-3 z-20 rounded bg-black/70 px-2 py-1 font-mono text-xs text-white" />}
    </div>
  );
}
