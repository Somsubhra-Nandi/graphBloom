"""LLM wrapper: disk-cached calls, structured output via forced tool use, and a hard spend budget.

- Every call carries a phase tag (ingest, smoke, learning). Cost comes from the usage tokens the API returns
  and is kept in a persisted ledger (data/state/spend.json). Before a call its cost is estimated; if the
  ledger plus the estimate would break the total or the phase budget, BudgetExceeded is raised.
- Cached calls cost $0 and never touch the ledger.
- Rate limits: at most config.LLM_WORKERS requests at once; 429 / overloaded retried with exponential
  backoff up to config.LLM_MAX_TRIES; rate-limit response headers slow the next request down.
- The API key is read from .env (ANTHROPIC_API_KEY) and is never printed or written anywhere.
"""
import atexit
import hashlib
import json
import os
import random
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from src import config

load_dotenv(config.ROOT / ".env")

_lock = threading.Lock()
_sem = threading.Semaphore(config.LLM_WORKERS)
_client = None
_use_reserve = False
_inflight = {}  # reservation id -> (phase, estimated cost) for calls that have started but not settled
_inflight_n = 0
_run = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "retries": 0, "truncated": 0}
_throttle_until = 0.0


class BudgetExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------- ledger
def _empty_ledger():
    return {"total": 0.0, "by_phase": {}, "by_phase_calls": {}, "by_phase_out_tokens": {}, "pending": {}}


def _load():
    if config.LEDGER_PATH.exists():
        led = json.loads(config.LEDGER_PATH.read_text())
        for k, v in _empty_ledger().items():
            led.setdefault(k, v)
        return led
    return _empty_ledger()


def _save(led):
    config.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.LEDGER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(led, indent=1))
    os.replace(tmp, config.LEDGER_PATH)


def set_use_reserve(flag):
    """Scripts call this with their --use-reserve flag. Without it the reserve budget is unusable."""
    global _use_reserve
    _use_reserve = bool(flag)


def _committed(led):
    """Spend so far plus money reserved for batches and calls still in flight."""
    pend_by_phase, total = {}, led["total"]
    for p in led["pending"].values():
        pend_by_phase[p["phase"]] = pend_by_phase.get(p["phase"], 0.0) + p["est"]
        total += p["est"]
    for phase, est in _inflight.values():
        pend_by_phase[phase] = pend_by_phase.get(phase, 0.0) + est
        total += est
    return total, pend_by_phase


def _reserve_left(led, pend_by_phase):
    """Reserve = what the phases have not already overrun into it."""
    used = led["by_phase"].get("reserve", 0.0)
    for ph, b in config.PHASE_BUDGETS.items():
        if ph != "reserve":
            used += max(0.0, led["by_phase"].get(ph, 0.0) + pend_by_phase.get(ph, 0.0) - b)
    return max(0.0, config.PHASE_BUDGETS["reserve"] - used)


def _check(led, phase, est):
    """Raise BudgetExceeded if `est` more dollars in `phase` would break the total or the phase budget."""
    if phase not in config.PHASE_BUDGETS or phase == "reserve":
        raise ValueError(f"unknown phase {phase!r}; use one of ingest, smoke, learning")
    total, pend = _committed(led)
    if total + est > config.BUDGET_TOTAL_USD:
        raise BudgetExceeded(f"total budget: ${total:.4f} committed + ${est:.4f} estimate > ${config.BUDGET_TOTAL_USD:.2f}")
    spent_phase = led["by_phase"].get(phase, 0.0) + pend.get(phase, 0.0)
    allowed = config.PHASE_BUDGETS[phase] + (_reserve_left(led, pend) if _use_reserve else 0.0)
    if spent_phase + est > allowed:
        hint = "" if _use_reserve else " (pass --use-reserve to allow the $1 reserve)"
        raise BudgetExceeded(f"phase '{phase}': ${spent_phase:.4f} committed + ${est:.4f} estimate > ${allowed:.2f}{hint}")


