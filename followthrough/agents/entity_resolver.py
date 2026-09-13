"""Agent 2 — Entity Resolution.
Maps names in a commitment to concrete app entities by SEARCHING the connected
apps (find_contact / find_user / find_channel / find_record).
Clarify-don't-guess: ambiguous or low-confidence => needs_clarification=True,
and the executor will refuse to act on it."""
import re
from ..config import MIN_ENTITY_CONFIDENCE

NAME_PAT = re.compile(
    r"(?:to|with|for|loop in|looping in|cc|mention|tag|ping)\s+((?:[A-Z][a-z]+\s?){1,2})")

def _extract_names(text: str) -> list[str]:
    names = [m.strip() for m in NAME_PAT.findall(text)]
    # drop non-person tokens the pattern can catch
    stop = {"Slack", "Gmail", "Airtable", "Calendar", "Monday", "Tuesday", "Wednesday",
            "Thursday", "Friday", "The"}
    return [n for n in names if n.split()[0] not in stop]

def _score(query: str, candidate_name: str) -> float:
    q, c = query.lower().split(), candidate_name.lower().split()
    if query.lower() == candidate_name.lower():
        return 1.0
    if all(t in c for t in q):           # "Alex Kim" fully inside candidate
        return 0.95
    if q and (q[0] == c[0]):             # first-name-only match
        return 0.9
    if q and (c[0].startswith(q[0]) or q[0].startswith(c[0])):
        return 0.85                       # partial-first-name (Priya ~ Priyanka)
    return 0.0

def _resolve_against(candidates: list[dict], query: str, id_key: str):
    scored = sorted(((c, _score(query, c["name"])) for c in candidates),
                    key=lambda x: -x[1])
    scored = [s for s in scored if s[1] > 0]
    if not scored:
        return None, 0.0, "no_match", []
    top, top_score = scored[0]
    runners = [s for s in scored[1:] if s[1] >= top_score - 0.1]
    if runners and top_score < 1.0:
        return None, top_score, "ambiguous", [c["name"] for c, _ in scored[:3]]
    if top_score < MIN_ENTITY_CONFIDENCE:
        return None, top_score, "low_confidence", [top["name"]]
    return top, top_score, "resolved", []

def resolve(commitments: list[dict], apps: dict) -> list[dict]:
    resolved = []
    for c in commitments:
        text, tl = c["text"], c["text"].lower()
        names = _extract_names(text)
        ent = {"commitment_id": c["id"], "names": names, "resolutions": [],
               "needs_clarification": False, "clarification": None}
        for name in names:
            hit = None
            if any(k in tl for k in ("email", "send", "deck", "report", "doc")) and "slack" not in tl:
                cands = apps["gmail"].find_contact(name)
                top, conf, status, opts = _resolve_against(cands, name, "email")
                hit = {"name": name, "app": "gmail", "status": status, "confidence": conf,
                       "id": top["email"] if top else None, "options": opts}
            elif "slack" in tl or "channel" in tl or "post" in tl:
                cands = apps["slack"].find_user(name)
                top, conf, status, opts = _resolve_against(cands, name, "id")
                hit = {"name": name, "app": "slack", "status": status, "confidence": conf,
                       "id": top["id"] if top else None, "options": opts}
            if hit:
                ent["resolutions"].append(hit)
                if hit["status"] != "resolved":
                    ent["needs_clarification"] = True
                    ent["clarification"] = (
                        f"Which '{name}' did you mean? Candidates: {hit['options']}"
                        if hit["status"] == "ambiguous" else
                        f"Could not confidently resolve '{name}' ({hit['status']}).")
        # airtable deal reference
        m = (re.search(r"([A-Z][A-Za-z]+)\s+(?:record|deal)\b", text)
             or re.search(r"(?:deal|record)\s+for\s+(?:the\s+)?([A-Z][A-Za-z]+)", text))
        if m and ("airtable" in tl or "deal" in tl):
            cands = [{"name": r["fields"].get("Name", ""), "id": r["id"]}
                     for r in apps["airtable"].find_record(m.group(1))]
            top, conf, status, opts = _resolve_against(cands, m.group(1), "id")
            ent["resolutions"].append({"name": m.group(1), "app": "airtable",
                                       "status": status, "confidence": conf,
                                       "id": top["id"] if top else None, "options": opts})
            if status != "resolved":
                ent["needs_clarification"] = True
                ent["clarification"] = f"Ambiguous Airtable record '{m.group(1)}': {opts}"
        resolved.append(ent)
    return resolved
