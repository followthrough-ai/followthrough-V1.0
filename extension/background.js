"use strict";
// Followthrough background worker: checks the local engine every minute, shows a
// notification when autopilot finishes a meeting, and keeps the badge up to date.

const DEFAULT_ENGINE = "http://127.0.0.1:8765";
const ALARM = "followthrough-poll";

async function engineUrl() {
  const { engineUrl } = await chrome.storage.local.get("engineUrl");
  return (engineUrl || DEFAULT_ENGINE).replace(/\/+$/, "");
}

async function getJson(path) {
  const res = await fetch((await engineUrl()) + path, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  if (color) chrome.action.setBadgeBackgroundColor({ color });
}

function summary(entry) {
  const c = entry.counts || {};
  if (entry.mode === "error") return `Could not process: ${entry.note || "unknown error"}`;
  if (entry.mode === "skipped_owner") return "Skipped: not your meeting";
  const parts = [];
  if (entry.mode === "preview") parts.push(`${c.actions || 0} action(s) previewed (engine not armed)`);
  else parts.push(`${c.done || 0} done`, `${c.failed || 0} failed`);
  if (c.questions) parts.push(`${c.questions} need you`);
  if (c.not_allowed) parts.push(`${c.not_allowed} skipped (app not allowed)`);
  return parts.join(" · ");
}

async function poll() {
  try {
    const status = await getJson("/api/status");
    const ap = status.autopilot;
    await chrome.storage.local.set({ engineOnline: true, lastStatus: status, lastSeenAt: Date.now() });
    if (!ap || !ap.enabled) { setBadge(ap ? "" : "!", "#ffc75e"); return; }

    const { lastActivityId } = await chrome.storage.local.get("lastActivityId");
    const { activity } = await getJson(`/api/activity?limit=20${lastActivityId ? "&since=" + encodeURIComponent(lastActivityId) : ""}`);
    if (activity.length) {
      // Newest first; notify each new entry once (skip on first ever poll).
      if (lastActivityId) {
        for (const entry of activity.slice(0, 3).reverse()) {
          chrome.notifications.create(`ft-${entry.id}`, {
            type: "basic",
            iconUrl: "icons/icon128.png",
            title: `Followthrough · ${entry.title}`,
            message: summary(entry),
            priority: 1,
          });
        }
      }
      await chrome.storage.local.set({ lastActivityId: activity[0].id });
    }
    const questions = ap.pending_questions || 0;
    setBadge(questions ? String(questions) : "", "#9f7dff");
  } catch {
    await chrome.storage.local.set({ engineOnline: false });
    setBadge("off", "#ff5d7d");
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  poll();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  poll();
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) poll(); });
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === "poll") { poll().then(() => reply({ ok: true })); return true; }
  return false;
});
chrome.notifications.onClicked.addListener(async () => {
  chrome.tabs.create({ url: await engineUrl() });
});
