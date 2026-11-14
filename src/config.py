"""Central configuration. Models, paths, schema and search parameters live here."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- HydraDB ---
HYDRA_URI = os.environ.get("HYDRA_URI", "neo4j://127.0.0.1:7687")
HYDRA_TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")

# --- LLM ---
# Haiku 4.5 for every call (extraction, planning and answering) to stay inside the budget.
EXTRACT_MODEL = "claude-haiku-4-5-20251001"
ANSWER_MODEL = EXTRACT_MODEL
# USD per million tokens (input, output). Checked against Anthropic's pricing page on 2026-11-14:
# Haiku 4.5 is $1 / $5 per MTok, and the Message Batches API is 50% of that.
PRICE_PER_MTOK = {EXTRACT_MODEL: (1.0, 5.0)}
BATCH_DISCOUNT = 0.5
LLM_WORKERS = 4  # maximum concurrent requests
LLM_MAX_TRIES = 5  # attempts on 429 / overloaded, exponential backoff
LLM_CACHE_DIR = ROOT / ".cache" / "llm"
EXTRACT_MAX_TOKENS = 600
PLAN_MAX_TOKENS = 300
ANSWER_MAX_TOKENS = 200

# --- Budget: hard cap on total spend for the whole project is $10; this leaves a $1 margin ---
BUDGET_TOTAL_USD = 9.00
PHASE_BUDGETS = {"ingest": 2.50, "smoke": 1.00, "learning": 4.50, "reserve": 1.00}  # reserve needs --use-reserve
LEDGER_PATH = ROOT / "data" / "state" / "spend.json"

# --- Data ---
SPLIT_DIR = ROOT / "data" / "split"
STATE_DIR = ROOT / "data" / "state"
INDEX_PATH = STATE_DIR / "index.json"
INGESTED_PATH = STATE_DIR / "ingested.json"

# --- Seed schema: relation -> (property name for literals, or None when the object is an entity, description)
# Literal objects become properties on the subject entity and never nodes.
SEED_RELATIONS = {
    "director": (None, "the director of a film"),
    "date of birth": ("date_of_birth", "the date a person was born (never a death date or any other date)"),
    "publication date": ("publication_date", "the date a film or work was released or published (a date)"),
    "country of citizenship": (None, "the country a person is a citizen of"),
    "place of birth": (None, "the place a person was born"),
    "country of origin": (None, "the country a film or work originates from"),
    "performer": (None, "the performer of a song or work"),
    "composer": (None, "the composer of a song or work"),
}
LITERAL_PROPS = sorted({p for p, _ in SEED_RELATIONS.values() if p})
QUESTION_TYPES = ["comparison", "inference", "compositional", "bridge_comparison"]
ANCHOR_QTYPE = "*"  # RelType node per relation that EXTRACTED edges point at

# --- Query: identical across the learned, random and static runs, and recorded in every run's output ---
BEAM_K = 5
MAX_HOPS = 3
FETCH_LIMIT = 200
CHAIN_BOOST = 3.0  # score multiplier when an edge matches the relation the planner expected at that hop
ANSWER_MAX_CHUNKS = 5  # source paragraphs in the answer prompt
ANSWER_SYSTEM = "You answer questions using only the supplied graph facts and source paragraphs. Reply with the shortest possible answer."
ANSWER_INSTRUCTION = (
    "First give one sentence of reasoning, then the shortest answer: an entity name, a date, or yes/no. "
    "Dates are given as the original text and in ISO form; compare dates using the ISO form. "
    "If the facts do not contain the answer, give your best guess from them."
)


def run_params():
    """Everything that must match across runs being compared."""
    import hashlib

    return {
        "beam_k": BEAM_K, "max_hops": MAX_HOPS, "fetch_limit": FETCH_LIMIT, "chain_boost": CHAIN_BOOST,
        "answer_max_chunks": ANSWER_MAX_CHUNKS, "answer_max_tokens": ANSWER_MAX_TOKENS,
        "answer_reasoning": "one sentence before the answer", "dates_in_prompt": "raw text plus ISO form",
        "dead_end_rule": "planned-chain branches only; leaves and literal steps excluded",
        "performer_rule": "performer edges dropped when the subject also has a director edge",
        "min_confidence": 0.6,
        "extract_model": EXTRACT_MODEL, "answer_model": ANSWER_MODEL,
        "answer_prompt_sha": hashlib.sha256((ANSWER_SYSTEM + ANSWER_INSTRUCTION).encode()).hexdigest()[:12],
    }
