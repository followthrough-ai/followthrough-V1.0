"""Agent 3 — Action Planning.
Converts each commitment + resolved entities into EXACTLY ONE structured,
validated action. Commitments needing clarification produce a clarification
request instead of an action (clarify-don't-guess invariant)."""
import re

APP_ACTIONS = {"gmail": "send_email", "calendar": "create_event",
               "slack": "send_message", "airtable": "update_record"}

def _infer_app(text: str) -> str | None:
    t = text.lower()
    if "slack" in t or ("post" in t and "channel" in t) or "loop in" in t:
        return "slack"
    if "airtable" in t or "deal stage" in t or ("record" in t and "update" in t):
        return "airtable"
    if "calendar" in t or "schedule" in t or re.search(r"\b\d{1,2}\s?(am|pm)\b", t):
        return "calendar"
    if "email" in t or "send" in t:
        return "gmail"
    return None

DAY = r"(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
TIME = r"(\d{1,2}(?::\d{2})?\s?(?:am|pm))"

def _time_expr(text: str) -> str | None:
    """Normalize to '<day> <time>' regardless of spoken order."""
    t = text.lower()
    m = re.search(DAY + r"\W+(?:at\s+)?" + TIME, t) or \
        re.search(TIME + r"\W+(?:on\s+)?" + DAY, t)
    if m:
        a, b = m.group(1), m.group(2)
        day, tm = (a, b) if re.fullmatch(DAY, a) else (b, a)
        return f"{day} {tm.replace(' ', '')}"
    m = re.search(TIME, t)
    return m.group(1).replace(" ", "") if m else None

def plan(commitments: list[dict], entities: list[dict], apps: dict) -> list[dict]:
    ent_by_c = {e["commitment_id"]: e for e in entities}
    plans = []
    for c in commitments:
        ent = ent_by_c.get(c["id"], {})
        if ent.get("needs_clarification"):
            plans.append({"commitment_id": c["id"], "type": "clarification",
                          "question": ent.get("clarification")})
            continue
        app = _infer_app(c["text"])
        if app is None:
            plans.append({"commitment_id": c["id"], "type": "clarification",
                          "question": f"Cannot determine target app for: {c['text']}"})
            continue
        params, tl = {}, c["text"].lower()
        res = {r["app"]: r for r in ent.get("resolutions", [])}
        if app == "gmail":
            r = res.get("gmail")
            if not r or not r.get("id"):
                plans.append({"commitment_id": c["id"], "type": "clarification",
                              "question": f"No confidently resolved recipient for: {c['text']}"})
                continue
            m = re.search(r"(?:send|share)\s+(?:\w+\s+)?the\s+([\w\s-]+?)(?:\s+to\b|$)", tl)
            params = {"recipient": r["id"],
                      "subject": (m.group(1).strip().title() if m else "Follow-up"),
                      "attachment": m.group(1).strip().replace(" ", "_") if m else None}
        elif app == "calendar":
            t = _time_expr(c["text"])
            if not t:
                plans.append({"commitment_id": c["id"], "type": "clarification",
                              "question": f"No time found for calendar event: {c['text']}"})
                continue
            params = {"title": "Meeting", "time": t}
        elif app == "slack":
            ch = apps["slack"].find_channel("updates") or apps["slack"].find_channel("general")
            r = res.get("slack")
            params = {"channel": ch[0]["id"] if ch else None,
                      "message": c["text"],
                      "mention": r["id"] if r and r.get("id") else None}
            if params["channel"] is None:
                plans.append({"commitment_id": c["id"], "type": "clarification",
                              "question": "No Slack channel found."})
                continue
        elif app == "airtable":
            r = res.get("airtable")
            if not r or not r.get("id"):
                plans.append({"commitment_id": c["id"], "type": "clarification",
                              "question": f"No confidently resolved Airtable record for: {c['text']}"})
                continue
            m = re.search(r"stage\s+to\s+['\"]?([\w-]+)", tl)
            params = {"record_id": r["id"],
                      "fields": {"Stage": m.group(1).strip().title() if m else "Updated"}}
        plans.append({"commitment_id": c["id"], "type": "action",
                      "app": app, "action": APP_ACTIONS[app], "parameters": params})
    return plans
