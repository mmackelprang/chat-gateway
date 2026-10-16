// chat-gateway admin console (CG-90). No framework, no browser storage: the
// admin key lives in `adminKey` for the life of this tab only (in open mode, no
// key is held at all: the page probes first and never asks). Every piece of
// data is rendered through textContent, never parsed as markup, so registry
// content cannot become HTML.
"use strict";

let adminKey = "";
let state = null;
let revealData = null; // the one minted key, in memory only; gone when the route leaves #/reveal
let filterText = ""; // the board filter (Task 7 reads it)
const SEVERITIES = ["alert", "warning", "info"];
const ID_PATTERN = "[a-z0-9][a-z0-9\\-]{0,62}"; // `-` escaped: valid under the v-flag pattern compiler
const TERMINAL = ["delivered", "failed", "unroutable", "expired"];
const RULE_6 = "Hard rule #6: inbound crosses to a consumer only by that consumer's explicit registry opt-in.";
// A LINK only: the page never loads an image from GitHub (CSP img-src 'self').
const AVATAR_GALLERY = "https://github.com/mmackelprang/chat-gateway/tree/main/assets/avatars";
const AVATAR_PNG_PATTERN = "https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png/<name>.png";
const REFUSED_INTRO = "The server refused this save until you confirm:";
const FILE_EDIT ="Grants of an inbound_locked app are a registry file edit, not a console action.";

function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else if (k === "text") n.textContent = v;
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  n.append(...toNodes(children));
  return n;
}
// The ONE place children become nodes: conditional children (`cond ? x : null`)
// are skipped, never stringified into a literal "null", and strings become
// text nodes. Every append/replaceChildren goes through this.
function toNodes(children) {
  const out = [];
  for (const c of children.flat(Infinity)) if (c != null) out.push(c instanceof Node ? c : document.createTextNode(String(c)));
  return out;
}
const $ = (id) => document.getElementById(id);
// Kept as the one-line spelling every existing caller uses; an empty message
// shows nothing (notices dismiss themselves or are dismissed by hand).
function toast(msg, isError) { if (msg) notify(msg, { kind: isError ? "alert" : "status" }); }
function view(...nodes) { $("view").replaceChildren(...toNodes(nodes)); }

// FastAPI's `detail` is a string for an HTTPException and a list of
// {loc, msg, type} for a validation 422. Under /admin the 422 list carries no
// `input`/`ctx` and a redacted `loc`, so only the messages are worth showing.
function detailText(data, status) {
  const d = data && data.detail;
  if (typeof d === "string" && d) return d;
  if (Array.isArray(d) && d.length) return d.map((x) => (x && typeof x.msg === "string") ? x.msg : "invalid request").join("; ");
  return "HTTP " + status;
}

async function api(method, path, body, key) {
  const headers = {};
  const k = key || adminKey;
  if (k) headers.Authorization = "Bearer " + k;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (!r.ok) {
    const err = new Error(detailText(data, r.status));
    err.status = r.status;
    // Task 2: refusal bodies carry a category (which recovery applies) and
    // sometimes reasons (the 428 dialog's bullets).
    err.category = data && data.category;
    err.reasons = data && data.reasons;
    throw err;
  }
  return data;
}

// One place that turns an API error into words for the operator. The category
// (a fixed authored phrase from the server) picks the recovery first; the
// status is the fallback when the body carried none.
function explain(e) {
  switch (e.category) {
    case "refused: edited outside the console":
      return e.message + " — registry.yaml was edited outside the console. Use Registry › Reload from disk, then try again.";
    case "refused: unpolled inbound": return e.message + " — poll or drain its inbox first.";
    case "refused: env name in use": return e.message + " — pick another id; the variable name is derived from it.";
    case "refused: still granted": return e.message + " — remove the grant from each holder first.";
    case "refused: secret in process env": return e.message + " — that value is set in the process environment; change it there.";
    default: break;
  }
  switch (e.status) {
    case 403: return "Not a console action — " + e.message;
    case 409: return e.message + " — the registry changed or conflicts. Use Registry › Refresh view, or Reload from disk if registry.yaml was edited by hand.";
    case 428: return "Typed confirmation needed — " + e.message;
    case 401: return "Signed out: the admin key was refused.";
    default: return e.message;
  }
}
function fail(e) {
  if (e && e.message === "cancelled") { toast("Cancelled."); return; }
  if (e && e.status === 401) { signOut("The admin key was refused — sign in again."); return; }
  toast(explain(e), true);
}
function signOut(msg) {
  adminKey = ""; state = null;
  $("console").hidden = true; $("login").hidden = false;
  revealData = null; setDirty(false);
  $("sha").textContent = ""; $("counts").textContent = "";
  $("auth-mode").hidden = true;
  view();
  $("login-error").textContent = msg || "";
}

async function refresh() {
  state = await api("GET", "/admin/api/state");
  $("sha").textContent = "registry " + state.registry_sha256.slice(0, 12);
  const rooms = Object.keys(state.rooms || {}).filter((k) => k).length; // "" = identities with no room
  $("counts").textContent = Object.keys(state.apps).length + " apps · " + Object.keys(state.identities).length + " identities · " + rooms + " rooms";
  const b = $("banner");
  if (state.shadowed_env_names.length) {
    b.hidden = false;
    b.textContent = "Stale secrets in the read-only .env (old values that would revive if managed.env is lost): "
      + state.shadowed_env_names.join(", ") + ". Remove those lines from .env by hand.";
  } else b.hidden = true;
}

