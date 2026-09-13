"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const DEFAULT_ENGINE = "http://127.0.0.1:8765";
const APP_NAMES = { gmail: "Gmail", calendar: "Calendar", slack: "Slack", airtable: "Airtable" };
const STATUS_ICON = { applied: "✅", skipped_duplicate: "⏭", failed: "❌", planned: "📝",
                      skipped_not_allowed: "🚫", clarification_requested: "❓" };

const state = { engine: DEFAULT_ENGINE, status: null, settings: null };

function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) n.append(c instanceof Node ? c : String(c));
  return n;
}

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(state.engine + path, { cache: "no-store", ...opts });
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, kind = "info") {
  const t = $("#toast");
  t.textContent = msg; t.dataset.kind = kind; t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, kind === "error" ? 7000 : 3500);
}

function show(view) {
  $$(".view").forEach(v => { v.hidden = v.id !== `view-${view}`; });
  $("#gear").hidden = !(view === "home");
}

function setPill(text, tone) {
  const p = $("#pill");
  p.textContent = text; p.dataset.tone = tone || "";
}

const ago = iso => {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
};

/* ---------- boot ---------- */
async function refresh() {
  try {
    const stored = await chrome.storage.local.get("engineUrl");
    state.engine = (stored.engineUrl || DEFAULT_ENGINE).replace(/\/+$/, "");
    $("#engine-url").value = state.engine;
    state.status = await api("/api/status");
    state.settings = (await api("/api/settings")).settings;
  } catch (e) {
    setPill("Offline", "danger");
    show("offline");
    return;
  }
  if (!state.status.autopilot) {
    setPill("Website mode", "warn");
    toast("The engine is running as website only. Start it with: python run.py engine", "error");
  }
  if (!state.settings.onboarded) { setPill("Set up", "run"); show("onboard"); return; }
  renderHome();
  show("home");
  chrome.runtime.sendMessage({ type: "poll" }).catch(() => {});
}

/* ---------- onboarding ---------- */
let step = 1;
function goStep(n) {
  step = n;
  $$("#view-onboard .step").forEach(s => { s.hidden = Number(s.dataset.step) !== n; });
  $$("#view-onboard .progress span").forEach(s => s.classList.toggle("on", Number(s.dataset.step) <= n));
}
function bindOnboarding() {
  $$("#view-onboard .next").forEach(b => b.addEventListener("click", () => {
    if (step === 1) {
      const email = $("#ob-email").value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { toast("Enter a valid email address.", "error"); return; }
    }
    if (step === 2 && !$$('#view-onboard .step[data-step="2"] input:checked').length) {
      toast("Allow at least one app.", "error"); return;
    }
    goStep(step + 1);
  }));
  $$("#view-onboard .back").forEach(b => b.addEventListener("click", () => goStep(step - 1)));
  $("#ob-finish").addEventListener("click", async () => {
    const armed = $("#ob-armed").checked;
    if (armed && !confirm("Act for real?\n\nFollowthrough will send real emails, create events, post to Slack and update records for the commitments in your meetings. Ambiguous items are asked, never guessed.")) return;
    const patch = {
      onboarded: true,
      profile: { email: $("#ob-email").value.trim(), name: $("#ob-name").value.trim() },
      allowed_apps: $$('#view-onboard .step[data-step="2"] input:checked').map(i => i.value),
      autopilot: { enabled: true, armed },
    };
    try {
      state.settings = (await api("/api/settings", patch)).settings;
      state.status = await api("/api/status");
      toast(armed ? "Autopilot is on and armed." : "Autopilot is on (preview only).", "ok");
      renderHome(); show("home");
    } catch (e) { toast(e.message, "error"); }
  });
}

/* ---------- home ---------- */
function renderHome() {
  const s = state.settings, ap = state.status.autopilot;
  const enabled = s.autopilot.enabled, armed = s.armed_effective;
  const orb = $("#orb");
  orb.className = "orb " + (!ap ? "off" : !enabled ? "paused" : armed ? "" : "preview");
  $("#ap-title").textContent = !ap ? "Engine in website mode" : !enabled ? "Autopilot paused" : armed ? "Autopilot on" : "Autopilot on · preview only";
  $("#ap-sub").textContent = !ap ? "Restart with: python run.py engine"
    : !enabled ? "Meetings are not being processed"
    : ap.last_poll ? `Last check ${ago(ap.last_poll)} · every ${ap.poll_minutes} min` : `Checks every ${ap.poll_minutes} min`;
  $("#ap-toggle").checked = enabled;
  $("#ap-toggle").disabled = !ap;
  setPill(!ap ? "Website mode" : !enabled ? "Paused" : armed ? "Armed" : "Preview", !ap ? "warn" : !enabled ? "warn" : armed ? "danger" : "ok");
  $("#chips").replaceChildren(...Object.keys(APP_NAMES).map(a =>
    el("span", { class: `chip ${s.allowed_apps.includes(a) ? "on" : "off"}`, text: APP_NAMES[a] })));
  if (ap?.last_error) toast(`Engine: ${ap.last_error}`, "error");
  loadActivity();
}