def price(model, in_tok, out_tok, batch=False):
    pin, pout = config.PRICE_PER_MTOK[model]
    c = (in_tok * pin + out_tok * pout) / 1e6
    return c * config.BATCH_DISCOUNT if batch else c


def estimate_cost(model, system, prompt, schema, max_tokens, phase, batch=False):
    """Conservative pre-call estimate: input at 3 chars/token; output from the phase's observed average
    (x1.5), or 60% of max_tokens until five calls have been seen, never above max_tokens."""
    in_tok = (len(system) + len(prompt) + (len(json.dumps(schema)) if schema else 0)) / 3 + 50
    with _lock:
        led = _load()
    n = led["by_phase_calls"].get(phase, 0)
    out_tok = min(max_tokens, 1.5 * led["by_phase_out_tokens"].get(phase, 0) / n) if n >= 5 else 0.6 * max_tokens
    return price(model, in_tok, max(out_tok, 20), batch)


def _settle(phase, cost, in_tok, out_tok, reservation=None, pending_id=None):
    with _lock:
        led = _load()
        if pending_id:
            led["pending"].pop(pending_id, None)
        led["total"] = round(led["total"] + cost, 8)
        led["by_phase"][phase] = round(led["by_phase"].get(phase, 0.0) + cost, 8)
        led["by_phase_calls"][phase] = led["by_phase_calls"].get(phase, 0) + 1
        led["by_phase_out_tokens"][phase] = led["by_phase_out_tokens"].get(phase, 0) + out_tok
        _save(led)
        _inflight.pop(reservation, None)
        _run["calls"] += 1
        _run["input_tokens"] += in_tok
        _run["output_tokens"] += out_tok
        _run["cost"] += cost


# ---------------------------------------------------------------- cache / client
def _key(model, system, prompt, schema, params):
    blob = json.dumps([model, system, prompt, schema, params], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_path(key):
    return config.LLM_CACHE_DIR / key[:2] / f"{key}.json"


def _cache_get(key):
    p = _cache_path(key)
    if p.exists():
        with _lock:
            _run["cache_hits"] += 1
        return True, json.loads(p.read_text())["result"]
    return False, None


def _cache_put(key, model, result, usage):
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"model": model, "result": result, "usage": usage}, ensure_ascii=False))
    os.replace(tmp, p)


def _get_client():
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set (put it in .env)")
        import anthropic

        ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")  # needed when the key is not scoped to a workspace
        headers = {"anthropic-workspace-id": ws} if ws else None
        _client = anthropic.Anthropic(max_retries=0, default_headers=headers)  # retries are handled here so every try is counted
    return _client


def _kwargs(model, system, prompt, schema, max_tokens, temperature):
    kw = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
    # temperature is not sent: this API rejects the parameter for the model ("Extra inputs are not permitted").
    # `temperature` stays in the cache key only so existing keys are stable.
    if system:
        kw["system"] = system
    if schema:
        kw["tools"] = [{"name": "respond", "description": "Return the structured result.", "input_schema": schema}]
        kw["tool_choice"] = {"type": "tool", "name": "respond"}
    return kw


def _parse(content, schema, stop_reason):
    """Return the structured dict (or text). None if the model never produced the tool call."""
    if schema:
        for b in content:
            if b.type == "tool_use":
                if stop_reason == "max_tokens":
                    with _lock:
                        _run["truncated"] += 1
                return b.input
        return None
    return "".join(b.text for b in content if b.type == "text")


def _wait_for_rate_limit():
    wait = _throttle_until - time.time()
    if wait > 0:
        time.sleep(min(wait, 60))