// Mutating call: carries the sha the page last saw, so a second tab gets 409.
// Keys whose value is `undefined` are dropped by JSON.stringify — that is how
// "not edited" reaches the server as "absent = unchanged".
//
// Once the mutation has succeeded, NOTHING after it may throw: create and
// rotate return a freshly minted key the server has already committed (for a
// rotation the old key is already dead), so a failed follow-up refresh must not
// stop the caller from reaching reveal(). The refresh failure is surfaced on
// the banner instead.
async function write(method, path, body) {
  const out = await api(method, path, Object.assign({ registry_sha256: state.registry_sha256 }, body || {}));
  try { await refresh(); }
  catch (e) {
    const b = $("banner");
    b.hidden = false;
    b.textContent = "The change was saved, but reloading the page's view failed (" + e.message
      + "). The page may be stale — use Registry › Refresh view before the next change.";
  }
  return out;
}

// Identity name -> the inbound_locked app holding it. Such an identity defines
// a locked space: its webhook cannot be replaced from the console (403).
function lockedHolders() {
  const out = new Map();
  for (const [id, a] of Object.entries(state.apps)) {
    if (!a.inbound_locked) continue;
    for (const n of a.identities) if (!out.has(n)) out.set(n, id);
  }
  return out;
}

// --------------------------------------------------------------- board ---
function board() {
  const held = lockedHolders();
  const appRows = Object.entries(state.apps).map(([id, a]) => el("tr", {},
    el("td", {}, el("strong", { text: id })),
    el("td", { text: a.identities.join(", ") || "—" }),
    el("td", { text: Object.entries(a.routes).map(([s, i]) => s + "→" + i).join(", ") || "—" }),
    el("td", {}, el("span", { class: "pill", text: a.allow_inbound ? "inbound on" : "inbound off" }),
      a.inbound_locked ? el("span", { class: "pill warn", text: "locked" }) : null),
    el("td", { class: a.key_configured ? "ok" : "error", text: (a.key_configured ? "key set" : "key missing") + " (" + a.key_source + ")" }),
    el("td", { text: a.recent_deliveries.length ? a.recent_deliveries[a.recent_deliveries.length - 1].status : "—" }),
    el("td", {}, el("button", { type: "button", text: "Manage", on: { click: () => navigate(hrefFor("app", id)) } }))));
  const idRows = Object.entries(state.identities).map(([name, i]) => {
    const locker = held.get(name);
    let webhookAction = null;
    if (i.mode === "webhook") {
      webhookAction = locker
        ? el("p", { class: "note", text: "Webhook held by locked app " + locker + " — replacing it is a registry file edit." })
        : el("button", { type: "button", text: "Replace webhook", on: { click: () => navigate(hrefFor("replace", name)) } });
    }
    return el("tr", {},
      el("td", {}, el("strong", { text: name })),
      el("td", { text: i.display }),
      el("td", { text: i.space || "—" }),
      el("td", { class: i.env_resolved ? "ok" : "error", text: i.env_resolved ? "ready" : "not resolvable" }),
      el("td", { text: i.secret_source || "—" }),
      el("td", {},
        webhookAction,
        el("button", { type: "button", text: "Rename display", on: { click: () => renameIdentity(name, i.display) } }),
        el("button", { type: "button", class: "danger", text: "Delete", on: { click: () => deleteIdentity(name) } })));
  });
  const defaulted = state.inbound_defaulted || [];
  view(
    el("h2", { text: "Apps" }),
    defaulted.length ? el("p", { class: "warn", text: "allow_inbound was left to the loader's default (off) for: " + defaulted.join(", ") + ". Saving the app here writes it explicitly." }) : null,
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["App", "Identities", "Routes", "Inbound", "API key", "Last delivery", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, appRows))),
    el("h2", { text: "Identities" }),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["Identity", "Display", "Space", "Webhook", "Secret source", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, idRows))));
}

// ------------------------------------------------------------ app form ---
// A field the state never shows (callback_url, unreachable_message): blank
// input = unchanged, typed value = set, "remove" box = "" (delete the key).
function optionalField(name, label, isSet, locked) {
  const input = el("input", { name, autocomplete: "off", disabled: locked,
    placeholder: isSet ? "(set — not shown; type a new value to replace it)" : "(not set)" });
  const parts = [el("label", {}, label, input)];
  if (isSet) {
    const box = el("input", { type: "checkbox", name: name + "-remove" });
    box.addEventListener("change", () => { input.disabled = box.checked || locked; if (box.checked) input.value = ""; });
    parts.push(el("label", {}, box, " remove " + name));
  }
  return parts;
}

