"use strict";

/* ---------- helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `Request failed (HTTP ${res.status})`);
  return data;
}

async function pollJob(id, onTick) {
  for (;;) {
    const job = await api(`/api/jobs/${id}`);
    onTick(job);
    if (job.status === "done" || job.status === "error") return job;
    await sleep(1000);
  }
}

function toast(message, kind = "info") {
  const box = $("#toast");
  box.textContent = message;
  box.dataset.kind = kind;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, kind === "error" ? 9000 : 5000);
}

const fmtDate = iso => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
};
const fmtTime = seconds => new Date(seconds * 1000)
  .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const APPS = {
  gmail: ["Gmail", "Send email"],
  calendar: ["Calendar", "Create event"],
  slack: ["Slack", "Post message"],
  airtable: ["Airtable", "Update record"],
};
const METHOD = { llm: "Groq", mixed: "Groq + rules", heuristic: "Rules only" };
const STATUS = { planned: "Planned", applied: "Done", failed: "Failed", skipped_duplicate: "Already done" };

const SAMPLE = `Alex: Hi Sam, thanks for joining. This is a quick sync on the Acme renewal.
Sam: Sure. I spoke with Daniel Cho yesterday. They're happy with the product and want pricing for next year.
Alex: Good. I'll send the pricing proposal to Daniel Cho.
Sam: Great. They also asked for a pricing review meeting.
Alex: Let's put Friday at 10am on the calendar for the pricing review.
Sam: Works for me. The deal has moved forward, so the pipeline is out of date.
Sam: I'll update the deal stage to Negotiation for the Acme record in Airtable.
Alex: Perfect. The rest of the team should know about this too.
Alex: Please post the renewal status in the Slack updates channel.
Sam: Will do. Maybe we could also share the case study with Priya next month, but there's no rush for now.
Alex: Agreed, not today. Just to confirm, I'll send the pricing proposal to Daniel Cho.
Sam: Sounds good. Thanks, talk soon.`;

const state = { status: null, notes: [], note: null, source: "notes", preview: null, previewJob: null, busy: false };

/* ---------- shared UI state ---------- */
function setBusy(busy) {
  state.busy = busy;
  updateAnalyze();
  syncExecute();
  $("#bench-run").disabled = busy;
}

function setPill(pill, text, tone) {
  pill.textContent = text;
  pill.dataset.tone = tone || "";
  pill.classList.toggle("ghost", !tone);
}

function logLine(entry, cls) {
  const kind = cls || (/warning|failed/i.test(entry.msg) ? "warn" : "");
  return el("li", { class: kind || null }, el("time", { text: fmtTime(entry.t) }), el("span", { text: entry.msg }));
}

function renderLog(list, log) {
  list.replaceChildren(...log.map(entry => logLine(entry)));
  list.scrollTop = list.scrollHeight;
}