def _note_headers(headers):
    """If the response says the request or token window is used up, pause until it resets."""
    global _throttle_until
    try:
        for kind in ("requests", "tokens"):
            rem = headers.get(f"anthropic-ratelimit-{kind}-remaining")
            reset = headers.get(f"anthropic-ratelimit-{kind}-reset")
            if rem is not None and int(rem) <= 1 and reset:
                t = datetime.fromisoformat(reset.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
                _throttle_until = max(_throttle_until, t)
    except (ValueError, TypeError):
        pass


# ---------------------------------------------------------------- public API
def call(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0, *, phase):
    """Return text, or a dict when `schema` (a JSON schema for the output object) is given."""
    params = {"max_tokens": max_tokens, "temperature": temperature}
    key = _key(model, system, prompt, schema, params)
    hit, result = _cache_get(key)
    if hit:
        return result

    est = estimate_cost(model, system, prompt, schema, max_tokens, phase)
    global _inflight_n
    with _lock:
        _check(_load(), phase, est)  # raises BudgetExceeded; nothing is retried
        _inflight_n += 1
        rid = _inflight_n
        _inflight[rid] = (phase, est)

    import anthropic

    try:
        with _sem:
            for attempt in range(1, config.LLM_MAX_TRIES + 1):
                _wait_for_rate_limit()
                try:
                    kw = _kwargs(model, system, prompt, schema, max_tokens, temperature)
                    raw = _get_client().messages.with_raw_response.create(**kw)
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
                    if attempt == config.LLM_MAX_TRIES:
                        raise
                    headers = getattr(getattr(e, "response", None), "headers", {}) or {}
                    ra = headers.get("retry-after")
                    delay = float(ra) if ra else 2 ** attempt + random.random()
                    with _lock:
                        _run["retries"] += 1
                    time.sleep(min(delay, 60))
            _note_headers(raw.headers)
            resp = raw.parse()
    except BaseException:
        with _lock:
            _inflight.pop(rid, None)
        raise

    in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
    _settle(phase, price(model, in_tok, out_tok), in_tok, out_tok, reservation=rid)
    result = _parse(resp.content, schema, resp.stop_reason)
    if result is not None:
        _cache_put(key, model, result, [in_tok, out_tok])
    return result


def cache_lookup(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0):
    """(hit, result) for a call without making it and without touching the ledger or stats."""
    p = _cache_path(_key(model, system, prompt, schema, {"max_tokens": max_tokens, "temperature": temperature}))
    return (True, json.loads(p.read_text())["result"]) if p.exists() else (False, None)


def pending_batches():
    """Batches submitted but not yet settled: {batch_id: {phase, est, n, model}}."""
    with _lock:
        return dict(_load()["pending"])


def cached_usage(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0):
    """(input_tokens, output_tokens) recorded when this call was made, or None if it is not cached."""
    p = _cache_path(_key(model, system, prompt, schema, {"max_tokens": max_tokens, "temperature": temperature}))
    return json.loads(p.read_text())["usage"] if p.exists() else None


def submit_batch(requests, phase, model=config.EXTRACT_MODEL):
    """Submit Message Batches requests at 50% price. `requests`: dicts with custom_id, prompt, system, schema,
    max_tokens (same shape as call()). Cached requests are skipped. Returns (batch_id or None, n_submitted).
    The estimated cost is reserved in the ledger until collect_batch settles it from the real usage."""
    todo = []
    for r in requests:
        params = {"max_tokens": r["max_tokens"], "temperature": 0.0}
        if not _cache_path(_key(model, r.get("system", ""), r["prompt"], r.get("schema"), params)).exists():
            todo.append(r)
    if not todo:
        return None, 0
    est = sum(estimate_cost(model, r.get("system", ""), r["prompt"], r.get("schema"), r["max_tokens"], phase, batch=True) for r in todo)
    with _lock:
        _check(_load(), phase, est)
    batch_reqs = [{"custom_id": r["custom_id"], "params": _kwargs(model, r.get("system", ""), r["prompt"], r.get("schema"), r["max_tokens"], 0.0)} for r in todo]
    batch = _get_client().messages.batches.create(requests=batch_reqs)
    with _lock:
        led = _load()
        led["pending"][batch.id] = {"phase": phase, "est": round(est, 6), "n": len(todo), "model": model}
        _save(led)
    return batch.id, len(todo)


def collect_batch(batch_id, requests, phase, model=config.EXTRACT_MODEL, poll=15, timeout=3600):
    """Wait for a batch, cache each result under the same key a normal call() would use, and settle the
    ledger from the real usage at the batch price. Returns {custom_id: result or None} and a status summary."""
    client = _get_client()
    t0 = time.time()
    import anthropic

    while True:
        try:
            b = client.messages.batches.retrieve(batch_id)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.InternalServerError):
            time.sleep(poll)  # transient network error while polling; the batch keeps running server side
            continue
        if b.processing_status == "ended":
            break
        if time.time() - t0 > timeout:
            return {}, {"status": "timeout", "counts": b.request_counts.model_dump()}
        time.sleep(poll)
    by_id = {r["custom_id"]: r for r in requests}
    out, cost, in_sum, out_sum, failed = {}, 0.0, 0, 0, 0
    for item in client.messages.batches.results(batch_id):
        r = by_id.get(item.custom_id)
        if item.result.type != "succeeded" or r is None:
            failed += 1
            out[item.custom_id] = None
            continue
        msg = item.result.message
        res = _parse(msg.content, r.get("schema"), msg.stop_reason)
        in_tok, out_tok = msg.usage.input_tokens, msg.usage.output_tokens
        cost += price(model, in_tok, out_tok, batch=True)
        in_sum += in_tok
        out_sum += out_tok
        out[item.custom_id] = res
        if res is not None:
            _cache_put(_key(model, r.get("system", ""), r["prompt"], r.get("schema"), {"max_tokens": r["max_tokens"], "temperature": 0.0}), model, res, [in_tok, out_tok])
    n_ok = len(out) - failed
    with _lock:
        led = _load()
        led["pending"].pop(batch_id, None)
        led["total"] = round(led["total"] + cost, 8)
        led["by_phase"][phase] = round(led["by_phase"].get(phase, 0.0) + cost, 8)
        led["by_phase_calls"][phase] = led["by_phase_calls"].get(phase, 0) + n_ok
        led["by_phase_out_tokens"][phase] = led["by_phase_out_tokens"].get(phase, 0) + out_sum
        _save(led)
        _run["calls"] += n_ok
        _run["input_tokens"] += in_sum
        _run["output_tokens"] += out_sum
        _run["cost"] += cost
    return out, {"status": "ended", "succeeded": n_ok, "failed": failed, "cost": cost, "input_tokens": in_sum, "output_tokens": out_sum}