function appFields(a) {
  const locked = !!a.inbound_locked;
  const ids = Object.keys(state.identities);
  const idBoxes = ids.map((n) => el("label", {},
    el("input", { type: "checkbox", name: "identity", value: n, checked: a.identities.includes(n), disabled: locked }), " " + n));
  const routeSel = (sev) => el("label", {}, sev === "default" ? "default (every severity without its own route)" : sev,
    el("select", { name: "route-" + sev }, el("option", { value: "", text: sev === "default" ? "— none —" : "(use default)" }),
      ids.map((n) => el("option", { value: n, text: n, selected: (a.routes[sev] || "") === n }))));
  return el("div", {},
    el("fieldset", {}, el("legend", { text: "Identities this app may send as" }),
      locked ? el("p", { class: "warn", text: "This app is inbound_locked. " + FILE_EDIT }) : null,
      idBoxes),
    el("fieldset", {}, el("legend", { text: "Notify routes" }),
      el("p", { class: "warn", text: "Severity picks the SPACE, not just the loudness (CG-86): split routes put an all-clear in a different room from the alert it closes." }),
      routeSel("default"), SEVERITIES.map(routeSel)),
    el("fieldset", {}, el("legend", { text: "Inbound" }),
      locked ? el("p", { class: "warn", text: "This app is inbound_locked. Inbound can only be narrowed here; widening is a registry file edit." }) : null,
      el("label", {}, el("input", { type: "checkbox", name: "allow_inbound", checked: a.allow_inbound, disabled: locked && !a.allow_inbound }), " allow_inbound"),
      optionalField("callback_url", "callback_url (push delivery; none = poll only)", !!a.callback_url_set, locked),
      el("label", {}, "allowed_users (one email per line; empty = anyone in the space)", el("textarea", { name: "allowed_users", rows: "3" }, (a.allowed_users || []).join("\n"))),
      optionalField("unreachable_message", "unreachable_message", !!a.unreachable_message_set, false)));
}

function readOptional(form, name) {
  const box = form.querySelector("[name=" + name + "-remove]");
  if (box && box.checked) return "";
  const v = form.querySelector("[name=" + name + "]").value.trim();
  return v ? v : undefined; // untouched blank: omitted, so the server keeps it
}

function readAppFields(form, a) {
  const routes = {};
  for (const sev of ["default", ...SEVERITIES]) { const v = form.querySelector("[name=route-" + sev + "]").value; if (v) routes[sev] = v; }
  // A locked app's identities are compared as an ORDERED list: send them back
  // exactly. Otherwise keep the existing order for what is still checked and
  // append new grants, so an unchanged grant set is never a reorder.
  let identities;
  if (a.inbound_locked) identities = a.identities.slice();
  else {
    const checked = new Set([...form.querySelectorAll("[name=identity]:checked")].map((x) => x.value));
    identities = a.identities.filter((n) => checked.has(n));
    for (const n of Object.keys(state.identities)) if (checked.has(n) && !identities.includes(n)) identities.push(n);
  }
  return {
    identities,
    routes,
    allow_inbound: form.querySelector("[name=allow_inbound]").checked,
    callback_url: readOptional(form, "callback_url"),
    allowed_users: form.querySelector("[name=allowed_users]").value.split("\n").map((s) => s.trim()).filter(Boolean),
    unreachable_message: readOptional(form, "unreachable_message"),
  };
}

// A 428 from the server means "this widens inbound": show rule #6 and ask for the typed id.
async function withInboundConfirm(appId, send) {
  try { return await send(""); }
  catch (e) {
    if (e.status !== 428) throw e;
    // The server's 428 detail already quotes rule #6; add it only if it does not.
    const msg = /hard rule #6/i.test(e.message) ? e.message : e.message + "\n\n" + RULE_6;
    const has = !!(e.reasons && e.reasons.length); // bullets cover the detail; do not print both
    const typed = await typedConfirm({ title: "Confirm: widen inbound for " + appId,
      intro: has ? REFUSED_INTRO : msg, reasons: e.reasons,
      note: has && !/hard rule #6/i.test(e.message) ? RULE_6 : null, expected: appId, verb: "Widen inbound", tone: "warn" });
    if (typed === null) throw new Error("cancelled");
    return await send(typed);
  }
}

// ------------------------------------------------------------- dialog ---
// Resolves with the dialog's returnValue once it closes, then hands focus back
// to whatever opened it. Escape closes natively with returnValue "" (= cancel).
function dialogClosed(dlg, trigger) {
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => {
      resolve(dlg.returnValue);
      if (trigger && trigger.isConnected && trigger.focus) trigger.focus();
    }, { once: true });
  });
}

// Typed confirmation: the verb button stays disabled until the text equals
// `expected`, so a mismatch cannot be submitted. Resolves the typed text, or
// null on Cancel/Escape.
function typedConfirm({ title, intro, reasons, note, expected, verb, tone }) {
  const dlg = $("confirm");
  if (dlg.open) dlg.close();
  const trigger = document.activeElement;
  const input = el("input", { id: "confirm-input", autocomplete: "off", "aria-label": "Type " + expected + " to confirm" });
  const verbBtn = el("button", { type: "button", class: tone === "danger" ? "danger" : "primary", text: verb, disabled: true });
  const cancelBtn = el("button", { type: "button", text: "Cancel" });
  const sync = () => { verbBtn.disabled = input.value !== expected; };
  input.addEventListener("input", sync);
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); if (!verbBtn.disabled) dlg.close("ok"); } });
  verbBtn.addEventListener("click", () => { if (!verbBtn.disabled) dlg.close("ok"); });
  cancelBtn.addEventListener("click", () => dlg.close(""));
  dlg.setAttribute("data-tone", tone || "warn");
  dlg.returnValue = "";
  dlg.replaceChildren(...toNodes([
    el("h2", { id: "confirm-title", text: title }),
    intro ? el("p", { text: intro }) : null,
    reasons && reasons.length ? el("ul", {}, reasons.map((r) => el("li", { text: r }))) : null,
    note ? el("p", { class: "muted", text: note }) : null,
    el("label", {}, "Type ", el("strong", { text: expected }), " to confirm", input),
    el("p", {}, verbBtn, " ", cancelBtn)]));
  const closed = dialogClosed(dlg, trigger);
  dlg.showModal();
  input.focus();
  return closed.then((v) => (v === "ok" ? input.value : null));
}

