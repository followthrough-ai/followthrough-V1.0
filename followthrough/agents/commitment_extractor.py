"""Agent 1 — Commitment Extraction.
Extracts explicit, actionable commitments only. Never invents; skips hedged
('might', 'maybe') statements; merges duplicate mentions of the same commitment.

Long transcripts are split into parts that fit the Groq tokens-per-minute limit
(free tier: 8000) and sent one at a time, pausing when the limit needs it. A part
the LLM can't handle falls back to the rule-based extractor with a visible warning."""
import re, sys, time
from .llm_client import llm_available, complete_json, LLMTruncated
from ..config import GROQ_TPM_LIMIT, GROQ_CHUNK_CHARS

SYSTEM = """You extract EXPLICIT commitments from meeting transcripts.
Rules:
- A commitment is a concrete action someone promised, or was asked, to do:
  "I'll send X", "Please post Y", "Can you email Z", "Let's put W on the calendar".
- Requests to someone else ("Please ...", "Can you ...") ARE commitments.
- Hedged/hypothetical statements ("might", "maybe", "we could") are NOT commitments.
- "text" is the full sentence containing the action, copied word for word from the
  transcript, without the speaker name.
- Never split one sentence into several commitments: "post the update and loop in Alex" is ONE.
- If the same commitment is stated twice, output it ONCE.
- Check every line. Do not invent commitments not supported by the transcript.
Output: {"commitments":[{"id":"pred_001","text":"...","source_line":"verbatim line"}]}"""

# Reasoning models spend part of the output budget thinking before they answer.
MAX_OUTPUT_TOKENS = 4096
EXPECTED_OUTPUT_TOKENS = 2000

HEDGES = ("might", "maybe", "could ", "thinking about", "not sure", "no need", "don't ", "won't need")
TRIGGERS = (r"\bi'?ll\b", r"\bi will\b", r"\bplease\b", r"\blet'?s\b", r"\bcan you\b", r"\bmake sure\b")

def _norm(text: str) -> str:
    norm = re.sub(r"\b(i'?ll|i will|please|let'?s|can you|and|also|again,?)\b", "", text.lower())
    norm = re.sub(r"[^a-z0-9 ]", "", norm)
    return " ".join(sorted(set(norm.split())))

def _heuristic(transcript: str) -> list[dict]:
    out, seen = [], set()
    for raw in transcript.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        text = line.split(":", 1)[1].strip()
        for sent in re.split(r"(?<=[.!?])\s+", text):
            s = sent.strip().rstrip(".")
            sl = s.lower()
            if not s or any(h in sl for h in HEDGES):
                continue
            if not any(re.search(t, sl) for t in TRIGGERS):
                continue
            key = _norm(s)
            if any(_similar(key, k) for k in seen):
                continue
            seen.add(key)
            out.append({"id": f"pred_{len(out)+1:03d}", "text": s, "source_line": line})
    return out

def _similar(a: str, b: str) -> bool:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) > 0.6

progress_hook = None   # optional callable(str), e.g. the web UI's live job log

def _say(msg: str):
    print(f"[extractor] {msg}", file=sys.stderr, flush=True)
    if progress_hook:
        progress_hook(msg)

class _TokenBudget:
    """Rolling 60-second window of tokens. Groq checks a request's prompt size
    up front and counts the generated tokens against the same per-minute limit."""
    def __init__(self, per_minute: int):
        self.per_minute, self.spent = per_minute, []

    def reserve(self, cost: int, label: str):
        while True:
            now = time.time()
            self.spent = [(t, c) for t, c in self.spent if now - t < 60]
            if not self.spent or sum(c for _, c in self.spent) + cost <= self.per_minute:
                self.spent.append((now, cost))
                return
            wait = 60 - (now - self.spent[0][0]) + 1
            _say(f"{label}: waiting {wait:.0f}s for the Groq rate limit")
            time.sleep(wait)

_BUDGET = _TokenBudget(GROQ_TPM_LIMIT)

def _estimate_tokens(part: str) -> int:
    # Speech transcripts run ~4.3 chars per token; 4 keeps the estimate on the safe side.
    return (len(SYSTEM) + len(part)) // 4 + EXPECTED_OUTPUT_TOKENS + 100

def _split(transcript: str, max_chars: int) -> list[str]:
    """Line-aligned parts of at most ~max_chars. Consecutive parts overlap by two
    short lines so a commitment on a boundary is still seen whole."""
    lines = []
    for line in transcript.splitlines():
        while len(line) > max_chars:
            lines.append(line[:max_chars])
            line = line[max_chars:]
        lines.append(line)
    parts, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) + 1 > max_chars:
            parts.append("\n".join(cur))
            tail = cur[-2:]
            cur = tail if sum(len(l) + 1 for l in tail) <= max_chars // 4 else []
            size = sum(len(l) + 1 for l in cur)
        cur.append(line)
        size += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return [p for p in parts if p.strip()]

def _llm_part(part: str, label: str) -> list[dict]:
    for attempt in (1, 2):
        _BUDGET.reserve(_estimate_tokens(part), label)
        try:
            res = complete_json(SYSTEM, part, max_tokens=MAX_OUTPUT_TOKENS)
            return [c for c in res.get("commitments", []) if isinstance(c, dict) and c.get("text")]
        except Exception as e:
            if attempt == 2:
                raise
            if isinstance(e, LLMTruncated):
                _say(f"{label}: {e}; retrying once")
                continue
            if getattr(e, "status_code", None) in (413, 429):
                _say(f"{label}: Groq rate limit hit, retrying in 60s")
                time.sleep(60)
                continue
            raise

def _dedupe(items: list[dict]) -> list[dict]:
    out, keys = [], []
    for c in items:
        text = str(c["text"]).strip()
        key = _norm(text)
        if any(_similar(key, k) for k in keys):
            continue
        keys.append(key)
        out.append({"id": f"pred_{len(out)+1:03d}", "text": text,
                    "source_line": c.get("source_line", "")})
    return out

def extract_detailed(transcript: str) -> tuple[list[dict], dict]:
    """Returns (commitments, info); info["method"] is "llm", "mixed" or "heuristic"."""
    if not llm_available():
        return _heuristic(transcript), {"method": "heuristic", "parts": 1,
            "warnings": ["Groq is off (no GROQ_API_KEY, or disabled for this run); "
                         "used the rule-based extractor"]}
    # Keep each request (prompt + expected output) under the per-minute limit.
    fit = (GROQ_TPM_LIMIT - EXPECTED_OUTPUT_TOKENS - 100) * 4 - len(SYSTEM)
    parts = _split(transcript, max(2000, min(GROQ_CHUNK_CHARS, fit)))
    found, warnings, llm_ok = [], [], 0
    for i, part in enumerate(parts, 1):
        label = f"part {i}/{len(parts)}"
        if len(parts) > 1:
            _say(f"{label}: sending {len(part):,} chars to Groq")
        try:
            found.extend(_llm_part(part, label))
            llm_ok += 1
        except Exception as e:
            msg = (f"Groq failed on {label} ({str(e)[:160]}); "
                   "used the rule-based extractor for that part")
            warnings.append(msg)
            _say("WARNING: " + msg)
            found.extend(_heuristic(part))
    method = "llm" if llm_ok == len(parts) else "heuristic" if llm_ok == 0 else "mixed"
    return _dedupe(found), {"method": method, "parts": len(parts), "warnings": warnings}

def extract(transcript: str) -> list[dict]:
    return extract_detailed(transcript)[0]
