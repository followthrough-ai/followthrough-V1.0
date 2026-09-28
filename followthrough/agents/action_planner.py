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

# ----- wording: what the recipient actually reads ---------------------------------
# Only title/message/body are written here. The fields that make up the live
# idempotency key (recipient, subject, time, channel, mention, record, fields)
# are left exactly as before, so upgrading never re-sends an action.

def _when(expr: str) -> str:
    """'friday 10am' -> 'Friday at 10am'; '3pm' -> '3pm'."""
    parts = expr.split()
    if len(parts) != 2:
        return expr
    day = parts[0] if parts[0] in ("today", "tomorrow") else parts[0].capitalize()
    return f"{day} at {parts[1]}"

def _email_topic(text: str, subject: str) -> str | None:
    """What the email is about, for the body only (the subject is left as planned)."""
    if subject != "Follow-up":
        return subject.lower()
    m = re.search(r"\b(?:send|share|email|forward)\s+(?:\w+\s+)?the\s+([\w\s-]+?)(?:\s+to\b|$)", text.lower())
    return m.group(1).strip() if m else None

_NOT_A_TITLE = {"the calendar", "calendar", "it", "that", "this", "at", "on", "for", "next week"}

def _event_title(text: str, context: dict) -> str:
    t = re.sub(TIME, " ", re.sub(DAY, " ", text, flags=re.I), flags=re.I)
    t = re.sub(r"\s+", " ", t)
    for pat in (r"\bfor\s+(?:the\s+|a\s+|an\s+|our\s+)?([a-z][\w\s-]{2,40}?)\s*(?:[.,!?]|$|\bwith\b|\bon\b|\bat\b)",
                r"\b(?:schedule|book|set up|put)\s+(?:a|an|the|our)\s+([a-z][\w\s-]{2,40}?)\s*(?:\bfor\b|\bon\b|\bat\b|[.,!?]|$)"):
        m = re.search(pat, t, flags=re.I)
        title = m.group(1).strip() if m else ""
        if title and title.lower() not in _NOT_A_TITLE:
            return title[0].upper() + title[1:]
    return f"Follow-up: {context['meeting']}" if context.get("meeting") else "Follow-up meeting"

def _slack_topic(text: str) -> str | None:
    m = re.search(r"\b(?:post|share|send|put|drop)\s+(?:the\s+|an?\s+|our\s+)?([a-z][\w\s-]{2,40}?)\s+(?:in|to|on|into)\s+(?:the\s+)?(?:#?[\w-]+\s+)?(?:slack|channel|#)", text.lower())
    return m.group(1).strip() if m else None

def _recap_line(p: dict, names: dict) -> str | None:
    prm = p["parameters"]
    if p["app"] == "gmail":
        topic = p.get("_topic") or prm["subject"].lower()
        return f"{topic.capitalize()} emailed to {names.get(p['commitment_id']) or prm['recipient']}"
    if p["app"] == "calendar":
        return f"{prm['title']}, {_when(prm['time'])}"
    if p["app"] == "airtable":
        rec = names.get(p["commitment_id"])
        stage = prm["fields"].get("Stage")
        return f"{rec + ' deal' if rec else 'Deal'} moved to {stage}" if stage else None
    return None

def _slack_message(c: dict, plans: list[dict], names: dict, context: dict) -> str:
    topic = _slack_topic(c["text"])
    head = " · ".join(x for x in (context.get("meeting"), topic and topic.capitalize()) if x)
    lines = [ln for ln in (_recap_line(p, names) for p in plans
                           if p["type"] == "action" and p["app"] != "slack") if ln]
    if not lines:
        return f"{head}: {c['text'].rstrip('.')}." if head else c["text"]
    return "\n".join([f"*{head or 'Meeting update'}*", "Next steps:"] + [f"• {ln}" for ln in lines])

def _email_body(c: dict, prm: dict, first_name: str | None, plans: list[dict], context: dict) -> str:
    topic = _email_topic(c["text"], prm["subject"])
    meetings = [p["parameters"] for p in plans if p["type"] == "action" and p["app"] == "calendar"]
    out = [f"Hi {first_name}," if first_name else "Hi,", "",
           "Thanks for your time today. " + (f"As promised, following up on the {topic}."
                                              if topic else "As promised, following up on our call.")]
    # Only meetings go to the recipient; deal stages and internal posts stay internal.
    if meetings:
        out += ["", "Next steps:"] + [f"- {m['title']}, {_when(m['time'])}" for m in meetings]
    out += ["", "Best,", context.get("sender") or ""]
    return "\n".join(out).rstrip() + "\n"

def plan(commitments: list[dict], entities: list[dict], apps: dict,
         context: dict | None = None) -> list[dict]:
    """context (optional): {"meeting": note title, "sender": your name}; used only
    for wording, never for what is done or to whom."""
    context = context or {}
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
            params = {"title": _event_title(c["text"], context), "time": t}
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

    # Second pass: emails and Slack posts can mention what else the meeting agreed.
    by_c = {c["id"]: c for c in commitments}
    names = {}
    for e in entities:
        for r in e.get("resolutions", []):
            if r.get("id") and r["app"] in ("gmail", "airtable"):
                names[e["commitment_id"]] = r["name"]
    for p in plans:
        if p["type"] == "action" and p["app"] == "gmail":
            p["_topic"] = _email_topic(by_c[p["commitment_id"]]["text"], p["parameters"]["subject"])
    for p in plans:
        if p["type"] != "action":
            continue
        c, prm = by_c[p["commitment_id"]], p["parameters"]
        if p["app"] == "slack":
            prm["message"] = _slack_message(c, plans, names, context)
        elif p["app"] == "gmail":
            who = names.get(p["commitment_id"])
            prm["body"] = _email_body(c, prm, who.split()[0] if who else None, plans, context)
    for p in plans:
        p.pop("_topic", None)
    return plans