// One-shot "Discard …?" dialog for the unsaved new-app draft and a dirty
// inspector. Escape keeps editing. Resolves true only on Discard.
function discardConfirm(what) {
  const dlg = $("confirm");
  if (dlg.open) dlg.close();
  const trigger = document.activeElement;
  const keep = el("button", { type: "button", class: "primary", text: "Keep editing" });
  const discard = el("button", { type: "button", class: "danger", text: "Discard" });
  keep.addEventListener("click", () => dlg.close(""));
  discard.addEventListener("click", () => dlg.close("discard"));
  dlg.setAttribute("data-tone", "warn");
  dlg.returnValue = "";
  dlg.replaceChildren(...toNodes([
    el("h2", { id: "confirm-title", text: "Discard " + what + "?" }),
    el("p", { class: "muted", text: "Escape keeps editing." }),
    el("p", {}, discard, " ", keep)]));
  const closed = dialogClosed(dlg, trigger);
  dlg.showModal();
  keep.focus();
  return closed.then((v) => v === "discard");
}

function shortcutsDialog() {
  const dlg = $("shortcuts");
  if (dlg.open) return;
  const trigger = document.activeElement;
  const close = el("button", { type: "button", class: "primary", text: "Close" });
  close.addEventListener("click", () => dlg.close(""));
  const row = (k, t) => el("li", {}, el("kbd", { text: k }), " " + t);
  dlg.replaceChildren(...toNodes([
    el("h2", { id: "shortcuts-title", text: "Keyboard shortcuts" }),
    el("ul", {}, row("/", "filter apps and identities"), row("Escape", "back to the board; cancels a dialog"), row("?", "this list")),
    el("p", { class: "muted", text: "Nothing here writes: there are no single-letter verbs." }),
    el("p", {}, close)]));
  dialogClosed(dlg, trigger);
  dlg.showModal();
  close.focus();
}

function appInspector(appId) {
  const a = state.apps[appId];
  const form = el("form", {}, appFields(a), el("button", { type: "submit", class: "primary", text: "Save" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await withInboundConfirm(appId, (c) => write("PUT", "/admin/api/apps/" + encodeURIComponent(appId), Object.assign(readAppFields(form, a), { confirm_app_id: c })));
      toast("Saved " + appId + ". Live now.");
      setDirty(false); navigate(hrefFor("board"));
    } catch (e) { fail(e); }
  });
  view(el("h2", { text: "App " + appId }),
    el("p", { class: "muted", text: "API key env var: " + a.key_env + " (" + a.key_source + ")" }),
    form,
    el("div", { class: "card" },
      el("h3", { text: "Rotate API key" }),
      el("p", { text: "The current key stops working the moment you confirm. Update the consuming app right after." }),
      el("button", { type: "button", text: "Rotate key", on: { click: async () => {
        const typed = await typedConfirm({ title: "Rotate the API key for " + appId + "?", intro: "The old key dies immediately. Update the consuming app right after.",
          expected: appId, verb: "Rotate key", tone: "danger" });
        if (typed === null) return;
        try { const r = await write("POST", "/admin/api/apps/" + encodeURIComponent(appId) + "/rotate-key", {}); showKey(r); }
        catch (e) { fail(e); }
      } } })),
    el("div", { class: "card" },
      el("h3", { text: "Delete app" }),
      a.inbound_locked
        ? el("p", { class: "note", text: "This app is inbound_locked: deleting it is a registry file edit, not a console action." })
        : el("button", { type: "button", class: "danger", text: "Delete " + appId, on: { click: async () => {
          const typed = await typedConfirm({ title: "Delete app " + appId + "?", intro: "Its queued messages close as unroutable.",
            expected: appId, verb: "Delete app", tone: "danger" });
          if (typed === null) return;
          try { await write("POST", "/admin/api/apps/" + encodeURIComponent(appId) + "/delete", { confirm_app_id: typed }); toast("Deleted " + appId); setDirty(false); navigate(hrefFor("board")); }
          catch (e) { fail(e); }
        } } })));
}