/* ---------- tabs ---------- */
function showTab(name) {
  $$(".tabs [role=tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".tab-panel").forEach(p => { p.hidden = p.id !== `tab-${name}`; });
  try { localStorage.setItem("ft-tab", name); } catch { /* storage unavailable */ }
  if (name === "system" && !$("#connections").children.length) runChecks();
  if (name === "bench") loadHistory();
}

/* ---------- status ---------- */
async function loadStatus() {
  const s = await api("/api/status");
  state.status = s;
  const real = Boolean(s.armed);
  for (const pill of [$("#mode-pill"), $("#mode-pill-2")]) {
    setPill(pill, real ? "Armed · sends for real" : "Safe mode · preview only", real ? "danger" : "ok");
  }
  renderAutopilot(s.autopilot);
  setPill($("#model-pill"), s.groq_enabled ? `Groq · ${s.groq_model}` : "Groq off · rules", "");
  setPill($("#version-pill"), `Agent ${s.agent_version}`, "");
  syncExecute();
  return s;
}

/* ---------- source: Granola notes / pasted transcript ---------- */
async function loadNotes() {
  const list = $("#notes");
  list.replaceChildren(el("li", { class: "muted pad", text: "Loading Granola notes…" }));
  try {
    state.notes = (await api("/api/notes")).notes;
    renderNotes();
  } catch (e) {
    list.replaceChildren(el("li", { class: "error pad", text: e.message }));
  }
}

function renderNotes() {
  const query = $("#note-filter").value.trim().toLowerCase();
  const items = state.notes.filter(n => !query || n.title.toLowerCase().includes(query));
  const list = $("#notes");
  if (!items.length) {
    list.replaceChildren(el("li", {
      class: "muted pad",
      text: state.notes.length ? "No notes match." : "No finished notes yet. Granola lists a note once its AI summary is ready.",
    }));
    return;
  }
  list.replaceChildren(...items.map(n => {
    const on = state.note?.id === n.id;
    return el("li", {},
      el("button", {
        type: "button", class: `note${on ? " on" : ""}`, "aria-pressed": String(on),
        onclick: () => { state.note = n; renderNotes(); updateAnalyze(); },
      },
        el("span", { class: "note-title", text: n.title || "(untitled)" }),
        el("span", { class: "note-meta" }, el("span", { text: fmtDate(n.created_at) }), el("code", { text: n.id }))));
  }));
}

function setSource(source) {
  state.source = source;
  $$("[data-src]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.src === source)));
  $("#src-notes").hidden = source !== "notes";
  $("#src-paste").hidden = source !== "paste";
  updateAnalyze();
}

function updateAnalyze() {
  const ready = state.source === "notes" ? Boolean(state.note) : $("#paste-text").value.trim().length > 0;
  $("#analyze").disabled = !ready || state.busy;
}

/* ---------- preview (dry run) ---------- */
function showRunView(view) {
  $("#empty").hidden = view !== "empty";
  $("#progress").hidden = view !== "progress";
  $("#result").hidden = view !== "result";
}

function setRunStatus(status) {
  const map = { queued: ["Queued", "run"], running: ["Running", "run"], done: ["Complete", "ok"], error: ["Error", "danger"] };
  const [text, tone] = map[status] || ["Idle", ""];
  setPill($("#run-status"), text, tone);
}

async function analyze() {
  const body = state.source === "notes"
    ? { note_id: state.note.id, title: state.note.title }
    : { transcript: $("#paste-text").value, title: $("#paste-title").value.trim() || "Pasted transcript" };
  try {
    const { job } = await api("/api/preview", body);
    await watchPreview(job);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function watchPreview(job) {
  setBusy(true);
  state.preview = null;
  state.previewJob = job.id;
  $("#run-title").textContent = job.label;
  showRunView("progress");
  const log = $("#log");
  log.classList.add("live");
  try {
    const final = await pollJob(job.id, j => { renderLog(log, j.log); setRunStatus(j.status); });
    log.classList.remove("live");
    if (final.status === "error") {
      log.append(logLine({ t: final.finished || Date.now() / 1000, msg: final.error }, "err"));
      toast(final.error, "error");
      return;
    }
    state.preview = final.result;
    renderPreview(final.result, final.log);
  } catch (e) {
    setRunStatus("error");
    toast(e.message, "error");
  } finally {
    log.classList.remove("live");
    setBusy(false);
  }
}

function paramRows(p) {
  const x = p.parameters || {};
  const rows = {
    gmail: [["To", x.recipient], ["Subject", x.subject]],
    calendar: [["Title", x.title], ["When", x.time]],
    slack: [["Channel", x.channel], ["Mention", x.mention], ["Message", x.message]],
    airtable: [["Record", x.record_id], ["Set", Object.entries(x.fields || {}).map(([k, v]) => `${k} → ${v}`).join(", ")]],
  }[p.app] || Object.entries(x).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : v]);
  return rows
    .filter(([, value]) => value != null && value !== "")
    .flatMap(([label, value]) => [el("dt", { text: label }), el("dd", { text: String(value) })]);
}

function actionCard(p) {
  const [app, verb] = APPS[p.app] || [p.app, p.action];
  return el("article", { class: "card action", dataset: { app: p.app, id: p.commitment_id } },
    el("header", {},
      el("label", { class: "pick-wrap" },
        el("input", { type: "checkbox", class: "pick", checked: true, "aria-label": `Include ${verb}`, dataset: { id: p.commitment_id }, onchange: syncExecute }),
        el("span", { class: "app-badge", text: app }),
        el("strong", { text: verb })),
      el("span", { class: "badge", dataset: { status: "planned" }, text: STATUS.planned })),
    el("dl", { class: "params" }, ...paramRows(p)),
    p.commitment_text ? el("blockquote", { text: p.commitment_text }) : null,
    el("p", { class: "card-error", hidden: true }));
}

function questionCard(p) {
  return el("article", { class: "card question" },
    el("header", {}, el("span", { class: "app-badge", text: "Clarify" }), el("strong", { text: "Needs your input" })),
    p.commitment_text ? el("blockquote", { text: p.commitment_text }) : null,
    el("p", { class: "question-text", text: p.question }));
}

function renderPreview(result, log) {
  showRunView("result");
  const actions = result.plans.filter(p => p.type === "action");
  const questions = result.plans.filter(p => p.type !== "action");
  $("#stat-commitments").textContent = result.counts.commitments;
  $("#stat-actions").textContent = result.counts.actions;
  $("#stat-questions").textContent = result.counts.questions;
  $("#stat-method").textContent = METHOD[result.extraction.method] || result.extraction.method;
  $("#warnings").replaceChildren(...(result.extraction.warnings || []).map(w => el("div", { class: "warning", text: w })));
  $("#actions-count").textContent = actions.length;
  $("#questions-count").textContent = questions.length;
  $("#actions").replaceChildren(...(actions.length ? actions.map(actionCard)
    : [el("p", { class: "muted", text: "No actions planned: nothing in this call maps to an email, event, Slack post or Airtable update." })]));
  $("#questions").replaceChildren(...(questions.length ? questions.map(questionCard)
    : [el("p", { class: "muted", text: "Nothing needs clarifying." })]));
  renderLog($("#result-log"), log);
  $("#trace").textContent = result.trace;
  $(".exec-bar").hidden = !actions.length;
  syncExecute();
}

/* ---------- execute ---------- */
function selectedIds() {
  return $$("#actions .pick").filter(b => b.checked && !b.disabled).map(b => b.dataset.id);
}

function syncExecute() {
  const picks = $$("#actions .pick");
  const open = picks.filter(b => !b.disabled);
  const chosen = selectedIds();
  const armed = Boolean(state.status?.armed);
  const all = $("#select-all");
  all.disabled = !open.length;
  all.checked = open.length > 0 && chosen.length === open.length;
  const button = $("#execute");
  button.disabled = !armed || !chosen.length || state.busy;
  button.textContent = `Execute ${chosen.length} action${chosen.length === 1 ? "" : "s"}`;
  const note = $("#exec-note");
  note.textContent = armed
    ? "Real mode: this sends real emails, events, Slack posts and Airtable edits."
    : "Locked in safe mode. Arm autopilot in the Followthrough extension (or set FOLLOWTHROUGH_MODE=real in .env and restart).";
  note.dataset.tone = armed ? "danger" : "";
}

async function confirmExecute() {
  const ids = [...new Set(selectedIds())];
  if (!ids.length) return;
  const dialog = $("#confirm");
  $("#confirm-count").textContent = ids.length;
  dialog.returnValue = "";
  dialog.showModal();
  const go = await new Promise(resolve =>
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "go"), { once: true }));
  if (!go) return;

  setBusy(true);
  try {
    const { job } = await api("/api/execute", { preview_job_id: state.previewJob, action_ids: ids });
    const log = $("#result-log");
    log.closest("details").open = true;
    const final = await pollJob(job.id, j => { renderLog(log, j.log); setRunStatus(j.status); });
    if (final.status === "error") throw new Error(final.error);
    applyResults(final.result.results);
    const failed = final.result.results.filter(r => r.status === "failed").length;
    toast(failed ? `${failed} action(s) failed. See the red cards.` : "All selected actions are done.", failed ? "error" : "ok");
  } catch (e) {
    setRunStatus("error");
    toast(e.message, "error");
  } finally {
    setBusy(false);
  }
}

