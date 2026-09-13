"""Thin Groq client. If GROQ_API_KEY is unset, callers fall back to
deterministic heuristics so the whole benchmark runs offline (mock mode)."""
import json
from contextlib import contextmanager
from ..config import GROQ_API_KEY, GROQ_MODEL, GROQ_REASONING_EFFORT, GROQ_TEMPERATURE

class LLMTruncated(ValueError):
    """The model used its whole output budget (usually on reasoning) before answering."""

_disabled = False

def llm_available() -> bool:
    return bool(GROQ_API_KEY) and not _disabled

@contextmanager
def llm_disabled():
    """Temporarily use the rule-based extractor (e.g. a deterministic benchmark)."""
    global _disabled
    previous, _disabled = _disabled, True
    try:
        yield
    finally:
        _disabled = previous

def complete_json(system: str, user: str, max_tokens: int = 2048) -> dict:
    """Ask the model to answer with strict JSON; parse and return it."""
    # Imported lazily so mock mode stays stdlib-only (no groq package needed).
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system + "\nRespond with ONLY valid JSON. No prose, no markdown fences."},
            {"role": "user", "content": user},
        ],
        temperature=GROQ_TEMPERATURE,
        max_completion_tokens=max_tokens,
        top_p=1,
        reasoning_effort=GROQ_REASONING_EFFORT,
        stream=True,
        stop=None,
    )
    pieces, finish = [], None
    for chunk in completion:
        if not chunk.choices:
            continue
        pieces.append(chunk.choices[0].delta.content or "")
        finish = chunk.choices[0].finish_reason or finish
    text = "".join(pieces).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except ValueError as e:
        if finish == "length":
            raise LLMTruncated(f"model hit the {max_tokens}-token output limit before "
                               "finishing its answer") from e
        raise
