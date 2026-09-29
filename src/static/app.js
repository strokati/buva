/* Business Validation Workspace — frontend.
   Static questionnaire content: fetched from /static/content.json.
   User data: fetched from /api/state, autosaved to SQLite via the API. */
(() => {
"use strict";

let C = null; // questionnaire content, loaded before anything renders
const $ = id => document.getElementById(id);

let state = { tasks: {}, sections: {}, customTasks: [], username: "" };
let currentAddSection = null;
let toastTimer = null;
const timers = {};

const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
const pad2 = n => String(n).padStart(2, "0");

// --- API -------------------------------------------------------------------

async function api(path, opts = {}) {
  const hasBody = opts.body !== undefined;
  const res = await fetch(path, {
    method: opts.method || (hasBody ? "POST" : "GET"),
    headers: hasBody && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    body: opts.body,
  });
  if (res.status === 401) { location.href = "/login"; throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}

function debounce(key, fn, ms = 600) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, ms);
}

// --- state ------------------------------------------------------------------

const customKey = ct => `CUSTOM-${ct.id}`;
const knownTaskIds = () => [
  ...C.sections.flatMap(s => s.tasks.map(t => t.id)),
  ...state.customTasks.map(customKey),
];

function taskState(id) {
  if (!state.tasks[id]) state.tasks[id] = { answer: "", source: "", status: "Open", confidence: "D", evidence: [] };
  if (!Array.isArray(state.tasks[id].evidence)) state.tasks[id].evidence = [];
  return state.tasks[id];
}

function saveTask(id, patch) {
  debounce(`task-${id}`, () =>
    api(`/api/tasks/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) })
      .then(() => markSaved(id))
      .catch(e => toast("Помилка збереження: " + e.message))
  );
}

function markSaved(id) {
  const el = $("saved-" + id);
  if (!el) return;
  el.textContent = "Збережено";
  clearTimeout(el.__t);
  el.__t = setTimeout(() => { el.textContent = "Автозбереження увімкнено"; }, 900);
}

async function reloadState() {
  state = await api("/api/state");
}

// --- rendering ----------------------------------------------------------------

function phaseName(p) { return C.phaseNames[p] || p; }
function phaseDescr(p) { return C.phaseDescriptions[p] || ""; }

function render() {
  document.title = "Germany Business Validation Workspace";
  if (state.username) $("menuUser").textContent = state.username;
  const root = $("app");
  root.innerHTML = renderHero() + renderNotice() + renderToc() + C.sections.map(renderSectionGroup).join("") + renderAppendices();
  updateProgress();
  bindNav();
}

function renderHero() {
  return `<div class="hero"><div class="hero-grid">
    <div><div class="eyebrow">Germany-first • evidence-first • economics-first</div>
    <h1>Business Validation Workspace</h1>
    <p>Один довгий research-процес: сформулюй гіпотези, знайди докази, порахуй економіку, перевір німецькі вимоги, проведи paid validation — і лише після цього приймай рішення.</p></div>
    <div class="progress-panel">
      <div class="progress-label"><span>Загальний прогрес</span><strong id="progressPct">0%</strong></div>
      <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
      <div class="stats">
        <div class="stat"><strong id="doneCount">0</strong><span>готових задач</span></div>
        <div class="stat"><strong id="evidenceCount">0</strong><span>джерел/доказів</span></div>
        <div class="stat"><strong id="customCount">0</strong><span>додаткових задач</span></div>
      </div>
    </div></div></div>`;
}

function renderNotice() {
  return `<div class="notice"><div>✓</div><div><b>Правило роботи.</b> Факт ≠ висновок. Кожну ключову цифру прив'язуй до джерела, дати та географії. Для німецьких legal/tax питань перевіряй актуальні офіційні джерела на момент запуску.</div></div>`;
}

function renderToc() {
  return `<section class="toc-section" id="toc"><div class="section-kicker"><div>
    <div class="section-id">Navigation</div><h2 class="toc-name">Зміст</h2>
    <div class="toc-sub">Клікни на розділ — сторінка прокрутиться до потрібного місця.</div></div>
    <button class="btn" id="toTop" type="button">↑ Верх</button></div>
    <div class="toc-grid">${C.sections.map(s => `
      <a class="toc-item" href="#s-${s.num}"><div class="toc-no">${pad2(s.num)}</div>
      <div><div class="toc-name">${esc(s.title)}</div>
      <div class="toc-sub">${esc(phaseName(s.phase[1]))} • ${s.tasks.length} задач</div></div></a>`).join("")}
    </div></section>`;
}

function renderSectionGroup(s, i) {
  const prev = i > 0 ? C.sections[i - 1] : null;
  let h = "";
  if (!prev || prev.phase[1] !== s.phase[1]) {
    h += `<div class="phase" id="phase-${esc(s.phase[1])}"><span class="phase-label">PHASE ${esc(s.phase[0])} · ${esc(s.phase[1])}</span><h2>${esc(phaseName(s.phase[1]))}</h2><p>${esc(phaseDescr(s.phase[1]))}</p></div>`;
  }
  const custom = state.customTasks.filter(t => t.section === s.num);
  const done = [...s.tasks, ...custom].filter(t => taskState(t.id).status === "Done").length;
  const note = state.sections[String(s.num)] || { note: "", key_number: "" };
  const next = C.sections.find(x => x.num === s.num + 1);
  h += `<section class="section" id="s-${s.num}"><div class="section-head">
    <div class="section-kicker"><div class="section-id">${pad2(s.num)} / ${esc(s.phase[1])}</div>
    <div class="section-progress" id="sec-prog-${s.num}">${done}/${s.tasks.length + custom.length} done</div></div>
    <h2 class="section-title">${esc(s.title)}</h2>
    <p class="objective">${esc(s.objective)}</p>
    ${s.example ? `<div class="section-example"><strong>Фіктивний приклад розділу</strong>${esc(s.example)}</div>` : ""}
    </div><div class="tasks">
    ${s.tasks.map(t => renderTask(t, false)).join("")}
    ${custom.map(t => renderTask({ id: customKey(t), title: t.title, instruction: t.instruction, example: t.example }, true)).join("")}
    <button class="add-task" type="button" data-action="add-task" data-section="${s.num}">＋ Додати власне завдання до цього розділу</button>
    <div class="takeaway"><h3>Підсумок розділу</h3><div class="takeaway-grid">
      <div><label class="write-label">Ключовий висновок</label><textarea data-section-note="${s.num}" placeholder="Що цей розділ довів або спростував? Який факт є найважливішим?">${esc(note.note)}</textarea></div>
      <div><label class="write-label">Ключова цифра</label><input data-section-number="${s.num}" placeholder="наприклад €24 млн SAM" value="${esc(note.key_number)}"></div>
    </div></div>
    <div class="next"><a href="${next ? `#s-${next.num}` : "#appendix-use"}">${next ? "Далі → " + esc(next.title) : "До фінального контролю ↓"}</a></div>
    </div></section>`;
  return h;
}

function renderTask(t, isCustom) {
  const st = taskState(t.id);
  const statuses = ["Open", "In progress", "Done"].map(x =>
    `<button class="pill status-btn ${st.status === x ? "active" : ""}" type="button" data-action="status" data-status="${x}">${x === "In progress" ? "Doing" : x}</button>`).join("");
  const confidence = ["A", "B", "C", "D"].map(c =>
    `<button class="pill ${st.confidence === c ? "active" : ""}" type="button" data-action="confidence" data-confidence="${c}" data-pill-confidence="${c}">${c}</button>`).join("");
  const evidence = st.evidence.map(ev => renderEvidenceRow(ev.id, ev.value)).join("");
  return `<article class="task" data-task-id="${esc(t.id)}">
    <div class="task-head"><div class="task-id">${esc(t.id)}</div>
    <div class="task-main"><h3 class="task-title">${esc(t.title)}${isCustom ? ' <span class="custom-badge">CUSTOM</span>' : ""}</h3>
    <p class="task-instruction">${esc(t.instruction || "Внеси конкретний факт, цифру або спостереження.")}</p></div>
    <div class="task-controls">${statuses}${isCustom ? `<button class="del-task" type="button" data-action="del-task" data-task-num="${esc(t.id.replace("CUSTOM-", ""))}" title="Видалити завдання">✕</button>` : ""}</div></div>
    <div class="task-body">
      <div class="example-box"><div class="label">Приклад • fiction only</div><p>${esc(t.example || "Фіктивний приклад: внеси конкретний evidence, який доводить або спростовує цю гіпотезу.")}</p></div>
      <label class="write-label">Твоя інформація <span class="write-hint">факти • цифри • спостереження • висновок</span></label>
      <textarea class="answer" data-answer="${esc(t.id)}" placeholder="Внеси знайдену інформацію. Не обмежуйся загальними словами — записуй конкретні числа, умови, quotes, результати тестів або спостереження.">${esc(st.answer)}</textarea>
      <div class="source-row">
        <input class="source" data-source="${esc(t.id)}" value="${esc(st.source)}" placeholder="Основне джерело / URL (необов'язково, але рекомендовано)">
        <button class="btn evidence-btn" type="button" data-action="add-evidence">＋ Evidence</button>
      </div>
      <div class="extra-evidence" data-evlist="${esc(t.id)}">${evidence}</div>
      <div class="task-meta"><div class="task-controls">${confidence}</div><span class="saved" id="saved-${esc(t.id)}">Автозбереження увімкнено</span></div>
    </div></article>`;
}

function renderEvidenceRow(evId, value) {
  return `<div class="ev"><input data-ev-input data-evidence-id="${evId}" value="${esc(value)}" placeholder="Додаткове джерело / evidence">
    <button class="ev-del" type="button" data-action="del-evidence" data-evidence-id="${evId}" title="Видалити">✕</button></div>`;
}

function renderAppendices() {
  const howto = [
    ["Формулюй невідомість → метод перевірки → evidence.", "Не починай з красивого pitch deck."],
    ["Відділяй факт від інтерпретації.", "«47% сказали X» — факт; «значить ринок великий» — гіпотеза."],
    ["Зберігай provenance.", "URL/документ, дата, географія, reference period, що саме вимірюється."],
    ["Не змішуй Germany з DACH/EU/global.", ""],
    ["Actual payment сильніший за «готовий купити».", ""],
    ["Thresholds визначай до тесту.", "Не змінюй їх заднім числом через неприємний результат."],
  ];
  let h = `<div class="appendix"><div class="phase"><span class="phase-label">REFERENCE</span><h2>Appendices</h2><p>Правила роботи, розрахунки та фінальний контроль.</p></div>`;
  h += `<section class="section" id="appendix-use"><div class="section-head"><h2 class="section-title">Як користуватися системою</h2><p class="objective">Працюй знизу вгору: evidence спочатку, інтерпретація потім.</p></div>
    <div class="tasks"><div class="task"><div class="task-body"><div class="checklist">
    ${howto.map(([b, sub]) => `<div class="check"><input type="checkbox"><div><b>${esc(b)}</b>${sub ? `<div class="toc-sub">${esc(sub)}</div>` : ""}</div></div>`).join("")}
    </div></div></div></div></section>`;
  h += `<section class="section" id="appendix-calcs"><div class="section-head"><h2 class="section-title">Calculation Definitions</h2><p class="objective">Використовуй однакові визначення у всій моделі.</p></div>
    <div class="tasks"><div class="definition-grid">
    ${C.calcDefs.map(([n, d]) => `<div class="definition"><b>${esc(n)}</b><div>${esc(d)}</div></div>`).join("")}
    </div></div></section>`;
  h += `<section class="section" id="germany-sources"><div class="section-head"><div class="section-id">GERMANY STARTER SOURCES</div><h2 class="section-title">Початкові офіційні джерела</h2><p class="objective">Це стартові точки для перевірки. Перед запуском перевіряй актуальність конкретного правила.</p></div>
    <div class="tasks"><div class="definition-grid">
    ${C.starterSources.map(([n, d, u]) => `<div class="definition"><b>${esc(n)}</b><div class="source-desc">${esc(d)}</div><a class="source-link" href="${esc(u)}" target="_blank" rel="noopener">Відкрити джерело ↗</a></div>`).join("")}
    </div></div></section>`;
  h += `<div class="app-footer">Версія workspace: ${esc(C.version)} • Фіктивні приклади не є ринковими фактами. Legal/tax content is a research checklist, not professional advice.</div>`;
  return h + `</div>`;
}

// --- progress & nav -------------------------------------------------------------

function updateProgress() {
  const known = knownTaskIds();
  const total = known.length;
  const done = known.filter(id => taskState(id).status === "Done").length;
  const pct = total ? Math.round(done / total * 100) : 0;
  $("progressPct").textContent = pct + "%";
  $("progressFill").style.width = pct + "%";
  $("doneCount").textContent = done;
  $("evidenceCount").textContent = known.reduce(
    (n, id) => { const st = taskState(id); return n + (st.source ? 1 : 0) + st.evidence.filter(ev => (ev.value || "").trim()).length; }, 0);
  $("customCount").textContent = state.customTasks.length;
  C.sections.forEach(s => {
    const custom = state.customTasks.filter(t => t.section === s.num);
    const tasks = [...s.tasks, ...custom];
    const d = tasks.filter(t => taskState(t.id).status === "Done").length;
    const el = $("sec-prog-" + s.num);
    if (el) el.textContent = `${d}/${tasks.length} done`;
    const nav = document.querySelector(`.nav a[data-section="${s.num}"]`);
    if (nav) {
      nav.classList.toggle("done", tasks.length > 0 && d === tasks.length);
      nav.querySelector(".count").textContent = `${d}/${tasks.length}`;
    }
  });
}

function updateNav() {
  $("sideNav").innerHTML = C.sections.map(s => `
    <a href="#s-${s.num}" data-section="${s.num}"><span class="dot"></span>
    <span>${pad2(s.num)} ${esc(s.title)}</span><span class="count">0/${s.tasks.length}</span></a>`).join("");
}

let observer = null;
function bindNav() {
  updateNav();
  updateProgress();
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(entries => {
    const hit = entries.filter(e => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!hit) return;
    document.querySelectorAll(".nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "#" + hit.target.id));
  }, { rootMargin: "-20% 0px -65% 0px", threshold: [0, .2, .5] });
  document.querySelectorAll(".section").forEach(e => observer.observe(e));
}

// --- actions ----------------------------------------------------------------------

function setStatus(id, status, taskEl) {
  taskState(id).status = status;
  saveTask(id, { status });
  taskEl.querySelectorAll("[data-action='status']").forEach(b => b.classList.toggle("active", b.dataset.status === status));
  updateProgress();
}

function setConfidence(id, confidence, taskEl) {
  taskState(id).confidence = confidence;
  saveTask(id, { confidence });
  taskEl.querySelectorAll("[data-pill-confidence]").forEach(b => b.classList.toggle("active", b.dataset.pillConfidence === confidence));
}

function addEvidence(id, taskEl) {
  api(`/api/tasks/${encodeURIComponent(id)}/evidence`, { body: JSON.stringify({ value: "" }) })
    .then(created => {
      taskState(id).evidence.push({ id: created.id, value: created.value });
      const list = taskEl.querySelector(`[data-evlist="${id}"]`);
      list.insertAdjacentHTML("beforeend", renderEvidenceRow(created.id, ""));
      list.lastElementChild.querySelector("input").focus();
    })
    .catch(e => toast("Не вдалося додати evidence: " + e.message));
}

function deleteEvidence(taskEl, evId) {
  api(`/api/evidence/${evId}`, { method: "DELETE" })
    .then(() => {
      const taskId = taskEl.dataset.taskId;
      const st = taskState(taskId);
      st.evidence = st.evidence.filter(ev => ev.id !== evId);
      taskEl.querySelector(`[data-ev-input][data-evidence-id="${evId}"]`)?.closest(".ev").remove();
      updateProgress();
    })
    .catch(e => toast("Не вдалося видалити evidence: " + e.message));
}

function deleteCustomTask(taskNum) {
  const ct = state.customTasks.find(t => t.id === taskNum);
  if (!ct) return;
  if (!confirm(`Видалити власне завдання «${ct.title}» разом із даними?`)) return;
  api(`/api/custom-tasks/${taskNum}`, { method: "DELETE" })
    .then(reloadState)
    .then(() => { render(); toast("Завдання видалено"); })
    .catch(e => toast("Помилка: " + e.message));
}

function filterTasks(q) {
  q = q.toLowerCase().trim();
  document.querySelectorAll(".task[data-task-id]").forEach(el => {
    el.classList.toggle("hidden", !!q && !el.innerText.toLowerCase().includes(q));
  });
}

// --- modals ------------------------------------------------------------------------

function openModal(id) { $(id).classList.add("show"); }
function closeModal(id) { $(id).classList.remove("show"); }

function openTaskModal(section) {
  currentAddSection = section;
  $("newTitle").value = ""; $("newInstruction").value = ""; $("newExample").value = "";
  openModal("taskModal");
  $("newTitle").focus();
}

function createCustomTask() {
  const title = $("newTitle").value.trim();
  if (!title) { toast("Додай назву задачі"); return; }
  api("/api/custom-tasks", {
    body: JSON.stringify({
      section: currentAddSection,
      title,
      instruction: $("newInstruction").value.trim(),
      example: $("newExample").value.trim(),
    }),
  })
    .then(created => reloadState().then(() => created))
    .then(created => {
      closeModal("taskModal");
      render();
      setTimeout(() => document.querySelector(`[data-task-id="${created.key}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
      toast("Власне завдання додано");
    })
    .catch(e => toast("Помилка: " + e.message));
}

function changePassword() {
  const err = $("pwError");
  err.textContent = "";
  const current = $("pwCurrent").value;
  const next = $("pwNew").value;
  if (next.length < 8) { err.textContent = "Новий пароль — мінімум 8 символів."; return; }
  if (next !== $("pwNew2").value) { err.textContent = "Нові паролі не співпадають."; return; }
  api("/api/password", { body: JSON.stringify({ current_password: current, new_password: next }) })
    .then(() => {
      ["pwCurrent", "pwNew", "pwNew2"].forEach(id => { $(id).value = ""; });
      closeModal("pwModal");
      toast("Пароль змінено");
    })
    .catch(e => { err.textContent = e.message === "unauthorized" ? "" : "Поточний пароль невірний."; });
}

// --- import / reset ------------------------------------------------------------------

function importData(file) {
  const fd = new FormData();
  fd.append("file", file);
  api("/api/import", { body: fd })
    .then(data => { state = data; render(); toast("Дані імпортовано"); })
    .catch(e => toast("Не вдалося імпортувати: " + e.message));
}

function resetAll() {
  if (!confirm("Стерти всі введені дані на сервері та повернути чистий workspace?")) return;
  api("/api/reset", { body: JSON.stringify({}) })
    .then(reloadState)
    .then(() => { render(); toast("Workspace очищено"); })
    .catch(e => toast("Помилка: " + e.message));
}

// --- event wiring ----------------------------------------------------------------------

function bindEvents() {
  const app = $("app");

  app.addEventListener("click", e => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const taskEl = btn.closest("[data-task-id]");
    const taskId = taskEl ? taskEl.dataset.taskId : null;
    switch (btn.dataset.action) {
      case "status": setStatus(taskId, btn.dataset.status, taskEl); break;
      case "confidence": setConfidence(taskId, btn.dataset.confidence, taskEl); break;
      case "add-evidence": addEvidence(taskId, taskEl); break;
      case "del-evidence": deleteEvidence(taskEl, btn.dataset.evidenceId); break;
      case "add-task": openTaskModal(+btn.dataset.section); break;
      case "del-task": deleteCustomTask(+btn.dataset.taskNum); break;
    }
  });

  app.addEventListener("input", e => {
    const el = e.target;
    if (el.matches(".answer")) {
      const id = el.dataset.answer;
      taskState(id).answer = el.value;
      saveTask(id, { answer: el.value });
    } else if (el.matches(".source")) {
      const id = el.dataset.source;
      taskState(id).source = el.value;
      saveTask(id, { source: el.value });
    } else if (el.matches("[data-ev-input]")) {
      const evId = el.dataset.evidenceId;
      const taskId = el.closest("[data-task-id]").dataset.taskId;
      const ev = taskState(taskId).evidence.find(v => v.id === +evId);
      if (ev) ev.value = el.value;
      debounce(`ev-${evId}`, () =>
        api(`/api/evidence/${evId}`, { method: "PATCH", body: JSON.stringify({ value: el.value }) })
          .then(() => markSaved(taskId))
          .catch(err => toast("Помилка збереження: " + err.message)));
    } else if (el.matches("[data-section-note]")) {
      const num = el.dataset.sectionNote;
      state.sections[num] = Object.assign({ note: "", key_number: "" }, state.sections[num], { note: el.value });
      debounce(`sec-${num}`, () =>
        api(`/api/sections/${num}`, { method: "PATCH", body: JSON.stringify({ note: el.value }) }).catch(err => toast("Помилка збереження: " + err.message)));
    } else if (el.matches("[data-section-number]")) {
      const num = el.dataset.sectionNumber;
      state.sections[num] = Object.assign({ note: "", key_number: "" }, state.sections[num], { key_number: el.value });
      debounce(`secn-${num}`, () =>
        api(`/api/sections/${num}`, { method: "PATCH", body: JSON.stringify({ key_number: el.value }) }).catch(err => toast("Помилка збереження: " + err.message)));
    }
  });

  $("search").addEventListener("input", e => filterTasks(e.target.value));
  $("toTop").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  $("printBtn").addEventListener("click", () => window.print());
  $("importFile").addEventListener("change", e => { const f = e.target.files[0]; if (f) importData(f); e.target.value = ""; });

  // task modal
  $("taskModalSave").addEventListener("click", createCustomTask);
  $("taskModalCancel").addEventListener("click", () => closeModal("taskModal"));
  $("taskModalClose").addEventListener("click", () => closeModal("taskModal"));

  // password modal + user menu
  $("changePwBtn").addEventListener("click", () => { $("pwError").textContent = ""; openModal("pwModal"); $("pwCurrent").focus(); });
  $("pwSave").addEventListener("click", changePassword);
  $("pwCancel").addEventListener("click", () => closeModal("pwModal"));

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeModal("taskModal"); closeModal("pwModal"); $("userMenu").removeAttribute("open"); }
  });
  document.addEventListener("click", e => {
    if (!$("userMenu").contains(e.target)) $("userMenu").removeAttribute("open");
  });
}

// --- boot -----------------------------------------------------------------------------

fetch("/static/content.json")
  .then(r => { if (!r.ok) throw new Error("content: " + r.status); return r.json(); })
  .then(content => { C = content; return reloadState(); })
  .then(() => { render(); bindEvents(); })
  .catch(e => { if (e.message !== "unauthorized") { document.body.insertAdjacentHTML("beforeend", `<div class="toast show">Не вдалося завантажити дані: ${esc(e.message)}</div>`); } });
})();