function applyResults(results) {
  const used = new Set();
  for (const r of results.filter(x => x.type === "action")) {
    const card = $$("#actions .card").find(c => c.dataset.id === r.commitment_id && !used.has(c));
    if (!card) continue;
    used.add(card);
    const badge = $(".badge", card);
    badge.dataset.status = r.status;
    badge.textContent = STATUS[r.status] || r.status;
    const error = $(".card-error", card);
    const message = r.error
      ? r.error + (r.outcome_unknown ? " (outcome unknown: check the app before retrying)" : "")
      : "";
    error.textContent = message;
    error.hidden = !message;
    if (r.status === "applied" || r.status === "skipped_duplicate") {
      const pick = $(".pick", card);
      pick.checked = false;
      pick.disabled = true;
    }
  }
  syncExecute();
}

/* ---------- benchmark ---------- */
async function runBench() {
  try {
    const { job } = await api("/api/suite", { llm: $("#bench-llm").checked, faults: $("#bench-faults").checked });
    await watchBench(job);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function watchBench(job) {
  setBusy(true);
  $("#bench-empty").hidden = true;
  $("#bench-out").hidden = false;
  $("#board").replaceChildren();
  $("#bench-summary").textContent = `${job.label}: running…`;
  const log = $("#bench-log");
  log.classList.add("live");
  try {
    const final = await pollJob(job.id, j => renderLog(log, j.log));
    if (final.status === "error") throw new Error(final.error);
    renderBoard(final.result);
    loadHistory();
  } catch (e) {
    $("#bench-summary").textContent = e.message;
    toast(e.message, "error");
  } finally {
    log.classList.remove("live");
    setBusy(false);
  }
}

function meter(value) {
  return el("span", { class: "meter", style: `--v:${value}`, title: value.toFixed(3) }, el("span", { text: value.toFixed(2) }));
}

function renderBoard(agg) {
  $("#bench-summary").replaceChildren(
    el("span", { class: "big", text: `${agg.passed}/${agg.fixtures}` }),
    ` passed · pass rate ${agg.pass_rate}% · mean score ${agg.mean_score} · ${agg.fault_injection ? "fault-injected" : "clean"}`);
  $("#board").replaceChildren(...agg.results.map(r => el("tr", {},
    el("td", {}, el("code", { text: r.fixture_id })),
    el("td", {}, el("span", { class: "verdict", dataset: { v: r.verdict }, text: r.verdict })),
    el("td", { class: "num", text: r.overall_score }),
    ...["commitment_f1", "entity_accuracy", "action_accuracy"].map(k => el("td", { class: "num" }, meter(r.components[k]))),
    el("td", { class: "num", text: r.components.safety ? "✓" : "✗" }),
    el("td", { class: "notes-cell" },
      ...r.hard_failures.map(h => el("div", { class: "hard", text: h })),
      ...r.explanations.map(x => el("div", { class: "muted", text: x }))))));
}

async function loadHistory() {
  try {
    const { history } = await api("/api/history");
    $("#history").replaceChildren(...(history.length ? history.map(h => el("tr", {},
      el("td", { text: h.ts }),
      el("td", { text: h.agent_version }),
      el("td", { text: h.fault_injection ? "faults" : "clean" }),
      el("td", { class: "num", text: `${h.pass_rate}%` }),
      el("td", { class: "num", text: h.mean_score })))
      : [el("tr", {}, el("td", { colspan: "5", class: "muted", text: "No runs yet." }))]));
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- system: autopilot card ---------- */
function renderAutopilot(ap) {
  const box = $("#autopilot");
  if (!box) return;
  if (!ap) {
    box.replaceChildren(el("p", { class: "muted", text: "Autopilot is off in website mode. Start the engine with: python run.py engine, then set it up in the Followthrough browser extension." }));
    return;
  }
  const rows = [
    ["State", !ap.enabled ? "Paused" : ap.armed ? "On · sends for real" : "On · preview only"],
    ["Allowed apps", ap.allowed_apps.join(", ") || "none"],
    ["Checks Granola", `every ${ap.poll_minutes} min` + (ap.last_poll ? ` · last ${fmtDate(ap.last_poll)}` : "")],
    ["Meetings processed", String(ap.processed)],
  ];
  if (ap.last_error) rows.push(["Last error", ap.last_error]);
  box.replaceChildren(el("dl", { class: "params" }, ...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])));
  api("/api/activity?limit=8").then(({ activity }) => {
    if (!activity.length) return;
    box.append(el("div", { class: "cards", style: "margin-top:14px" }, ...activity.map(e => {
      const c = e.counts || {};
      const sum = e.mode === "error" ? `Error: ${e.note}` : e.mode === "skipped_owner" ? "Skipped: not your meeting"
        : e.mode === "preview" ? `Preview: ${c.actions || 0} action(s)` : `${c.done || 0} done · ${c.failed || 0} failed`;
      return el("article", { class: "card" + (e.mode === "error" ? " question" : "") },
        el("header", {}, el("strong", { text: e.title }), el("span", { class: "badge", text: fmtDate(e.ts) })),
        el("p", { class: "muted", style: "margin:6px 0 0", text: sum + (c.questions ? ` · ${c.questions} need you` : "") }));
    })));
  }).catch(() => {});
}

/* ---------- system ---------- */
async function runChecks() {
  const grid = $("#connections");
  const button = $("#check-run");
  button.disabled = true;
  grid.replaceChildren(...["Groq", "Granola", "Slack", "Airtable", "Google"].map(name =>
    el("article", { class: "conn", dataset: { state: "pending" } },
      el("header", {}, el("span", { class: "dot" }), el("strong", { text: name })),
      el("p", { text: "Checking…" }))));
  try {
    const { connections } = await api("/api/check");
    grid.replaceChildren(...connections.map(c =>
      el("article", { class: "conn", dataset: { state: c.ok ? "ok" : "fail" } },
        el("header", {},
          el("span", { class: "dot" }),
          el("strong", { text: c.name }),
          el("span", { class: "badge", dataset: { status: c.ok ? "applied" : "failed" }, text: c.ok ? "Online" : "Error" })),
        el("p", { text: c.detail }))));
  } catch (e) {
    grid.replaceChildren();
    toast(e.message, "error");
  } finally {
    button.disabled = false;
  }
}

/* ---------- boot ---------- */
function resume(job) {
  if (job.kind === "preview") { showTab("live"); watchPreview(job); }
  else if (job.kind === "suite") { showTab("bench"); watchBench(job); }
  else toast("Actions are being executed in the background. Refresh in a moment.", "info");
}

async function init() {
  $$(".tabs [role=tab]").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $$("[data-src]").forEach(b => b.addEventListener("click", () => setSource(b.dataset.src)));
  $("#note-filter").addEventListener("input", renderNotes);
  $("#notes-refresh").addEventListener("click", loadNotes);
  $("#paste-text").addEventListener("input", updateAnalyze);
  $("#load-sample").addEventListener("click", () => {
    $("#paste-title").value = "Acme renewal sync (demo)";
    $("#paste-text").value = SAMPLE;
    updateAnalyze();
  });
  $("#analyze").addEventListener("click", analyze);
  $("#select-all").addEventListener("change", e => {
    $$("#actions .pick").forEach(b => { if (!b.disabled) b.checked = e.target.checked; });
    syncExecute();
  });
  $("#execute").addEventListener("click", confirmExecute);
  $("#bench-run").addEventListener("click", runBench);
  $("#check-run").addEventListener("click", runChecks);

  let tab = "live";
  try { tab = localStorage.getItem("ft-tab") || "live"; } catch { /* storage unavailable */ }
  showTab(["live", "bench", "system"].includes(tab) ? tab : "live");

  try {
    const status = await loadStatus();
    if (status.active_job) resume(status.active_job);
  } catch (e) {
    setPill($("#mode-pill"), "Server offline", "danger");
    toast(`Can't reach the Followthrough server: ${e.message}`, "error");
  }
  loadNotes();
}

init();