// ----------------------------------------------------------- new app ---
function newApp() {
  const blank = { identities: [], routes: {}, allow_inbound: false, inbound_locked: false,
    callback_url_set: false, unreachable_message_set: false, allowed_users: [] };
  const idInput = el("input", { name: "app_id", required: true, pattern: ID_PATTERN, autocomplete: "off", placeholder: "e.g. rotaryphone" });
  const envHint = el("p", { class: "muted" });
  idInput.addEventListener("input", () => { envHint.textContent = "API key env var: CHAT_GATEWAY_API_KEY__" + idInput.value.toUpperCase().replace(/-/g, "_"); });
  const form = el("form", {},
    el("fieldset", {}, el("legend", { text: "1 · App id" }), el("label", {}, "App id", idInput), envHint),
    el("p", {}, "2 · Need a new Chat space identity first? ",
      el("button", { type: "button", text: "Create an identity", on: { click: () => navigate(hrefFor("new-identity")) } })),
    el("p", { class: "muted", text: "3 and 4 · identities, routes and inbound:" }),
    appFields(blank),
    el("button", { type: "submit", class: "primary", text: "Create app and mint key" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const appId = idInput.value.trim();
    try {
      const r = await withInboundConfirm(appId, (c) => write("POST", "/admin/api/apps", Object.assign(readAppFields(form, blank), { app_id: appId, confirm_app_id: c })));
      showKey(r);
    } catch (e) { fail(e); }
  });
  view(el("h2", { text: "New app" }), form);
}

// ------------------------------------------------------ new identity ---
function newIdentity() {
  const form = el("form", {},
    el("ol", { class: "guide" },
      el("li", { text: "Open the Google Chat space this identity should post into." }),
      el("li", { text: "Space name ▸ Apps & integrations ▸ Webhooks ▸ Add webhook." }),
      el("li", {}, "Set the name and avatar now — they are fixed at creation and cannot be changed later without a new webhook. "
        + "For the avatar, you can paste the PNG URL of one of the gateway's icons into the webhook's Avatar URL: ",
        el("a", { href: AVATAR_GALLERY, target: "_blank", rel: "noopener noreferrer", text: "browse the avatar gallery" }),
        " (each icon's PNG is at " + AVATAR_PNG_PATTERN + ")."),
      el("li", { text: "Save, copy the whole URL, and paste it below. It is stored in managed.env and never shown again." })),
    el("label", {}, "Identity name", el("input", { name: "name", required: true, pattern: ID_PATTERN, autocomplete: "off", placeholder: "e.g. rotaryphone-alerts" })),
    el("label", {}, "Display name (for /v1/identities)", el("input", { name: "display", required: true, autocomplete: "off" })),
    el("label", {}, "Webhook URL", el("input", { name: "webhook_url", type: "password", autocomplete: "off", required: true })),
    el("button", { type: "submit", class: "primary", text: "Create identity" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = (n) => form.querySelector("[name=" + n + "]").value;
    try {
      const r = await write("POST", "/admin/api/identities", { name: f("name").trim(), display: f("display").trim(), webhook_url: f("webhook_url") });
      toast("Identity " + r.name + " created in " + r.space + ".");
      navigate(hrefFor("new-app"));
    } catch (e) { fail(e); }
  });
  view(el("h2", { text: "New identity (Chat webhook)" }), form);
}

function replaceWebhook(name) {
  const locker = lockedHolders().get(name);
  if (locker) { toast("Identity " + name + " is held by locked app " + locker + ". " + FILE_EDIT, true); return; }
  const input = el("input", { type: "password", autocomplete: "off", "aria-label": "New webhook URL" });
  view(el("h2", { text: "Replace webhook for " + name }),
    el("p", { text: "Google Chat has no regenerate button: delete the old webhook in the space, create a new one, paste its URL here." }),
    el("label", {}, "New webhook URL", input),
    el("button", { type: "button", class: "primary", text: "Replace", on: { click: async () => {
      // CG-90 final review I1: moving this identity to a NEW space widens every
      // inbound app holding it, and the server answers 428 naming them. One
      // typed confirmation — the identity name — covers all of them.
      const send = (c) => write("POST", "/admin/api/identities/" + encodeURIComponent(name) + "/webhook", { webhook_url: input.value, confirm_name: c });
      try {
        try { await send(""); }
        catch (e) {
          if (e.status !== 428) throw e;
          const msg = /hard rule #6/i.test(e.message) ? e.message : e.message + "\n\n" + RULE_6;
          const has = !!(e.reasons && e.reasons.length);
          const typed = await typedConfirm({ title: "Confirm: replace the webhook for " + name,
            intro: has ? REFUSED_INTRO : msg, reasons: e.reasons,
            note: has && !/hard rule #6/i.test(e.message) ? RULE_6 : null, expected: name, verb: "Replace webhook", tone: "warn" });
          if (typed === null) throw new Error("cancelled");
          await send(typed);
        }
        input.value = ""; toast("Webhook replaced."); navigate(hrefFor("board"));
      }
      catch (e) { fail(e); }
    } } }));
}

function renameIdentity(name, current) {
  const input = el("input", { value: current, "aria-label": "Display name", autocomplete: "off" });
  view(el("h2", { text: "Display name for " + name }), el("label", {}, "Display name", input),
    el("button", { type: "button", class: "primary", text: "Save", on: { click: async () => {
      try { await write("PUT", "/admin/api/identities/" + encodeURIComponent(name), { display: input.value.trim() }); toast("Saved display name for " + name + "."); navigate(hrefFor("board")); }
      catch (e) { fail(e); }
    } } }));
}

async function deleteIdentity(name) {
  const typed = await typedConfirm({ title: "Delete identity " + name + "?", intro: "", expected: name, verb: "Delete identity", tone: "danger" });
  if (typed === null) return;
  try { await write("POST", "/admin/api/identities/" + encodeURIComponent(name) + "/delete", { confirm_name: typed }); toast("Deleted " + name); navigate(hrefFor("board")); }
  catch (e) { fail(e); }
}

// ------------------------------------------------------------- reveal ---
function copyKey(key, box) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(key).then(() => toast("Copied."), () => selectBox(box));
  } else selectBox(box);
}
function selectBox(box) {
  // The clipboard API needs a secure context; a plain-LAN page selects instead.
  const range = document.createRange();
  range.selectNodeContents(box);
  const sel = window.getSelection();
  sel.removeAllRanges(); sel.addRange(range);
  toast("Key selected — press Ctrl+C (or ⌘C) to copy.");
}

function reveal(r) {
  const base = window.location.origin;
  const key = r.key;
  const curl = "printf 'url = \"%s\"\\nheader = \"Authorization: Bearer %s\"\\nheader = \"Content-Type: application/json\"\\ndata = \"%s\"\\n' \\\n  \"" + base + "/v1/notify\" \"$CHAT_GATEWAY_API_KEY\" '{\\\"severity\\\":\\\"info\\\",\\\"title\\\":\\\"hello\\\"}' \\\n  | curl --config -";
  const py = "from chat_gateway.client import GatewayClient\nimport os\ngw = GatewayClient(\"" + base + "\", api_key=os.environ[\"CHAT_GATEWAY_API_KEY\"])\ngw.notify(\"info\", \"hello\")";
  const mcp = JSON.stringify({ mcpServers: { "chat-gateway": { type: "http", url: base + "/mcp", headers: { Authorization: "Bearer ${CHAT_GATEWAY_API_KEY}" } } } }, null, 2);
  const keyBox = el("div", { class: "secret", text: key });
  const result = el("p", { role: "status" });
  view(
    el("h2", { text: "API key for " + r.app_id }),
    el("p", { class: "warn", text: "This is the only time this key is shown. Copy it into the consuming app's secret store now." }),
    keyBox,
    el("button", { type: "button", text: "Copy key", on: { click: () => copyKey(key, keyBox) } }),
    r.shadows_env_file ? el("p", { class: "warn", text: "The OLD value of " + r.key_env + " is still in the read-only .env. It is inert now, but would revive if managed.env were lost — remove that line by hand." }) : null,
    el("h3", { text: "Connect" }),
    el("p", {}, "Gateway URL: ", el("code", { text: base }), " · env var in the consumer: ", el("code", { text: "CHAT_GATEWAY_API_KEY" })),
    el("h4", { text: "curl (key stays out of argv)" }), el("pre", { text: curl }),
    el("h4", { text: "Python" }), el("pre", { text: py }),
    // Only when the gateway serves /mcp (GATEWAY_ENABLE_MCP=1); otherwise this
    // would be a working-looking config for a 404 (CG-90 final review).
    state.mcp_enabled ? [el("h4", { text: "MCP client config" }), el("pre", { text: mcp })] : null,
    el("h3", { text: "Send test notification" }),
    el("p", { class: "muted", text: "202 enqueued is not delivery — this waits for the delivery log to say delivered or failed." }),
    el("button", { type: "button", class: "primary", text: "Send test", on: { click: () => testSend(key, result) } }),
    result,
    el("p", {}, el("button", { type: "button", text: "Done", on: { click: () => navigate(hrefFor("board")) } })));
}

async function testSend(key, out) {
  out.className = ""; out.textContent = "Sending…";
  try {
    const sent = await api("POST", "/v1/notify", { severity: "info", title: "chat-gateway console test", body: "Test notification sent from the admin console." }, key);
    if (sent.status !== "enqueued") { out.textContent = "Not enqueued: " + sent.status; return; }
    for (let i = 0; i < 30; i++) {
      await new Promise((res) => setTimeout(res, 2000));
      const d = await api("GET", "/v1/deliveries?limit=20", undefined, key);
      const mine = d.deliveries.filter((x) => x.id === sent.id);
      const last = mine[mine.length - 1];
      if (last && TERMINAL.includes(last.status)) {
        out.className = last.status === "delivered" ? "ok" : "error";
        out.textContent = last.status + (last.detail ? " — " + last.detail : "");
        return;
      }
      out.textContent = "Waiting… (" + (last ? last.status : "enqueued") + ")";
    }
    out.className = "error"; out.textContent = "No terminal status after 60s — check GET /v1/deliveries.";
  } catch (e) { out.className = "error"; out.textContent = e.message; }
}

// --------------------------------------------------------------- router ---
// Routes live in the URL hash (nothing is stored). `#/reveal` is in-memory
// only: reloading it lands on the "No key to show" card.
let dirty = false; // set by an inspector with unsaved edits (Task 8)
let shownHash = "#/";
let ignoreHashChange = false;
function setDirty(v) { dirty = !!v; }

// The ONE normalisation of "which route is this": a page opened with no hash
// is the board. render(), navigate() and the hashchange handler all use it.
function routeKey(hash) { return hash || "#/"; }
// The ONE builder of route hashes; ids are encoded here and decoded in routeFromHash.
function hrefFor(name, id) {
  const e = encodeURIComponent(id == null ? "" : id);
  switch (name) {
    case "board": return "#/";
    case "app": return "#/app/" + e;
    case "identity": return "#/identity/" + e;
    case "replace": return "#/identity/" + e + "/replace";
    case "room": return "#/room/" + e;
    case "new-app": return "#/new-app";
    case "new-identity": return "#/new-identity";
    case "reveal": return "#/reveal";
    default: return "#/";
  }
}

function routeFromHash() {
  const raw = routeKey(window.location.hash).replace(/^#/, "");
  const path = raw.split("?")[0];
  const seg = path.split("/").filter(Boolean).map((x) => { try { return decodeURIComponent(x); } catch (_) { return x; } });
  if (!seg.length) return { name: "board", params: {} };
  if (seg[0] === "app" && seg.length === 2) return { name: "app", params: { id: seg[1] } };
  if (seg[0] === "identity" && seg.length === 2) return { name: "identity", params: { id: seg[1] } };
  if (seg[0] === "identity" && seg.length === 3 && seg[2] === "replace") return { name: "replace", params: { id: seg[1] } };
  if (seg[0] === "room" && seg.length === 2) return { name: "room", params: { id: seg[1] } };
  if (seg[0] === "new-app" && seg.length === 1) return { name: "new-app", params: {} };
  if (seg[0] === "new-identity" && seg.length === 1) return { name: "new-identity", params: {} };
  if (seg[0] === "reveal" && seg.length === 1) return { name: "reveal", params: {} };
  return { name: "notfound", params: { kind: "view", id: path } };
}

// Runs `fn` now when the page is clean; otherwise asks once and runs it only
// if the operator chooses Discard.
function guardNavigation(fn) {
  if (!dirty) { fn(); return Promise.resolve(true); }
  return discardConfirm("unsaved changes").then((ok) => { if (ok) { setDirty(false); fn(); } return ok; });
}
function navigate(hash) {
  return guardNavigation(() => { if (routeKey(window.location.hash) === routeKey(hash)) render(); else window.location.hash = hash; });
}

function setCrumbs(...parts) {
  const nodes = [];
  parts.forEach((p, i) => {
    if (i) nodes.push(" › ");
    nodes.push(p.href ? el("a", { href: p.href, text: p.text }) : p.text);
  });
  $("crumbs").replaceChildren(...toNodes(nodes));
}
const NAV_ROUTES = [["nav-board", "board"], ["nav-new-app", "new-app"], ["nav-new-identity", "new-identity"]];
function setNav(name) {
  for (const [id, n] of NAV_ROUTES) {
    if (n === name) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current");
  }
}

function notFound(kind, id) {
  setNav(null); setCrumbs({ text: "Unknown " + kind });
  view(el("div", { class: "card" }, el("h2", { text: "No " + kind + " “" + id + "”" }),
    el("p", {}, el("a", { href: hrefFor("board"), text: "Back to the board" }))));
  return null;
}

// Placeholders for Tasks 9 and 10: enough to reach the existing actions.
function identityInspector(name) {
  const i = state.identities[name];
  const held = lockedHolders();
  view(el("h2", { text: "Identity " + name }),
    el("p", { class: "muted", text: i.display + " · " + (i.space || "no room") }),
    el("p", {},
      i.mode === "webhook" && !held.get(name) ? el("button", { type: "button", text: "Replace webhook", on: { click: () => navigate(hrefFor("replace", name)) } }) : null,
      el("button", { type: "button", text: "Rename display", on: { click: () => renameIdentity(name, i.display) } }),
      el("button", { type: "button", class: "danger", text: "Delete", on: { click: () => deleteIdentity(name) } })));
}
function roomInspector(key, room) {
  view(el("h2", { text: "Room " + (key || "none") }),
    el("p", { text: "Identities: " + (room.identities.join(", ") || "—") }),
    el("p", { text: "Apps that post here: " + (room.posting_apps.join(", ") || "—") }),
    el("p", { text: "Apps receiving inbound: " + (room.inbound_apps.join(", ") || "—") }));
}

// Called by every flow that mints a key: hold it in memory, go to #/reveal.
// The server has already minted the key: edits are moot and the reveal must
// never be blocked by the discard guard, so this bypasses guardNavigation.
function showKey(r) {
  revealData = r; setDirty(false);
  if (routeKey(window.location.hash) === hrefFor("reveal")) render(); else window.location.hash = hrefFor("reveal");
}
function revealView() {
  setNav(null);
  if (!revealData) {
    setCrumbs({ text: "Key" });
    view(el("div", { class: "card" }, el("h2", { text: "No key to show" }),
      el("p", { text: "A key is shown exactly once, at the moment it is minted. If you reloaded this page the key is gone — rotate again to get a new one." }),
      el("p", {}, el("a", { href: hrefFor("board"), text: "Back to the board" }))));
    return;
  }
  setCrumbs({ text: "App " + revealData.app_id, href: hrefFor("app", revealData.app_id) }, { text: "API key" });
  reveal(revealData);
}

function render() {
  shownHash = routeKey(window.location.hash);
  if (!state) return;
  const { name, params } = routeFromHash();
  if (name !== "reveal") revealData = null;
  setCrumbs();
  switch (name) {
    case "board": setNav("board"); board(); break;
    case "app": {
      const a = (Object.hasOwn(state.apps, params.id) && state.apps[params.id]) || notFound("app", params.id);
      if (a) { setNav(null); setCrumbs({ text: "App " + params.id }); appInspector(params.id); }
      break;
    }
    case "identity": {
      const i = (Object.hasOwn(state.identities, params.id) && state.identities[params.id]) || notFound("identity", params.id);
      if (i) { setNav(null); setCrumbs({ text: "Identity " + params.id }); identityInspector(params.id); }
      break;
    }
    case "replace": {
      const i = (Object.hasOwn(state.identities, params.id) && state.identities[params.id]) || notFound("identity", params.id);
      if (i) {
        setNav(null);
        setCrumbs({ text: "Identity " + params.id, href: hrefFor("identity", params.id) }, { text: "Replace webhook" });
        replaceWebhook(params.id);
      }
      break;
    }
    case "room": {
      const key = params.id === "none" ? "" : "spaces/" + params.id;
      const r = (Object.hasOwn(state.rooms || {}, key) && state.rooms[key]) || notFound("room", params.id);
      if (r) { setNav(null); setCrumbs({ text: "Room " + params.id }); roomInspector(key, r); }
      break;
    }
    case "new-app": setNav("new-app"); setCrumbs({ text: "New app" }); newApp(); break;
    case "new-identity": setNav("new-identity"); setCrumbs({ text: "New identity" }); newIdentity(); break;
    case "reveal": revealView(); break;
    default: notFound(params.kind, params.id);
  }
}

// Back/Forward while dirty: the hash has already moved, so put it back, ask,
// and only on Discard go where the operator was headed.
window.addEventListener("hashchange", () => {
  if (ignoreHashChange) { ignoreHashChange = false; return; }
  const target = routeKey(window.location.hash);
  if (target === shownHash) return;
  if (!dirty || !state) { render(); return; }
  ignoreHashChange = true;
  window.location.hash = shownHash;
  discardConfirm("unsaved changes").then((ok) => { if (ok) { setDirty(false); window.location.hash = target; } });
});

// --------------------------------------------------------------- notices ---
// Successes are role="status" and dismiss themselves after 6 s; refusals are
// role="alert" and stay until dismissed. Refusals also render at the control.
function notify(msg, opts) {
  const kind = opts && opts.kind === "alert" ? "alert" : "status";
  const dismiss = el("button", { type: "button", "aria-label": "Dismiss", text: "×" });
  const n = el("div", { class: "notice " + kind, role: kind }, el("p", { text: msg }), dismiss);
  dismiss.addEventListener("click", () => n.remove());
  $("notices").append(...toNodes([n]));
  if (kind === "status") setTimeout(() => n.remove(), 6000);
  return n;
}

// -------------------------------------------------------------- keyboard ---
function onKey(ev) {
  if (document.querySelector("dialog[open]")) return; // dialogs own Escape (cancel) natively
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const t = ev.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT");
  if (ev.key === "Escape") {
    if (routeFromHash().name === "reveal") return; // the key's only way out is Done
    if (!$("console").hidden) { ev.preventDefault(); navigate(hrefFor("board")); }
  } else if (ev.key === "/" && !typing && !$("console").hidden) {
    ev.preventDefault(); guardNavigation(() => $("filter").focus());
  } else if (ev.key === "?" && !typing && !$("console").hidden) {
    ev.preventDefault(); shortcutsDialog();
  }
}

// --------------------------------------------------------------- boot ---
// Ask the API before asking the human: in open mode the state call answers
// with no header and the sign-in form never appears; in key mode it is a 401
// (which does not count toward the login rate limit) and the form is shown.
async function probePosture() {
  try {
    await refresh();
    $("console").hidden = false; $("auth-mode").hidden = false;
    render(); // resume the hash the page was opened on
  } catch (e) {
    $("login").hidden = false;
    $("login-error").textContent = e.status === 401 ? "" : e.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  probePosture();
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    adminKey = $("admin-key").value.trim();
    $("admin-key").value = "";
    try {
      await refresh();
      $("login-error").textContent = "";
      $("login").hidden = true; $("console").hidden = false;
      render();
    } catch (e) { adminKey = ""; $("login-error").textContent = e.message; }
  });
  document.addEventListener("keydown", onKey);
  $("nav-board").addEventListener("click", () => navigate(hrefFor("board")));
  $("nav-new-app").addEventListener("click", () => navigate(hrefFor("new-app")));
  $("nav-new-identity").addEventListener("click", () => navigate(hrefFor("new-identity")));
  $("filter").addEventListener("input", () => {
    filterText = $("filter").value;
    if (routeFromHash().name !== "board") navigate(hrefFor("board")); else render();
  });
  const closeMenu = () => { $("registry-menu").open = false; };
  $("menu-refresh").addEventListener("click", async () => {
    closeMenu();
    try { await refresh(); render(); notify("View refreshed."); } catch (e) { fail(e); }
  });
  $("menu-reload").addEventListener("click", async () => {
    closeMenu();
    try { await api("POST", "/admin/api/reload", {}); await refresh(); render(); notify("Reloaded from disk."); }
    catch (e) { fail(e); }
  });
  $("menu-shortcuts").addEventListener("click", () => { closeMenu(); shortcutsDialog(); });
});
