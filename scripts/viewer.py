"""Streamlit viewer for the self-improving graph. Read-only, no LLM calls.

  .venv/bin/streamlit run scripts/viewer.py

  .venv/bin/streamlit run scripts/viewer.py -- --snapshot learned_iter5   # also checks the live graph against that snapshot

Tabs: Learning curve (with replay and a live toggle), Mutation log, Before / after, Entity search, Query trace.
Needs the HydraDB container for the Mutation log (live run) and Entity search; everything else reads results/.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from pyvis.network import Network  # noqa: E402

from src import config  # noqa: E402
from src.curve import build_curve  # noqa: E402
from src.graph import Graph, Index, normalize  # noqa: E402
from src.mutations import from_graph  # noqa: E402
from src.snapshot import get_live, snap_dir  # noqa: E402

RESULTS = config.ROOT / "results"
st.set_page_config(page_title="Self-improving graph", layout="wide")

SERIES_COLORS = {
    "learned": "#1b7f3b", "random (seed 42)": "#d95f02", "random (seed 7)": "#e6a15a",
    "static graph": "#6a51a3", "BM25": "#7f7f7f", "open vocabulary (one pass)": "#1f77b4",
}
NODE = {"seed": "#4C78A8", "plain": "#C9CED6", "chain": "#2CA02C", "dead": "#D62728", "attr": "#FFBF00", "ghost": "#FFFFFF"}


# ------------------------------------------------------------------ data helpers
@st.cache_data(ttl=5)
def read_jsonl(path_str, mtime):
    return [json.loads(l) for l in open(path_str)]


def rows_of(path):
    return read_jsonl(str(path), path.stat().st_mtime) if path.exists() else []


def runs_available():
    return sorted(p.parent.name for p in RESULTS.glob("*/state.json"))


def iterations_of(run):
    return sorted(int(p.parent.name[4:]) for p in (RESULTS / run).glob("iter*/summary.json"))


def run_state(run):
    p = RESULTS / run / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_resource
def get_graph():
    return Graph()


def live_run():
    p = config.STATE_DIR / "live_graph.json"
    return json.loads(p.read_text()).get("run") if p.exists() else None


# ------------------------------------------------------------------ learning curve
def curve_chart(curve, metric, upto=None):
    rows = []
    max_it = max([k for r in curve["runs"].values() for k in r["iterations"]] + [1])
    for r in curve["runs"].values():
        for i, k in enumerate(r["iterations"]):
            if upto is None or k <= upto:
                lo, hi = r[f"{metric}_ci95"][i]
                rows.append({"series": r["label"], "iteration": k, "value": r[metric][i], "lo": lo, "hi": hi})
    runs = pd.DataFrame(rows)
    base = []
    for b in curve["baselines"].values():
        lo, hi = b[f"{metric}_ci95"]
        for k in range(max_it + 1):
            base.append({"series": b["label"], "iteration": k, "value": b[metric], "lo": lo, "hi": hi})
    base = pd.DataFrame(base)
    domain = [s for s in SERIES_COLORS if s in set(runs.get("series", [])) | set(base.get("series", []))]
    color = alt.Color("series:N", scale=alt.Scale(domain=domain, range=[SERIES_COLORS[s] for s in domain]), legend=alt.Legend(title=None))
    x = alt.X("iteration:Q", scale=alt.Scale(domain=[0, max_it]), axis=alt.Axis(tickMinStep=1, title="iteration"))
    y = alt.Y("value:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title=f"held-out {metric.upper()} (87 questions)"))
    layers = []
    if len(base):
        layers += [alt.Chart(base).mark_area(opacity=0.08).encode(x=x, y=alt.Y("lo:Q"), y2="hi:Q", color=color),
                   alt.Chart(base).mark_line(strokeDash=[5, 4], strokeWidth=2).encode(x=x, y=y, color=color)]
    if len(runs):
        layers += [alt.Chart(runs).mark_area(opacity=0.18).encode(x=x, y=alt.Y("lo:Q"), y2="hi:Q", color=color),
                   alt.Chart(runs).mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=3).encode(
                       x=x, y=y, color=color, tooltip=["series", "iteration", alt.Tooltip("value:Q", format=".3f"), alt.Tooltip("lo:Q", format=".3f"), alt.Tooltip("hi:Q", format=".3f")])]
    return alt.layer(*layers).properties(height=420) if layers else None


def added_table(curve):
    rows = []
    for r in curve["runs"].values():
        for k in r["iterations"]:
            rows.append({"run": r["label"], "iteration": k, "relations added": ", ".join(r["added"].get(str(k), [])) or ("-" if k else "seed schema")})
    return pd.DataFrame(rows)


def curve_body(metric, live):
    curve = build_curve() if live else (json.loads((RESULTS / "curve.json").read_text()) if (RESULTS / "curve.json").exists() else build_curve())
    ch = curve_chart(curve, metric)
    if ch is None:
        st.info("No iterations yet. Run scripts/learn.py.")
        return
    st.altair_chart(ch, width="stretch")
    st.caption(f"Bands are bootstrap 95% CIs (1,000 resamples, seed 42). Dashed lines are the static graph and BM25 baselines. Updated {curve['updated']}.")
    st.dataframe(added_table(curve), hide_index=True, width="stretch")


def tab_curve():
    c1, c2, c3 = st.columns([2, 2, 3])
    metric = c1.radio("Metric", ["em", "f1"], format_func=str.upper, horizontal=True)
    live = c2.toggle("Live (re-read results/ every 5 s)")
    replay = c3.button("Replay learning")
    if replay:
        curve = build_curve()
        top = max([k for r in curve["runs"].values() for k in r["iterations"]] + [0])
        slot, cap = st.empty(), st.empty()
        for k in range(top + 1):
            ch = curve_chart(curve, metric, upto=k)
            if ch is not None:
                slot.altair_chart(ch, width="stretch")
            cap.caption(f"iteration {k} of {top}")
            time.sleep(1.5)
        st.dataframe(added_table(curve), hide_index=True, width="stretch")
    elif live:
        st.fragment(curve_body, run_every=5)(metric, True)
    else:
        curve_body(metric, False)


# ------------------------------------------------------------------ mutation log
def tab_mutations():
    runs = runs_available()
    if not runs:
        st.info("No runs yet.")
        return
    run = st.selectbox("Run", runs, key="mut_run")
    exported = RESULTS / run / "mutations.jsonl"
    if run == live_run():
        try:
            rows, source = from_graph(get_graph()), "HydraDB (live graph)"
        except Exception as e:  # noqa: BLE001
            st.error(f"HydraDB is not reachable: {e}")
            return
    elif exported.exists():
        rows, source = rows_of(exported), f"export of the graph's Mutation nodes ({exported.relative_to(config.ROOT)})"
    else:
        st.warning(f"The live graph belongs to '{live_run()}', and '{run}' has no export.")
        return
    st.caption(f"Source: {source}. {len(rows)} Mutation nodes.")
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No mutations yet.")
        return
    df = df[["iteration", "kind", "relation", "reason", "question_id", "id"]]
    f1, f2 = st.columns(2)
    its = f1.multiselect("Iteration", sorted(df["iteration"].unique()), default=sorted(df["iteration"].unique()))
    kinds = f2.multiselect("Kind", sorted(df["kind"].unique()), default=sorted(df["kind"].unique()))
    view = df[df["iteration"].isin(its) & df["kind"].isin(kinds)]
    st.dataframe(view, hide_index=True, width="stretch", height=380)
    counts = df.pivot_table(index="iteration", columns="kind", values="id", aggfunc="count", fill_value=0)
    cl, cr = st.columns([2, 3])
    cl.subheader("Per-iteration counts")
    cl.dataframe(counts, width="stretch")
    cr.subheader(" ")
    long = counts.reset_index().melt("iteration", var_name="kind", value_name="mutations")
    cr.altair_chart(alt.Chart(long).mark_bar().encode(x=alt.X("iteration:O"), y="mutations:Q", color="kind:N", tooltip=["iteration", "kind", "mutations"]).properties(height=220), width="stretch")


# ------------------------------------------------------------------ graph drawing from a stored trace
def is_literal_rel(r):
    n = normalize(r)
    return n in {"date of birth", "publication date"} or n.startswith("date of ") or n.endswith(" date")


def edge_steps(chain):
    return [normalize(c) for c in chain if not is_literal_rel(c)]


def complete_paths(trace):
    steps = edge_steps(trace["plan"]["relation_chain"])
    return [p for p in trace["paths"] if [normalize(e["type"]) for e in p["edges"]] == steps]


def attr_text(attrs):
    return "\n".join(f"{k.replace('_', ' ')}: {v['raw']}" + (f" [{v['iso']}]" if v.get("iso") else "") for k, v in sorted(attrs.items()))


def clean(s):
    """Labels come from Wikipedia text and LLM output and end up inside generated HTML: drop angle brackets."""
    return str(s).replace("<", "\u2039").replace(">", "\u203a")


def trace_html(trace, mode, height=520):
    """mode 'dead': highlight dead ends in red with a ghost step for the missing relation.
    mode 'complete': highlight the completed planned path in green."""
    net = Network(height=f"{height}px", width="100%", directed=True, cdn_resources="in_line", bgcolor="#ffffff")
    seeds = {s["id"] for s in trace["seeds"]}
    done = complete_paths(trace)
    chain_nodes = {n["id"] for p in done for n in p["nodes"]}
    chain_edges = {(a["id"], b["id"]) for p in done for a, b in zip(p["nodes"], p["nodes"][1:])}
    dead = {d["entity_id"]: d for d in trace.get("dead_ends", [])}
    added = set()

    def node(i, name):
        if i in added:
            return
        added.add(i)
        name = clean(name)
        if mode == "dead" and i in dead:
            net.add_node(i, label=name, color={"background": NODE["dead"], "border": "#7f0000"}, borderWidth=3, size=24, title=clean(f"dead end: no '{dead[i]['expected_relation']}' edge"))
        elif mode == "complete" and i in chain_nodes:
            net.add_node(i, label=name, color={"background": NODE["chain"], "border": "#0b4f1c"}, borderWidth=2, size=22)
        elif i in seeds:
            net.add_node(i, label=name, color=NODE["seed"], size=20, font={"color": "#111"})
        else:
            net.add_node(i, label=name, color=NODE["plain"], size=13)

    for p in trace["paths"][:14]:
        for n in p["nodes"]:
            node(n["id"], n["name"])
        for e, (a, b) in zip(p["edges"], zip(p["nodes"], p["nodes"][1:])):
            hot = mode == "complete" and (a["id"], b["id"]) in chain_edges
            net.add_edge(a["id"], b["id"], label=clean(e["type"]), color="#2CA02C" if hot else "#B0B5BD", width=5 if hot else 1, font={"size": 10, "align": "middle"})
    for s in trace["seeds"]:
        node(s["id"], s["name"])
    if mode == "dead":
        for i, d in dead.items():
            node(i, d["entity"])
            gid = f"ghost-{i}-{d['expected_relation']}"
            net.add_node(gid, label=clean(f"{d['expected_relation']} ?"), shape="box", color={"background": "#FFFFFF", "border": NODE["dead"]}, borderWidth=2, shapeProperties={"borderDashes": [5, 5]}, font={"color": NODE["dead"]})
            net.add_edge(i, gid, color=NODE["dead"], dashes=True, width=2)
    attrs = {int(k): v for k, v in trace.get("attributes", {}).items()}
    show_attr = chain_nodes | seeds if mode == "complete" else seeds | set(dead)
    for i in show_attr:
        if i in attrs and i in added:
            aid = f"attr-{i}"
            net.add_node(aid, label=clean(attr_text(attrs[i])), shape="box", color={"background": "#FFF3C4", "border": "#E0A800"}, font={"size": 11})
            net.add_edge(i, aid, color="#E0A800", dashes=True, width=1)
    net.set_options(json.dumps({
        "physics": {"barnesHut": {"gravitationalConstant": -6500, "springLength": 130, "springConstant": 0.04}, "stabilization": {"iterations": 200}},
        "edges": {"arrows": {"to": {"enabled": True, "scaleFactor": 0.6}}, "smooth": {"type": "dynamic"}},
        "interaction": {"hover": True, "tooltipDelay": 100},
    }))
    return net.generate_html()


def legend(mode):
    items = [("seed entity", NODE["seed"])]
    items += [("dead end", NODE["dead"])] if mode == "dead" else [("completed planned path", NODE["chain"])]
    items += [("other entity on a retrieved path", NODE["plain"]), ("date attribute", NODE["attr"])]
    st.markdown("  ".join(f"<span style='color:{c}'>&#9632;</span> {t}" for t, c in items), unsafe_allow_html=True)


def trace_panel(row, mode, title):
    t = row["trace"]
    ok = row["em"] == 1
    st.markdown(f"#### {title}")
    st.markdown(f"**Prediction:** {row['prediction'] or '(none)'} &nbsp; **Gold:** {row['gold']} &nbsp; {'&#9989;' if ok else '&#10060;'}")
    st.caption(f"planned chain: {' → '.join(t['plan']['relation_chain']) or '(none)'}  |  seeds: {', '.join(s['name'] for s in t['seeds']) or '(none resolved)'}")
    if t.get("query_extraction"):
        st.caption("query-time extraction: " + "; ".join(f"{q['relation']} from '{q['chunk']}' (+{q['edges']} edges, +{q['literals']} dates)" for q in t["query_extraction"]))
    legend(mode)
    st.iframe(trace_html(t, mode), height=540)


# ------------------------------------------------------------------ before / after
def visual_score(r0, rN, added_rels):
    """Higher = more visual: a dead end on a relation the schema later gained, and a long completed path."""
    t0, tN = r0["trace"], rN["trace"]
    dead_on_added = any(normalize(d["expected_relation"]) in added_rels for d in t0.get("dead_ends", []))
    longest = max([len(p["nodes"]) for p in complete_paths(tN)] + [0])
    return 10 * dead_on_added + 2 * longest + len({n["id"] for p in tN["paths"] for n in p["nodes"]}) * 0.1


def tab_before_after():
    runs = [r for r in runs_available() if len(iterations_of(r)) >= 2]
    if not runs:
        st.info("Needs a run with at least two iterations.")
        return
    run = st.selectbox("Run", runs, index=runs.index("learned") if "learned" in runs else 0, key="ba_run")
    its = iterations_of(run)
    last = its[-1]
    st.caption(f"Comparing iteration 0 with iteration {last} on the held-out questions.")
    a = {r["id"]: r for r in rows_of(RESULTS / run / "iter0" / "heldout.jsonl")}
    b = {r["id"]: r for r in rows_of(RESULTS / run / f"iter{last}" / "heldout.jsonl")}
    cand = [i for i in a if i in b and a[i]["em"] == 0 and b[i]["em"] == 1]
    if not cand:
        st.info(f"No held-out question is wrong at iteration 0 and right at iteration {last} yet.")
        return
    state = run_state(run)
    grown = {normalize(rel): int(it) for it, rels in state.get("added", {}).items() for rel in rels}
    scored = sorted(cand, key=lambda i: -visual_score(a[i], b[i], set(grown)))
    labels = {i: f"{a[i]['question'][:90]}  [{a[i]['type']}]" for i in scored}
    pick = st.selectbox(f"{len(cand)} questions went from wrong to right (most visual first)", scored, format_func=labels.get, key="ba_q")
    r0, rN = a[pick], b[pick]
    needed = {normalize(d["expected_relation"]) for d in r0["trace"].get("dead_ends", [])} | {normalize(e["relation"]) for e in r0["trace"].get("events", [])}
    hit = sorted(rel for rel in needed if rel in grown)
    st.markdown(f"**{r0['question']}**")
    if hit:
        st.success("Relation added: " + ", ".join(f"`{rel}` at iteration {grown[rel]}" for rel in hit))
    else:
        st.info("The gap on the iteration-0 path was not a relation added later (the answer changed through other repairs or extraction).")
    left, right = st.columns(2)
    with left:
        trace_panel(r0, "dead", "Iteration 0")
    with right:
        trace_panel(rN, "complete", f"Iteration {last}")


# ------------------------------------------------------------------ entity search
@st.cache_resource
def load_index(mtime):
    return Index()


def tab_entities():
    ix = load_index((config.INDEX_PATH).stat().st_mtime)
    text = st.text_input("Search entities by name or alias", placeholder="e.g. Tuset Street, Terrence Malick, American")
    if not text:
        st.caption(f"{len(ix.d['display']):,} entities in the index.")
        return
    q = normalize(text)
    hits = {}
    for table in (ix.d["names"], ix.d["aliases"]):
        for k, i in table.items():
            if q in k:
                hits.setdefault(i, ix.d["display"].get(str(i), k))
    if not hits:
        st.warning("No match.")
        return
    ids = sorted(hits, key=lambda i: (normalize(hits[i]) != q, len(hits[i]), hits[i]))[:50]
    pick = st.selectbox(f"{len(hits)} matches", ids, format_func=lambda i: f"{hits[i]}  (id {i})")
    g = get_graph()
    try:
        props = g.read("MATCH (n:Entity {id: $id}) RETURN n.name AS name, n.aliases AS aliases", id=pick)[0]
        attrs = {}
        for p in config.LITERAL_PROPS + ["date_of_death"]:
            r = g.read(f"MATCH (n:Entity {{id: $id}}) RETURN n.{p} AS raw, n.{p}_norm AS iso", id=pick)
            if r and r[0]["raw"]:
                attrs[p] = r[0]
        out = g.read("MATCH (a:Entity {id: $id})-[r:REL]->(b:Entity) RETURN r.type AS relation, b.name AS entity, r.confidence AS confidence, r.src_chunk AS chunk, r.created_iter AS iteration", id=pick)
        inc = g.read("MATCH (a:Entity)-[r:REL]->(b:Entity {id: $id}) RETURN r.type AS relation, a.name AS entity, r.confidence AS confidence, r.src_chunk AS chunk, r.created_iter AS iteration", id=pick)
        chunks = g.read("MATCH (c:Chunk)-[r:MENTIONS]->(e:Entity {id: $id}) RETURN c.title AS title, c.text AS text", id=pick)
    except Exception as e:  # noqa: BLE001
        st.error(f"HydraDB is not reachable: {e}")
        return
    st.markdown(f"### {props['name']}")
    if props.get("aliases"):
        st.caption("aliases: " + props["aliases"].replace("|", ", "))
    if attrs:
        st.dataframe(pd.DataFrame([{"attribute": k.replace("_", " "), "value": v["raw"], "ISO": v["iso"]} for k, v in attrs.items()]), hide_index=True)
    c1, c2 = st.columns(2)
    c1.markdown(f"**Outgoing** ({len(out)})")
    c1.dataframe(pd.DataFrame(out), hide_index=True, width="stretch")
    c2.markdown(f"**Incoming** ({len(inc)})")
    c2.dataframe(pd.DataFrame(inc), hide_index=True, width="stretch")
    for ch in chunks:
        with st.expander(f"Paragraph: {ch['title']}"):
            st.write(ch["text"])


# ------------------------------------------------------------------ query trace
def tab_trace():
    runs = list(runs_available()) + ["iter0_static_graph", "iter0_bm25"]
    c1, c2, c3 = st.columns(3)
    run = c1.selectbox("Run", runs, key="tr_run")
    if run.startswith("iter0_"):
        files = {"heldout": RESULTS / run / "heldout.jsonl"}
    else:
        its = iterations_of(run)
        if not its:
            st.info("No iterations yet.")
            return
        it = c2.selectbox("Iteration", its, index=len(its) - 1, key="tr_it")
        files = {n: RESULTS / run / f"iter{it}" / f"{n}.jsonl" for n in ("heldout", "feedback")}
    split = c3.selectbox("Split", [n for n, p in files.items() if p.exists()], key="tr_split")
    rows = rows_of(files[split])
    if not rows:
        st.info("No rows.")
        return
    labels = {i: f"{'✅' if r['em'] == 1 else '❌'} {r['question'][:95]}  [{r['type']}]" for i, r in enumerate(rows)}
    pick = st.selectbox("Question", list(labels), format_func=labels.get, key="tr_q")
    row = rows[pick]
    t = row["trace"]
    st.markdown(f"**{row['question']}**")
    st.markdown(f"Prediction **{row['prediction'] or '(none)'}**, gold **{row['gold']}**, EM {row['em']:.0f}, F1 {row['f1']:.2f}")
    if t.get("reasoning"):
        st.caption("reasoning: " + t["reasoning"])
    if "plan" not in t:  # BM25 traces carry chunks only
        st.dataframe(pd.DataFrame(t["chunks"]), hide_index=True)
        return
    st.markdown(f"Plan: type `{t['plan']['question_type']}`, chain `{' → '.join(t['plan']['relation_chain'])}`, seeds {t['plan']['seeds']}, resolved {[(s['name'], s['id']) for s in t['seeds']]}, unresolved {t['unresolved_seeds']}")
    mode = "dead" if t.get("dead_ends") and row["em"] != 1 else "complete"
    legend(mode)
    st.iframe(trace_html(t, mode), height=540)
    if t.get("dead_ends") or t.get("events"):
        st.markdown("**Dead ends / gaps**")
        st.dataframe(pd.DataFrame(t.get("events") or t["dead_ends"]), hide_index=True)
    if t.get("query_extraction"):
        st.markdown("**Query-time extraction**")
        st.dataframe(pd.DataFrame(t["query_extraction"]), hide_index=True)
    st.markdown("**Paths**")
    st.dataframe(pd.DataFrame([{"score": p["score"], "path": p["nodes"][0]["name"] + "".join(f" -[{e['type']}]-> {n['name']}" for e, n in zip(p["edges"], p["nodes"][1:]))} for p in t["paths"]]), hide_index=True, width="stretch")
    if t.get("attributes"):
        st.markdown("**Entity attributes**")
        st.json(t["attributes"], expanded=False)
    if t.get("chunks"):
        st.markdown("**Source paragraphs used:** " + ", ".join(c["title"] for c in t["chunks"]))


# ------------------------------------------------------------------ graph state (sidebar)
def sidebar_graph_state():
    """Which graph state is loaded. `--snapshot NAME` (after `--` on the command line) names the snapshot the
    live graph is expected to match; without it the snapshot recorded when the graph was last restored is used."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot")
    args, _ = ap.parse_known_args(sys.argv[1:])
    live = get_live()
    expected = args.snapshot or live.get("snapshot")
    with st.sidebar:
        st.subheader("Graph state")
        it = live.get("iteration")
        where = live.get("run", "unknown run") + (f", after iteration {it}" if it is not None and it >= 0 else ", iteration-0 graph" if it == -1 else "")
        try:
            g = get_graph()
            now = {"entities": g.read("MATCH (n:Entity) RETURN count(*) AS n")[0]["n"], "REL edges": len(g.load_edges())}
        except Exception as e:  # noqa: BLE001
            st.error(f"HydraDB is not reachable: {e}")
            return
        st.caption(f"Loaded: **{where}**. Live graph: {now['entities']:,} entities, {now['REL edges']:,} REL edges.")
        if expected:
            mp = snap_dir(expected) / "meta.json"
            if not mp.exists():
                st.warning(f"Snapshot '{expected}' not found in data/snapshots.")
            else:
                meta = json.loads(mp.read_text())
                same = meta["entities"] == now["entities"] and meta["REL edges"] == now["REL edges"]
                st.caption(("✅ matches" if same else "⚠️ differs from") + f" snapshot **{expected}** ({meta['entities']:,} entities, {meta['REL edges']:,} REL edges).")
        else:
            st.caption("Not tied to a saved snapshot (the learning loop has changed it since the last restore).")


# ------------------------------------------------------------------ main
sidebar_graph_state()
st.title("Self-improving graph on HydraDB")
tabs = st.tabs(["Learning curve", "Mutation log", "Before / after", "Entity search", "Query trace"])
with tabs[0]:
    tab_curve()
with tabs[1]:
    tab_mutations()
with tabs[2]:
    tab_before_after()
with tabs[3]:
    tab_entities()
with tabs[4]:
    tab_trace()