# ---------------------------------------------------------------- reporting
def total_spent():
    """Cumulative dollars in the persisted ledger."""
    with _lock:
        return _load()["total"]


def run_stats():
    """Calls, tokens and cost of this process so far (fresh calls only; cache hits are free)."""
    with _lock:
        return dict(_run)


def spend_summary():
    with _lock:
        led = _load()
    total, pend = _committed(led)
    rows = []
    for ph, b in config.PHASE_BUDGETS.items():
        if ph == "reserve":
            left = _reserve_left(led, pend)
            rows.append(f"reserve ${left:.2f} left of ${b:.2f}")
        else:
            rows.append(f"{ph} ${led['by_phase'].get(ph, 0.0):.4f} / ${b:.2f}")
    return f"total ${led['total']:.4f} of ${config.BUDGET_TOTAL_USD:.2f} (+${total - led['total']:.4f} pending) | " + " | ".join(rows)


def log_stats(label):
    """Print this run's usage and append it to .cache/llm_runs.jsonl (no secrets are logged)."""
    s = dict(_run)
    print(f"[llm:{label}] fresh_calls={s['calls']} cache_hits={s['cache_hits']} in={s['input_tokens']} out={s['output_tokens']} "
          f"cost=${s['cost']:.4f} retries={s['retries']} truncated={s['truncated']}")
    config.LLM_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LLM_CACHE_DIR.parent / "llm_runs.jsonl", "a") as f:
        f.write(json.dumps({"label": label, "time": time.time(), **s}) + "\n")


@atexit.register
def _print_total():
    if _run["calls"] or _run["cache_hits"] or config.LEDGER_PATH.exists():
        print("[spend] " + spend_summary())
