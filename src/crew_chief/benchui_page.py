"""The bench interface's single page. Everything is inline; nothing loads from a network."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crew Chief bench</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --ink: #1c2230; --muted: #64707f; --line: #dde2ea;
  --accent: #2b6cb0; --accent-ink: #ffffff; --acc: #2b6cb0; --spd: #d9822b;
  --ok: #2f855a; --bad: #c53030; --warn: #b7791f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151b; --panel: #1b2029; --ink: #e6e9ef; --muted: #8c97a7; --line: #2c3340;
    --accent: #63a4e8; --accent-ink: #0d1117; --acc: #63a4e8; --spd: #e8a257;
    --ok: #5fc48a; --bad: #ef7676; --warn: #e0b45a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { display: flex; align-items: center; gap: 16px; padding: 12px 16px;
  background: var(--panel); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
header h1 { font-size: 17px; margin: 0; }
nav { display: flex; gap: 4px; flex-wrap: wrap; }
nav button { border: 0; background: none; color: var(--muted); padding: 6px 12px;
  border-radius: 6px; cursor: pointer; font: inherit; }
nav button[aria-selected="true"] { background: var(--bg); color: var(--ink); font-weight: 600; }
#badge { margin-left: auto; color: var(--muted); font-size: 13px; }
main { max-width: 1100px; margin: 0 auto; padding: 16px; }
section[hidden] { display: none; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  padding: 14px 16px; margin-bottom: 14px; }
.card h2 { font-size: 15px; margin: 0 0 10px; }
.grid { display: grid; gap: 14px; grid-template-columns: minmax(280px, 380px) 1fr; }
@media (max-width: 820px) { .grid { grid-template-columns: 1fr; } }
label { display: block; font-size: 13px; color: var(--muted); }
.slider { margin: 10px 0; }
.slider .row { display: flex; justify-content: space-between; align-items: baseline; }
.slider output { color: var(--ink); font-variant-numeric: tabular-nums; font-weight: 600; }
.slider small { color: var(--muted); display: block; font-size: 12px; }
input[type=range] { width: 100%; accent-color: var(--accent); }
input[type=text], select, textarea { width: 100%; padding: 6px 8px; font: inherit;
  background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; }
button.btn { background: var(--accent); color: var(--accent-ink); border: 0; padding: 7px 14px;
  border-radius: 6px; cursor: pointer; font: inherit; font-weight: 600; }
button.btn.secondary { background: none; color: var(--ink); border: 1px solid var(--line); }
button.btn.danger { background: none; color: var(--bad); border: 1px solid var(--bad); }
button.btn:disabled { opacity: .5; cursor: default; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); font-size: 14px; }
th { color: var(--muted); font-weight: 600; font-size: 12px; }
td.num, th.num { text-align: right; }
.bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--bg);
  min-width: 120px; }
.bar i { display: block; height: 100%; }
.bar .a { background: var(--acc); } .bar .s { background: var(--spd); }
.legend { font-size: 12px; color: var(--muted); display: flex; gap: 14px; margin-top: 8px; }
.legend b { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
.tag { font-size: 11px; padding: 1px 7px; border-radius: 10px; border: 1px solid var(--line);
  color: var(--muted); }
.tag.tied { color: var(--ok); border-color: var(--ok); }
.tag.gated { color: var(--bad); border-color: var(--bad); }
.status { font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 10px; }
.status.running { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
.status.queued { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); }
.status.done { color: var(--ok); background: color-mix(in srgb, var(--ok) 14%, transparent); }
.status.failed, .status.interrupted { color: var(--bad);
  background: color-mix(in srgb, var(--bad) 14%, transparent); }
.status.cancelled { color: var(--muted); background: var(--bg); }
.checks { display: flex; flex-wrap: wrap; gap: 6px 16px; }
.checks label { color: var(--ink); font-size: 14px; display: flex; gap: 6px; align-items: center; }
pre { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px;
  max-height: 260px; overflow: auto; font-size: 12px; margin: 8px 0 0; white-space: pre-wrap; }
.muted { color: var(--muted); } .err { color: var(--bad); } .ok { color: var(--ok); }
.job { border-top: 1px solid var(--line); padding: 10px 0; }
.job:first-child { border-top: 0; }
.progress { height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; margin-top: 6px; }
.progress i { display: block; height: 100%; background: var(--accent); }
a { color: var(--accent); }
.sens td { font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Crew Chief bench</h1>
  <nav role="tablist">
    <button role="tab" data-tab="profiles" aria-selected="true">Profiles</button>
    <button role="tab" data-tab="run" aria-selected="false">New run</button>
    <button role="tab" data-tab="jobs" aria-selected="false">Jobs</button>
    <button role="tab" data-tab="results" aria-selected="false">Results</button>
  </nav>
  <span id="badge"></span>
  <a href="/latest.html" style="font-size:13px">Weekly report</a>
  <a href="/results/" style="font-size:13px">All files</a>
</header>
<main>

<section id="tab-profiles">
  <div class="grid">
    <div class="card">
      <h2>Profile</h2>
      <label for="profile-pick">Saved profiles</label>
      <select id="profile-pick"></select>
      <div style="margin-top:8px"><label for="p-name">Name</label>
        <input type="text" id="p-name" maxlength="32"></div>
      <div style="margin-top:8px"><label for="p-desc">Description</label>
        <input type="text" id="p-desc"></div>
      <div id="sliders"></div>
      <div class="actions">
        <button class="btn" id="save">Save</button>
        <button class="btn secondary" id="revert">Revert</button>
        <button class="btn danger" id="delete">Delete</button>
        <button class="btn secondary" id="reset">Reset to defaults</button>
      </div>
      <p id="p-msg" class="muted"></p>
    </div>
    <div>
      <div class="card">
        <h2>Preview on a result</h2>
        <label for="preview-pick">Result</label>
        <select id="preview-pick"></select>
        <p class="muted" id="preview-note"></p>
        <div id="ranking"></div>
        <div class="legend"><span><b style="background:var(--acc)"></b>accuracy points</span>
          <span><b style="background:var(--spd)"></b>speed points</span></div>
      </div>
      <div class="card">
        <h2>Who leads as accuracy weight changes</h2>
        <div id="sensitivity" class="sens"></div>
      </div>
    </div>
  </div>
</section>

<section id="tab-run" hidden>
  <div class="card">
    <h2>Start a benchmark</h2>
    <label for="r-kind">Kind</label>
    <select id="r-kind">
      <option value="taskbench">taskbench: score runners on each suite</option>
      <option value="routebench">routebench: compare single models, routing and cascades</option>
    </select>
    <h2 style="margin-top:14px">Suites</h2>
    <div class="checks" id="r-suites"></div>
    <div class="actions" style="margin-top:6px">
      <button class="btn secondary" id="suites-all">All</button>
      <button class="btn secondary" id="suites-clockwork">Clockwork</button>
      <button class="btn secondary" id="suites-none">None</button>
    </div>
    <h2 style="margin-top:14px" id="r-runners-title">Runners</h2>
    <div class="checks" id="r-runners"></div>
    <label for="r-extra" style="margin-top:8px">More runner specs, one per line
      (rules, ollama:&lt;model&gt;, llamacpp:&lt;model&gt;, systemone:&lt;model&gt;)</label>
    <textarea id="r-extra" rows="2"></textarea>
    <div id="r-taskonly">
      <label for="r-split" style="margin-top:8px">Split</label>
      <select id="r-split"><option>dev</option><option>heldout</option><option>all</option></select>
    </div>
    <div id="r-routeonly" hidden>
      <label for="r-router" style="margin-top:8px">Router</label>
      <input type="text" id="r-router" value="systemone:clef-flash">
      <label for="r-thr" style="margin-top:8px">Cascade thresholds</label>
      <input type="text" id="r-thr" value="0.6, 0.8, 0.95">
    </div>
    <label style="margin-top:10px;color:var(--ink);display:flex;gap:6px;align-items:center">
      <input type="checkbox" id="r-private"> Keep results private (not under the shared results/ folder)</label>
    <div class="actions">
      <button class="btn" id="start">Start job</button>
    </div>
    <p id="r-msg" class="muted"></p>
    <p class="muted">Jobs run one at a time so latencies are not distorted by a neighbour on the GPU.
      Each job records the GPU memory in use when it started.</p>
  </div>
</section>

<section id="tab-jobs" hidden>
  <div class="card"><div id="jobs"></div></div>
</section>

<section id="tab-results" hidden>
  <div class="card">
    <h2>Results</h2>
    <div id="results"></div>
  </div>
</section>

</main>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { profiles: [], defaults: [], draft: null, results: [], jobs: [], open: new Set() };

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ---- tabs
function showTab(name) {
  for (const b of document.querySelectorAll("nav button"))
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== "tab-" + name;
  try { localStorage.setItem("bench-tab", name); } catch (e) {}
  if (name === "jobs" || name === "results") refreshJobs();
}
for (const b of document.querySelectorAll("nav button"))
  b.addEventListener("click", () => showTab(b.dataset.tab));

// ---- sliders
const logMs = (ms) => Math.log10(ms);
const SLIDERS = [
  { key: "accuracy_weight", label: "Accuracy weight", min: 0, max: 1, step: 0.01,
    hint: "Share of the score from accuracy; speed gets the rest." },
  { key: "relative_weight", label: "Relative speed", min: 0, max: 1, step: 0.01,
    hint: "Share of speed measured against the fastest and slowest performer in the comparison; the rest uses the absolute target and ceiling." },
  { key: "tail_weight", label: "Tail (p90) weight", min: 0, max: 1, step: 0.01,
    hint: "Share of speed taken from p90 latency instead of the mean." },
  { key: "target_ms", label: "Target latency", log: true, min: 1, max: 5, step: 0.01, unit: "ms",
    hint: "Full absolute speed credit at or under this." },
  { key: "ceiling_ms", label: "Ceiling latency", log: true, min: 1, max: 5, step: 0.01, unit: "ms",
    hint: "No absolute speed credit at or over this." },
  { key: "min_accuracy", label: "Minimum accuracy (gate)", min: 0, max: 1, step: 0.01, optional: true,
    hint: "Below this a model is gated and ranks last." },
  { key: "max_p90_ms", label: "Maximum p90 (gate)", log: true, min: 1, max: 5, step: 0.01, unit: "ms",
    optional: true, hint: "A slower p90 gates the model." },
  { key: "tie_margin", label: "Tie margin", min: 0, max: 0.1, step: 0.005,
    hint: "Scores this close to the best count as tied." },
];
const fromSlider = (s, v) => (s.log ? Math.round(Math.pow(10, v)) : Number(v));
const toSlider = (s, v) => (s.log ? logMs(v) : v);
const fmt = (s, v) => (s.log ? (v >= 1000 ? (v / 1000).toFixed(1) + " s" : Math.round(v) + " ms") : Number(v).toFixed(s.step < 0.01 ? 3 : 2));

function buildSliders() {
  $("sliders").innerHTML = SLIDERS.map((s) => `
    <div class="slider" data-key="${s.key}">
      <div class="row"><label for="s-${s.key}">${esc(s.label)}</label>
        <span>${s.optional ? `<label style="display:inline-flex;gap:4px"><input type="checkbox" id="on-${s.key}"> on</label> ` : ""}<output id="o-${s.key}"></output></span></div>
      <input type="range" id="s-${s.key}" min="${s.min}" max="${s.max}" step="${s.step}">
      <small>${esc(s.hint)}</small>
    </div>`).join("");
  for (const s of SLIDERS) {
    $("s-" + s.key).addEventListener("input", () => onSlide(s));
    const on = $("on-" + s.key);
    if (on) on.addEventListener("change", () => onSlide(s));
  }
}
function onSlide(s) {
  const on = $("on-" + s.key);
  state.draft[s.key] = on && !on.checked ? null : fromSlider(s, $("s-" + s.key).value);
  syncSliders();
  schedulePreview();
}
function syncSliders() {
  for (const s of SLIDERS) {
    const v = state.draft[s.key];
    const on = $("on-" + s.key);
    if (on) on.checked = v !== null && v !== undefined;
    $("s-" + s.key).disabled = on ? !on.checked : false;
    if (v !== null && v !== undefined) $("s-" + s.key).value = toSlider(s, v);
    $("o-" + s.key).textContent = v === null || v === undefined ? "off" : fmt(s, v);
  }
}
function loadDraft(name) {
  const p = state.profiles.find((x) => x.name === name);
  if (!p) return;
  state.draft = JSON.parse(JSON.stringify(p));
  $("p-name").value = p.name;
  $("p-desc").value = p.description || "";
  $("profile-pick").value = name;
  syncSliders();
  schedulePreview();
}
function currentDraft() {
  state.draft.name = $("p-name").value.trim();
  state.draft.description = $("p-desc").value;
  return state.draft;
}
function renderProfilePick(selected) {
  $("profile-pick").innerHTML = state.profiles.map((p) =>
    `<option value="${esc(p.name)}">${esc(p.name)}${state.defaults.includes(p.name) ? "" : " (yours)"}</option>`).join("");
  if (selected) $("profile-pick").value = selected;
}
async function loadProfiles(select) {
  const data = await api("/api/profiles");
  state.profiles = data.profiles;
  state.defaults = data.defaults;
  const name = select || (state.draft && state.draft.name) || (state.profiles[0] && state.profiles[0].name);
  renderProfilePick(name);
  loadDraft(state.profiles.some((p) => p.name === name) ? name : state.profiles[0].name);
}
$("profile-pick").addEventListener("change", () => loadDraft($("profile-pick").value));
$("revert").addEventListener("click", () => loadDraft($("profile-pick").value));
$("save").addEventListener("click", async () => {
  try {
    const d = currentDraft();
    await api("/api/profiles", "POST", d);
    $("p-msg").className = "ok"; $("p-msg").textContent = `Saved "${d.name}". New runs score with it.`;
    await loadProfiles(d.name);
  } catch (e) { $("p-msg").className = "err"; $("p-msg").textContent = e.message; }
});
$("delete").addEventListener("click", async () => {
  const name = $("profile-pick").value;
  if (!confirm(`Delete profile "${name}"?`)) return;
  try { await api("/api/profiles/" + encodeURIComponent(name), "DELETE"); state.draft = null; await loadProfiles(); }
  catch (e) { $("p-msg").className = "err"; $("p-msg").textContent = e.message; }
});
$("reset").addEventListener("click", async () => {
  if (!confirm("Discard your saved profiles and restore the tracked defaults?")) return;
  await api("/api/profiles/reset", "POST", {}); state.draft = null; await loadProfiles();
});

// ---- preview
let previewTimer = null, previewSeq = 0;
function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(preview, 120); }
async function preview() {
  const ref = $("preview-pick").value;
  if (!ref || !state.draft) { $("ranking").innerHTML = ""; return; }
  const seq = ++previewSeq;
  try {
    const d = currentDraft();
    const out = await api("/api/rescore", "POST", { result: ref, profile: d });
    if (seq !== previewSeq) return;
    $("preview-note").className = "muted";
    $("preview-note").textContent = out.describe;
    renderRanking(out);
  } catch (e) {
    $("preview-note").className = "err"; $("preview-note").textContent = e.message;
  }
}
function renderRanking(out) {
  const p = out.profile, w = p.accuracy_weight;
  const rows = out.ranking.map((r, i) => {
    const e = out.entries[r.name];
    const a = r.score === null ? 0 : w * r.quality * 100;
    const s = r.score === null ? 0 : (1 - w) * r.speed * 100;
    const tag = r.gate ? `<span class="tag gated" title="${esc(r.gate)}">gated</span>` : r.tied ? `<span class="tag tied">${i === 0 ? "lead" : "tied"}</span>` : "";
    return `<tr><td>${i + 1}</td><td>${esc(r.name)} ${tag}</td>
      <td class="num">${r.score === null ? "—" : r.score.toFixed(3)}</td>
      <td><div class="bar"><i class="a" style="width:${a}%"></i><i class="s" style="width:${s}%"></i></div></td>
      <td class="num">${e.accuracy.toFixed(3)}</td><td class="num">${r.speed.toFixed(2)}</td>
      <td class="num">${Math.round(e.mean_ms)}</td><td class="num">${Math.round(e.p90_ms)}</td></tr>`;
  }).join("");
  $("ranking").innerHTML = `<table><thead><tr><th>#</th><th>Performer</th><th class="num">Score</th><th></th>
    <th class="num">Accuracy</th><th class="num">Speed</th><th class="num">Mean ms</th><th class="num">p90 ms</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  const sens = Object.entries(out.sensitivity).map(([w2, names]) =>
    `<tr><td>${esc(w2)}${Number(w2) === p.accuracy_weight ? " (this profile)" : ""}</td><td>${names.map(esc).join(", ")}</td></tr>`).join("");
  $("sensitivity").innerHTML = `<table><thead><tr><th>Accuracy weight</th><th>Tied for the lead</th></tr></thead><tbody>${sens}</tbody></table>`;
}
$("preview-pick").addEventListener("change", () => {
  try { localStorage.setItem("bench-preview", $("preview-pick").value); } catch (e) {}
  preview();
});
function renderPreviewPick() {
  const keep = $("preview-pick").value;
  let saved = ""; try { saved = localStorage.getItem("bench-preview") || ""; } catch (e) {}
  $("preview-pick").innerHTML = state.results.map((r) =>
    `<option value="${esc(r.ref)}">${esc(r.name)}${r.dir === "private" ? " (private)" : ""}</option>`).join("");
  const want = [keep, saved].find((v) => v && state.results.some((r) => r.ref === v));
  const first = state.results.find((r) => r.kind === "routebench") || state.results[0];
  $("preview-pick").value = want || (first && first.ref) || "";
}

// ---- new run
async function loadRunForm() {
  const [suites, models] = await Promise.all([api("/api/suites"), api("/api/models")]);
  $("r-suites").innerHTML = suites.suites.map((s) =>
    `<label><input type="checkbox" name="suite" value="${esc(s)}"> ${esc(s)}</label>`).join("");
  const runners = ["rules", ...models.systemone.map((m) => "systemone:" + m), ...models.ollama.map((m) => "ollama:" + m)];
  $("r-runners").innerHTML = runners.map((r) =>
    `<label><input type="checkbox" name="runner" value="${esc(r)}"${r.startsWith("systemone:") ? " checked" : ""}> ${esc(r)}</label>`).join("");
  setKind();
}
function setKind() {
  const route = $("r-kind").value === "routebench";
  $("r-routeonly").hidden = !route; $("r-taskonly").hidden = route;
  $("r-runners-title").textContent = route ? "Candidates" : "Runners";
}
$("r-kind").addEventListener("change", setKind);
const checkSuites = (pred) => document.querySelectorAll("input[name=suite]").forEach((c) => { c.checked = pred(c.value); });
$("suites-all").addEventListener("click", () => checkSuites(() => true));
$("suites-none").addEventListener("click", () => checkSuites(() => false));
$("suites-clockwork").addEventListener("click", () => checkSuites((v) => v.startsWith("clockwork-")));
$("start").addEventListener("click", async () => {
  const checked = (name) => [...document.querySelectorAll(`input[name=${name}]:checked`)].map((c) => c.value);
  const extra = $("r-extra").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const spec = {
    kind: $("r-kind").value, suites: checked("suite"), runners: [...checked("runner"), ...extra],
    split: $("r-split").value, router: $("r-router").value.trim(),
    thresholds: $("r-thr").value.split(/[ ,]+/).filter(Boolean).map(Number),
    private: $("r-private").checked,
  };
  try {
    const job = await api("/api/jobs", "POST", spec);
    $("r-msg").className = "ok"; $("r-msg").textContent = "Queued job " + job.id;
    state.open.add(job.id);
    showTab("jobs");
  } catch (e) { $("r-msg").className = "err"; $("r-msg").textContent = e.message; }
});

// ---- jobs and results
const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "—");
const dur = (a, b) => (a ? Math.round((b || Date.now() / 1000) - a) + " s" : "—");
const fileLink = (ref) => `<a href="/files/${esc(ref)}" target="_blank" rel="noopener">${esc(ref.split("/")[1].split(".").pop())}</a>`;
function openResult(ref) {
  showTab("profiles");
  $("preview-pick").value = ref;
  try { localStorage.setItem("bench-preview", ref); } catch (e) {}
  preview();
}
window.openResult = openResult;
function renderJobs() {
  const active = state.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  $("badge").textContent = active ? `${active} job${active > 1 ? "s" : ""} active` : "";
  if (!state.jobs.length) { $("jobs").innerHTML = '<p class="muted">No jobs yet.</p>'; return; }
  $("jobs").innerHTML = state.jobs.map((j) => {
    const pct = j.units_total ? Math.round(100 * j.units_done / j.units_total) : 0;
    const json = (j.outputs || []).find((o) => o.endsWith(".json"));
    const links = (j.outputs || []).map((o) => fileLink(j.out + "/" + o)).join(" · ");
    const warn = j.gpu_used_mib_at_start ? `<div class="muted">GPU memory in use at start: ${j.gpu_used_mib_at_start} MiB (includes any model Ollama already holds).</div>` : "";
    const open = state.open.has(j.id);
    return `<div class="job" data-id="${esc(j.id)}">
      <div><span class="status ${esc(j.status)}">${esc(j.status)}</span>
        <b>${esc(j.kind)}</b> ${esc(j.spec.suites.length)} suite${j.spec.suites.length > 1 ? "s" : ""},
        ${esc(j.spec.runners.length)} ${j.kind === "routebench" ? "candidates" : "runners"}
        ${j.out === "private" ? '<span class="tag">private</span>' : ""}
        <span class="muted">${when(j.created)} · ${dur(j.started, j.finished)}</span></div>
      ${j.status === "running" || j.status === "queued" ? `<div class="progress"><i style="width:${pct}%"></i></div>
        <div class="muted">${esc(j.current)} ${j.kind === "taskbench" ? `(${j.units_done}/${j.units_total} runs)` : ""}</div>` : ""}
      ${warn}
      <div class="actions">
        ${json ? `<button class="btn" onclick="openResult('${esc(j.out + "/" + json)}')">Score under a profile</button>` : ""}
        <button class="btn secondary" data-log="${esc(j.id)}">${open ? "Hide log" : "Log"}</button>
        ${j.status === "running" || j.status === "queued" ? `<button class="btn danger" data-cancel="${esc(j.id)}">Cancel</button>` : ""}
        <span class="muted" style="align-self:center">${links}</span></div>
      ${open ? `<pre id="log-${esc(j.id)}">loading…</pre>` : ""}</div>`;
  }).join("");
  for (const id of state.open) loadLog(id);
}
async function loadLog(id) {
  try {
    const j = await api("/api/jobs/" + id);
    const el = $("log-" + id);
    if (el) { const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 8; el.textContent = j.log || "(empty)"; if (stick) el.scrollTop = el.scrollHeight; }
  } catch (e) {}
}
$("jobs").addEventListener("click", async (ev) => {
  const t = ev.target;
  if (t.dataset.log) { state.open.has(t.dataset.log) ? state.open.delete(t.dataset.log) : state.open.add(t.dataset.log); renderJobs(); }
  if (t.dataset.cancel) { try { await api(`/api/jobs/${t.dataset.cancel}/cancel`, "POST", {}); } catch (e) { alert(e.message); } refreshJobs(); }
});
function renderResults() {
  if (!state.results.length) { $("results").innerHTML = '<p class="muted">No results yet.</p>'; return; }
  $("results").innerHTML = `<table><thead><tr><th>Result</th><th>Kind</th><th>Written</th><th>Job</th><th>Files</th><th></th></tr></thead><tbody>` +
    state.results.map((r) => `<tr><td>${esc(r.name)}${r.dir === "private" ? ' <span class="tag">private</span>' : ""}</td>
      <td>${esc(r.kind)}</td><td>${when(r.modified)}</td>
      <td>${r.job ? `<a href="#" data-job="${esc(r.job)}">${esc(r.job)}</a>` : '<span class="muted">—</span>'}</td>
      <td>${r.files.map(fileLink).join(" · ")}</td>
      <td><button class="btn secondary" onclick="openResult('${esc(r.ref)}')">Score</button></td></tr>`).join("") + "</tbody></table>";
}
$("results").addEventListener("click", (ev) => {
  const job = ev.target.dataset && ev.target.dataset.job;
  if (job) { ev.preventDefault(); state.open.add(job); showTab("jobs"); }
});
async function refreshJobs() {
  try {
    const [jobs, results] = await Promise.all([api("/api/jobs"), api("/api/results")]);
    const before = state.results.length;
    state.jobs = jobs.jobs; state.results = results.results;
    renderJobs(); renderResults();
    if (state.results.length !== before) { renderPreviewPick(); preview(); }
  } catch (e) {}
}

// ---- start
(async () => {
  buildSliders();
  await Promise.all([refreshJobs(), loadRunForm()]);
  renderPreviewPick();
  await loadProfiles();
  let tab = "profiles"; try { tab = localStorage.getItem("bench-tab") || tab; } catch (e) {}
  showTab(tab);
  setInterval(() => { if (document.visibilityState === "visible") refreshJobs(); },
    2000);
})();
</script>
</body>
</html>
"""
