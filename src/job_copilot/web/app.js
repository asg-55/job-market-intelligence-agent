const state = {
  profile: null,
  resumes: [],
  vacancies: [],
  capabilities: {},
  analytics: null,
  activeVacancy: null,
  lastAdvice: null,
};
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const split = (v) =>
  v
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        c
      ],
  );
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      detail = Array.isArray(body.detail)
        ? body.detail.map((x) => x.msg).join(", ")
        : body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(el.timer);
  el.timer = setTimeout(() => (el.className = "toast"), 2600);
}
function show(view) {
  $$(".view").forEach((x) =>
    x.classList.toggle("active", x.id === `view-${view}`),
  );
  $$(".nav-item").forEach((x) =>
    x.classList.toggle("active", x.dataset.view === view),
  );
  const titles = {
    overview: "Добрый день",
    profile: "Профиль кандидата",
    resumes: "Библиотека резюме",
    searches: "Стратегия поиска",
    vacancies: "Вакансии",
  };
  $("#page-title").textContent = titles[view];
  location.hash = view;
}
$$(".nav-item").forEach((x) => (x.onclick = () => show(x.dataset.view)));
$$("[data-go]").forEach((x) => (x.onclick = () => show(x.dataset.go)));
async function load() {
  try {
    const [profile, resumes, vacancies, capabilities, analytics] =
      await Promise.all([
        api("/profile"),
        api("/resumes"),
        api("/vacancies?limit=100"),
        api("/capabilities"),
        api("/analytics/overview"),
      ]);
    state.profile = profile.profile;
    state.resumes = resumes;
    state.vacancies = vacancies;
    state.capabilities = capabilities;
    state.analytics = analytics;
    renderAll();
  } catch (e) {
    toast(e.message, true);
  }
}
function renderAll() {
  renderMetrics();
  renderProfile();
  renderResumes();
  renderSearches();
  renderVacancies();
  renderAnalytics();
}
function renderMetrics() {
  $("#metric-resumes").textContent = state.resumes.length;
  $("#metric-searches").textContent =
    (state.profile.search_profiles || []).filter((x) => x.enabled).length ||
    state.profile.searches.length;
  $("#metric-vacancies").textContent =
    state.analytics?.total_vacancies ?? state.vacancies.length;
}
async function refreshAnalytics() {
  state.analytics = await api("/analytics/overview");
  renderAnalytics();
  renderMetrics();
}
const sourceLabels = {
  hh: "HH",
  remotive: "Remotive",
  superjob: "SuperJob",
  jooble: "Jooble",
  linkedin: "LinkedIn",
  manual: "Ручной импорт",
  other: "Другой источник",
};
const sourceStatusLabels = {
  ok: "Работает",
  captcha: "Требуется CAPTCHA",
  authorization: "Нужен ключ",
  forbidden: "Ожидает доступ",
  unavailable: "Недоступен",
  rate_limit: "Лимит запросов",
  partial: "Частично",
};
function sourceState(source, lastRun, integrations) {
  const status = lastRun?.summary?.sources?.[source]?.status;
  if (status)
    return {
      label: sourceStatusLabels[status] || status,
      kind: status === "ok" ? "ready" : "waiting",
    };
  const integration = integrations?.[source] || {};
  if (source === "linkedin") return { label: "Ручной импорт", kind: "manual" };
  if (source === "hh" && !integration.authenticated)
    return { label: "Заявка / токен", kind: "waiting" };
  return integration.enabled
    ? { label: "Готов", kind: "ready" }
    : { label: "Нужен ключ", kind: "waiting" };
}
function renderAnalytics() {
  const data = state.analytics;
  if (!data) return;
  const sourceRoot = $("#source-health");
  const lastRun = data.recent_runs?.[0];
  const names = [
    ...new Set([
      "hh",
      "remotive",
      "superjob",
      "jooble",
      "linkedin",
      ...Object.keys(data.source_counts || {}),
    ]),
  ];
  const maxSource = Math.max(1, ...Object.values(data.source_counts || {}));
  sourceRoot.innerHTML = names
    .map((source) => {
      const count = data.source_counts?.[source] || 0;
      const status = sourceState(source, lastRun, data.integrations);
      return `<div class="source-row"><div class="source-meta"><b>${esc(sourceLabels[source] || source)}</b><span class="source-state ${status.kind}">${esc(status.label)}</span></div><div class="bar-track"><i style="width:${Math.round((count / maxSource) * 100)}%"></i></div><strong>${count}</strong></div>`;
    })
    .join("");
  const bucketLabels = {
    under_40: "до 39%",
    "40_64": "40–64%",
    "65_79": "65–79%",
    "80_plus": "80% и выше",
  };
  const maxBucket = Math.max(1, ...Object.values(data.score_buckets || {}));
  $("#score-distribution").innerHTML = Object.entries(bucketLabels)
    .map(([key, label]) => {
      const count = data.score_buckets?.[key] || 0;
      return `<div class="distribution-row"><span>${label}</span><div class="bar-track"><i style="width:${Math.round((count / maxBucket) * 100)}%"></i></div><strong>${count}</strong></div>`;
    })
    .join("");
  $("#analytics-passed").textContent =
    `Прошли фильтры: ${data.passed_filters || 0}`;
  const history = $("#run-history");
  history.innerHTML = data.recent_runs?.length
    ? data.recent_runs
        .map((run) => {
          const summary = run.summary || {};
          const when = new Date(
            `${run.created_at.replace(" ", "T")}Z`,
          ).toLocaleString("ru-RU", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          });
          const trigger =
            {
              manual: "Вручную",
              automation: "n8n",
              cli: "CLI",
              scheduler: "Расписание",
            }[run.trigger] || run.trigger;
          return `<div class="run-row"><div><b>${esc(trigger)}</b><small>${esc(when)}</small></div><span>Найдено <b>${summary.found || 0}</b></span><span>Новых <b>${summary.new || 0}</b></span><span>Отправлено <b>${summary.notified || 0}</b></span><span class="run-status ${summary.source_status === "ok" ? "ready" : "waiting"}">${esc(sourceStatusLabels[summary.source_status] || summary.source_status || "Завершён")}</span></div>`;
        })
        .join("")
    : '<div class="empty compact">История появится после первого запуска мониторинга.</div>';
}
function renderProfile() {
  const p = state.profile;
  $("#profile-name").value = p.name || "";
  $("#profile-roles").value = (p.target_roles || []).join(", ");
  $("#profile-skills").value = (p.skills || []).join(", ");
  $("#profile-salary").value = p.minimum_salary || "";
  $("#profile-remote").checked = p.remote_only;
  $("#profile-preferences").value = p.preferences || "";
  $("#profile-facts").value = (p.verified_facts || []).join("\n");
}
$("#profile-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const data = {
      name: $("#profile-name").value.trim(),
      target_roles: split($("#profile-roles").value),
      skills: split($("#profile-skills").value),
      minimum_salary: Number($("#profile-salary").value) || null,
      remote_only: $("#profile-remote").checked,
      preferences: $("#profile-preferences").value.trim(),
      verified_facts: split($("#profile-facts").value),
    };
    const result = await api("/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    state.profile = result.profile;
    renderMetrics();
    toast("Профиль сохранён");
  } catch (e) {
    toast(e.message, true);
  }
};
function renderResumes() {
  const root = $("#resume-list");
  if (!state.resumes.length) {
    root.innerHTML =
      '<div class="empty">Пока нет резюме. Добавьте первое — текст останется в локальной базе.</div>';
    return;
  }
  root.innerHTML = state.resumes
    .map(
      (r) =>
        `<article class="card"><div class="document-icon">▤</div><h3>${esc(r.name)}</h3><p>${r.target_roles.map((x) => `<span class="tag">${esc(x)}</span>`).join("") || "Роли не указаны"}</p><p>Версия ${r.version}${r.source_resume_id ? ` · рабочая копия #${r.source_resume_id}` : ""}</p><footer><button class="secondary edit-resume" data-id="${r.id}">Изменить</button><a class="secondary download-resume" href="/resumes/${r.id}/export.docx">DOCX</a><button class="secondary archive-resume" data-id="${r.id}">В архив</button></footer></article>`,
    )
    .join("");
  $$(".edit-resume").forEach(
    (x) => (x.onclick = () => openResume(Number(x.dataset.id))),
  );
  $$(".archive-resume").forEach(
    (x) => (x.onclick = () => archiveResume(Number(x.dataset.id))),
  );
}
async function openResume(id = null) {
  $("#resume-form").reset();
  $("#resume-id").value = id || "";
  $("#resume-dialog-title").textContent = id
    ? "Редактировать резюме"
    : "Новое резюме";
  if (id) {
    try {
      const r = await api(`/resumes/${id}`);
      $("#resume-name").value = r.name;
      $("#resume-roles").value = r.target_roles.join(", ");
      $("#resume-content").value = r.content;
    } catch (e) {
      return toast(e.message, true);
    }
  }
  $("#resume-dialog").showModal();
}
$("#add-resume").onclick = () => openResume();
$("#resume-form").onsubmit = async (e) => {
  e.preventDefault();
  if (e.submitter?.value === "cancel") return $("#resume-dialog").close();
  const id = $("#resume-id").value;
  const data = {
    name: $("#resume-name").value.trim(),
    target_roles: split($("#resume-roles").value),
    content: $("#resume-content").value.trim(),
  };
  try {
    await api(id ? `/resumes/${id}` : "/resumes", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(data),
    });
    state.resumes = await api("/resumes");
    $("#resume-dialog").close();
    renderResumes();
    renderSearches();
    renderMetrics();
    toast(id ? "Резюме обновлено" : "Резюме добавлено");
  } catch (e) {
    toast(e.message, true);
  }
};
async function archiveResume(id) {
  if (!confirm("Архивировать резюме? История сохранится.")) return;
  try {
    await api(`/resumes/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ archived: true }),
    });
    state.resumes = await api("/resumes");
    renderResumes();
    renderSearches();
    renderMetrics();
    toast("Резюме перемещено в архив");
  } catch (e) {
    toast(e.message, true);
  }
}
function searchTemplate(
  p = {
    key: "",
    name: "",
    enabled: true,
    resume_id: null,
    searches: [{ text: "", area: null, period: 3 }],
  },
) {
  return `<article class="search-card"><div class="search-head"><b>${esc(p.name || "Новое направление")}</b><button class="remove-link" type="button">Удалить</button></div><label><span>Ключ</span><input class="sp-key" value="${esc(p.key)}" placeholder="ai-product" /></label><label><span>Название</span><input class="sp-name" value="${esc(p.name)}" placeholder="AI Product" /></label><label><span>Предпочтительное резюме</span><select class="sp-resume"><option value="">Не выбрано</option>${state.resumes.map((r) => `<option value="${r.id}" ${r.id === p.resume_id ? "selected" : ""}>#${r.id} · ${esc(r.name)}</option>`).join("")}</select></label><label class="toggle"><input class="sp-enabled" type="checkbox" ${p.enabled ? "checked" : ""}/><span>Направление включено</span></label><label class="wide"><span>Поисковые запросы — по одному на строку</span><textarea class="sp-queries" rows="4">${esc((p.searches || []).map((x) => x.text).join("\n"))}</textarea></label></article>`;
}
function renderSearches() {
  const root = $("#search-list");
  const profiles = state.profile.search_profiles || [];
  root.innerHTML = profiles.length
    ? profiles.map(searchTemplate).join("")
    : '<div class="empty">Добавьте первое направление поиска.</div>';
  wireSearchRemove();
}
function wireSearchRemove() {
  $$(".remove-link").forEach(
    (x) =>
      (x.onclick = () => {
        x.closest(".search-card").remove();
        if (!$("#search-list").children.length)
          $("#search-list").innerHTML =
            '<div class="empty">Добавьте первое направление поиска.</div>';
      }),
  );
}
$("#add-search").onclick = () => {
  if ($("#search-list .empty")) $("#search-list").innerHTML = "";
  $("#search-list").insertAdjacentHTML("beforeend", searchTemplate());
  wireSearchRemove();
};
$("#save-searches").onclick = async () => {
  const profiles = $$(".search-card").map((card) => ({
    key: $(".sp-key", card).value.trim(),
    name: $(".sp-name", card).value.trim(),
    enabled: $(".sp-enabled", card).checked,
    resume_id: Number($(".sp-resume", card).value) || null,
    searches: split($(".sp-queries", card).value).map((text) => ({
      text,
      area: null,
      period: 3,
    })),
  }));
  try {
    const result = await api("/profile", {
      method: "PATCH",
      body: JSON.stringify({ search_profiles: profiles }),
    });
    state.profile = result.profile;
    renderSearches();
    renderMetrics();
    toast("Направления сохранены");
  } catch (e) {
    toast(e.message, true);
  }
};
const feedbackLabels = {
  fit: "Подходит",
  skip: "Пропущена",
  applied: "Отклик отправлен",
  interview: "Собеседование",
  rejected: "Отказ",
};
function renderVacancies() {
  const root = $("#vacancy-list");
  if (!state.vacancies.length) {
    root.innerHTML =
      '<div class="empty">Вакансий пока нет. Нажмите «Запустить поиск» — лучшие варианты появятся здесь.</div>';
    return;
  }
  root.innerHTML = state.vacancies
    .map(
      (v) =>
        `<article class="vacancy-card" data-vacancy-id="${esc(v.id)}" tabindex="0"><div class="score" style="--score:${v.score}"><b>${v.score}%</b></div><div><div class="vacancy-title-row"><h3>${esc(v.name)}</h3>${v.feedback_action ? `<span class="status-tag status-${esc(v.feedback_action)}">${esc(feedbackLabels[v.feedback_action] || v.feedback_action)}</span>` : ""}</div><p>${esc(v.employer)} · ${esc((v.source || "hh").toUpperCase())} · ${(v.search_profiles || []).map((x) => `${esc(x.name)}${x.resume_id ? ` · резюме #${x.resume_id}` : ""}`).join(" / ") || "Общий поиск"}</p><small>${esc(v.result?.explanation || "Откройте карточку, чтобы увидеть подробности")}</small></div><button class="secondary vacancy-open" data-id="${esc(v.id)}">Подробнее</button></article>`,
    )
    .join("");
  $$(".vacancy-open").forEach(
    (x) =>
      (x.onclick = (e) => {
        e.stopPropagation();
        openVacancy(x.dataset.id);
      }),
  );
  $$(".vacancy-card").forEach((x) => {
    x.onclick = () => openVacancy(x.dataset.vacancyId);
    x.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openVacancy(x.dataset.vacancyId);
      }
    };
  });
}
$("#refresh-vacancies").onclick = async () => {
  try {
    state.vacancies = await api("/vacancies?limit=100");
    renderVacancies();
    renderMetrics();
    toast("Список обновлён");
  } catch (e) {
    toast(e.message, true);
  }
};
const vacancyImportDialog = $("#vacancy-import-dialog");
$("#import-vacancy").onclick = () => vacancyImportDialog.showModal();
$("#close-vacancy-import").onclick = $("#cancel-vacancy-import").onclick = () =>
  vacancyImportDialog.close();
$("#vacancy-import-form").onsubmit = async (event) => {
  event.preventDefault();
  const submit =
    event.submitter || $('#vacancy-import-form button[type="submit"]');
  submit.disabled = true;
  submit.textContent = "Оцениваю…";
  try {
    const payload = {
      source: $("#import-source").value,
      name: $("#import-name").value.trim(),
      employer: $("#import-employer").value.trim(),
      url: $("#import-url").value.trim(),
      description: $("#import-description").value.trim(),
      remote: $("#import-remote").checked,
      key_skills: split($("#import-skills").value),
    };
    const imported = await api("/vacancies/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.vacancies = await api("/vacancies?limit=100");
    await refreshAnalytics();
    renderVacancies();
    vacancyImportDialog.close();
    event.target.reset();
    toast(`Вакансия сохранена · совпадение ${imported.result.total_score}%`);
    openVacancy(imported.vacancy.id);
  } catch (e) {
    toast(e.message, true);
  } finally {
    submit.disabled = false;
    submit.textContent = "Сохранить и оценить";
  }
};
$("#run-monitor").onclick = async () => {
  const button = $("#run-monitor");
  button.disabled = true;
  button.textContent = "Ищу…";
  try {
    const result = await api("/monitor/run", { method: "POST" });
    state.vacancies = await api("/vacancies?limit=100");
    await refreshAnalytics();
    renderVacancies();
    if (result.source_status !== "ok")
      toast(result.source_message || "Источники частично недоступны", true);
    else
      toast(
        `Поиск завершён: новых — ${result.new}, уведомлений — ${result.notified}`,
      );
  } catch (e) {
    toast(friendlyError(e).message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Запустить поиск";
  }
};
function recommendedResume(v) {
  return (
    (v.search_profiles || []).find((x) => x.resume_id)?.resume_id ||
    state.resumes[0]?.id ||
    null
  );
}
function chips(values, empty) {
  return values?.length
    ? values.map((x) => `<span>${esc(x)}</span>`).join("")
    : `<small>${empty}</small>`;
}
function openVacancy(id) {
  const v = state.vacancies.find((x) => String(x.id) === String(id));
  if (!v) return;
  state.activeVacancy = v;
  $("#workspace-title").textContent = v.name;
  $("#workspace-company").textContent = v.employer;
  $("#workspace-score").textContent = `${v.score}%`;
  $("#workspace-explanation").textContent =
    v.result?.explanation || "Подробное объяснение пока недоступно";
  $("#workspace-matched").innerHTML = chips(
    v.result?.matched_skills,
    "Явных совпадений пока нет",
  );
  $("#workspace-missing").innerHTML = chips(
    v.result?.missing_skills,
    "Критичных пробелов не найдено",
  );
  $("#workspace-link").href = v.url;
  $("#workspace-resume").innerHTML = state.resumes.length
    ? state.resumes
        .map(
          (r) =>
            `<option value="${r.id}" ${r.id === recommendedResume(v) ? "selected" : ""}>#${r.id} · ${esc(r.name)} · v${r.version}</option>`,
        )
        .join("")
    : '<option value="">Сначала добавьте резюме</option>';
  $("#llm-state").textContent = state.capabilities.llm
    ? "LLM подключена"
    : "LLM не подключена";
  $("#llm-state").className = state.capabilities.llm ? "ready" : "offline";
  $("#assistant-output").innerHTML = state.capabilities.llm
    ? "<p>Выберите действие — AI подготовит аудируемый черновик.</p>"
    : "<p><b>AI-функции пока выключены.</b><br>Подключите локальную Ollama по инструкции проекта. Оценка и статусы вакансии уже работают без неё.</p>";
  $$("#feedback-actions button").forEach((x) =>
    x.classList.toggle("active", x.dataset.action === v.feedback_action),
  );
  $("#vacancy-dialog").showModal();
}
$("#close-workspace").onclick = () => {
  state.lastAdvice = null;
  $("#create-adapted-copy").hidden = true;
  $("#vacancy-dialog").close();
};
$$("#feedback-actions button").forEach(
  (button) =>
    (button.onclick = async () => {
      if (!state.activeVacancy) return;
      try {
        await api(`/vacancies/${state.activeVacancy.id}/feedback`, {
          method: "POST",
          body: JSON.stringify({ action: button.dataset.action }),
        });
        state.activeVacancy.feedback_action = button.dataset.action;
        $$("#feedback-actions button").forEach((x) =>
          x.classList.toggle("active", x === button),
        );
        renderVacancies();
        await refreshAnalytics();
        toast(`Статус: ${feedbackLabels[button.dataset.action]}`);
      } catch (e) {
        toast(e.message, true);
      }
    }),
);
function friendlyError(error) {
  if (/Configure LLM_MODEL/i.test(error.message))
    return new Error("Сначала подключите локальную LLM в настройках проекта");
  if (/verified fact/i.test(error.message))
    return new Error("Добавьте подтверждённые факты в разделе «Мой профиль»");
  return error;
}
async function withBusy(button, label, action) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await action();
  } catch (e) {
    const friendly = friendlyError(e);
    toast(friendly.message, true);
    $("#assistant-output").innerHTML =
      `<p><b>Не удалось выполнить действие.</b><br>${esc(friendly.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}
$("#generate-letter").onclick = () =>
  withBusy($("#generate-letter"), "Готовлю…", async () => {
    const v = state.activeVacancy;
    if (!v) return;
    const draft = await api(`/vacancies/${v.id}/cover-letter`, {
      method: "POST",
      body: JSON.stringify({ language: "ru", tone: "professional" }),
    });
    $("#assistant-output").innerHTML =
      `<div class="result-head"><b>Черновик письма</b><button class="copy-result" type="button">Копировать</button></div><pre>${esc(draft.text)}</pre><small>Черновик #${draft.id}. Проверьте текст перед отправкой.</small>`;
    $(".copy-result").onclick = () => copyResult(draft.text);
    toast("Черновик письма готов");
  });
$("#generate-advice").onclick = () =>
  withBusy($("#generate-advice"), "Анализирую…", async () => {
    const v = state.activeVacancy;
    const resumeId = Number($("#workspace-resume").value);
    if (!v || !resumeId) throw new Error("Сначала добавьте и выберите резюме");
    const advice = await api(`/vacancies/${v.id}/resume-advice`, {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId, language: "ru" }),
    });
    state.lastAdvice = advice;
    $("#create-adapted-copy").hidden = false;
    const r = advice.result;
    const bullets = (r.fact_backed_bullets || [])
      .map((x) => `<li><b>${esc(x.section)}</b> — ${esc(x.text)}</li>`)
      .join("");
    const changes = (r.presentation_changes || [])
      .map(
        (x) => `<li>${esc(x.instruction)} <small>${esc(x.reason)}</small></li>`,
      )
      .join("");
    $("#assistant-output").innerHTML =
      `<div class="result-head"><b>Рекомендации к копии резюме</b><span>#${advice.id}</span></div>${bullets ? `<h5>Подтверждённые формулировки</h5><ul>${bullets}</ul>` : ""}${changes ? `<h5>Структура</h5><ul>${changes}</ul>` : ""}<h5>Подчеркнуть</h5><div class="chip-list">${chips(r.skills_to_emphasize, "Нет дополнительных акцентов")}</div><h5>Честные пробелы</h5><ul>${(r.honest_gaps || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>Не обнаружены</li>"}</ul><small>Оригинал резюме не изменён.</small>`;
    toast("Рекомендации готовы");
  });
async function copyResult(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано");
  } catch {
    toast("Не удалось скопировать автоматически", true);
  }
}
$("#create-adapted-copy").onclick = () =>
  withBusy($("#create-adapted-copy"), "Создаю…", async () => {
    const v = state.activeVacancy;
    const advice = state.lastAdvice;
    if (!v || !advice || advice.vacancy_id !== v.id)
      throw new Error("Сначала получите рекомендации по этой вакансии");
    const copy = await api(`/vacancies/${v.id}/adapted-resume`, {
      method: "POST",
      body: JSON.stringify({
        resume_id: advice.resume_id,
        advice_id: advice.id,
      }),
    });
    state.resumes = await api("/resumes");
    renderResumes();
    renderSearches();
    renderMetrics();
    state.lastAdvice = null;
    $("#create-adapted-copy").hidden = true;
    toast(`Рабочая копия #${copy.id} создана`);
    $("#vacancy-dialog").close();
    show("resumes");
    await openResume(copy.id);
  });
show((location.hash || "#overview").slice(1));
load();