async function loadActivity() {
  try {
    const { activity } = await api("/api/activity?limit=15");
    $("#activity-count").textContent = activity.length;
    $("#activity").replaceChildren(...(activity.length ? activity.map(entryCard)
      : [el("div", { class: "empty", text: state.settings.autopilot.enabled
          ? "No meetings yet. Finish a Granola meeting and check back in a few minutes."
          : "Autopilot is paused." })]));
  } catch (e) { toast(e.message, "error"); }
}

function entryCard(e) {
  const c = e.counts || {};
  let sum, tone;
  if (e.mode === "error") { sum = `Could not process: ${e.note}`; tone = "danger"; }
  else if (e.mode === "skipped_owner") { sum = "Skipped: not your meeting"; tone = ""; }
  else if (e.mode === "preview") { sum = `Preview: ${c.actions || 0} action(s) would run` + (c.questions ? ` · ${c.questions} need you` : ""); tone = "info"; }
  else {
    sum = `${c.done || 0} done` + (c.failed ? ` · ${c.failed} failed` : "") + (c.questions ? ` · ${c.questions} need you` : "") + (c.not_allowed ? ` · ${c.not_allowed} not allowed` : "");
    tone = c.failed ? "danger" : c.questions ? "warn" : "ok";
  }
  const items = (e.items || []).map(it => el("div", { class: "item" },
    el("span", { text: STATUS_ICON[it.status] || "•" }),
    el("span", { class: "app-tag", text: it.type === "action" ? APP_NAMES[it.app] || it.app : "ask" }),
    el("span", { class: "txt" },
      it.type === "action" ? it.text : el("em", { text: it.question || it.text }),
      it.error ? el("span", { class: "err", text: ` — ${it.error}` }) : null)));
  return el("article", { class: "entry" },
    el("header", {}, el("b", { text: e.title }), el("time", { text: ago(e.ts), title: e.ts })),
    el("div", { class: "sum", dataset: { tone }, text: sum }),
    items.length ? el("div", { class: "items" }, ...items) : null);
}

/* ---------- settings ---------- */
function openSettings() {
  const s = state.settings;
  $("#st-email").value = s.profile.email; $("#st-name").value = s.profile.name;
  $$("#st-apps input").forEach(i => { i.checked = s.allowed_apps.includes(i.value); });
  $("#st-armed").checked = s.autopilot.armed; $("#st-mine").checked = s.autopilot.only_my_meetings;
  $("#st-poll").value = s.autopilot.poll_minutes; $("#st-url").value = state.engine;
  show("settings");
}
async function saveSettings() {
  const armed = $("#st-armed").checked;
  if (armed && !state.settings.autopilot.armed && !confirm("Act for real from now on?\n\nReal emails, events, Slack posts and record updates will be sent for your meetings.")) return;
  const url = ($("#st-url").value.trim() || DEFAULT_ENGINE).replace(/\/+$/, "");
  await chrome.storage.local.set({ engineUrl: url });
  state.engine = url;
  try {
    state.settings = (await api("/api/settings", {
      profile: { email: $("#st-email").value.trim(), name: $("#st-name").value.trim() },
      allowed_apps: $$("#st-apps input:checked").map(i => i.value),
      autopilot: { armed, only_my_meetings: $("#st-mine").checked, poll_minutes: Number($("#st-poll").value) || 2 },
    })).settings;
    state.status = await api("/api/status");
    toast("Saved.", "ok"); renderHome(); show("home");
  } catch (e) { toast(e.message, "error"); }
}

/* ---------- wiring ---------- */
function init() {
  bindOnboarding();
  $("#retry").addEventListener("click", async () => {
    const url = ($("#engine-url").value.trim() || DEFAULT_ENGINE).replace(/\/+$/, "");
    await chrome.storage.local.set({ engineUrl: url });
    refresh();
  });
  $("#gear").addEventListener("click", openSettings);
  $("#st-cancel").addEventListener("click", () => show("home"));
  $("#st-save").addEventListener("click", saveSettings);
  $("#open-site").addEventListener("click", () => chrome.tabs.create({ url: state.engine }));
  $("#ap-toggle").addEventListener("change", async e => {
    try {
      state.settings = (await api("/api/settings", { autopilot: { enabled: e.target.checked } })).settings;
      state.status = await api("/api/status");
      toast(e.target.checked ? "Autopilot resumed." : "Autopilot paused.", "ok");
      renderHome();
    } catch (err) { toast(err.message, "error"); e.target.checked = !e.target.checked; }
  });
  $("#run-now").addEventListener("click", async () => {
    try { await api("/api/autopilot/run-now", {}); toast("Checking Granola now…", "ok"); setTimeout(loadActivity, 4000); }
    catch (e) { toast(e.message, "error"); }
  });
  refresh();
}
init();
