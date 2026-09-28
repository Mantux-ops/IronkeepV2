(function () {
  const data = Ik.pageData();
  if (!data || !document.getElementById("trial-rows")) return;

  const { settings, roles, channels, guild, viewer, today } = data;
  const trials = data.trials;
  const esc = Ik.escape;

  const CATEGORIES = ["Attendance", "Group fit", "Behaviour", "Skill", "Communication", "Other"];
  const RATINGS = {
    positive: { label: "Positive", tone: "green", sign: "+" },
    neutral: { label: "Neutral", tone: "grey", sign: "○" },
    negative: { label: "Negative", tone: "red", sign: "−" },
  };

  const STATUS = {
    action_failed: { label: "Action failed", tone: "red", group: "attention", rank: 0 },
    no_content: { label: "No content role", tone: "red", group: "attention", rank: 1 },
    lost_content: { label: "Lost content role", tone: "red", group: "attention", rank: 2 },
    no_start: { label: "No start date", tone: "orange", group: "attention", rank: 3 },
    verdict_due: { label: "Verdict due", tone: "orange", group: "verdict", rank: 4 },
    ending_soon: { label: "Ending soon", tone: "orange", group: "ending", rank: 5 },
    active: { label: "Active", tone: "green", group: "active", rank: 6 },
    left: { label: "Left server", tone: "grey", group: "closed", rank: 7 },
    accepted: { label: "Accepted", tone: "green", group: "closed", rank: 8 },
    rejected: { label: "Rejected", tone: "grey", group: "closed", rank: 9 },
  };

  const FILTERS = [
    { key: "open", label: "All open", match: (s) => STATUS[s].group !== "closed" },
    { key: "attention", label: "Needs attention", match: (s) => STATUS[s].group === "attention" },
    { key: "ending", label: "Ending soon", match: (s) => STATUS[s].group === "ending" },
    { key: "verdict", label: "Verdict due", match: (s) => STATUS[s].group === "verdict" },
    { key: "closed", label: "Closed", match: (s) => STATUS[s].group === "closed" },
  ];

  const state = { filter: "open", search: "", sort: { key: "status", dir: 1 }, selected: null, editing: null, tab: "notes", formOpen: false };

  const roleById = (id) => roles.find((r) => r.id === id);
  const channelById = (id) => channels.find((c) => c.id === id);
  const trialById = (id) => trials.find((t) => t.id === id);

  const length = (t) => settings.trial_days + t.extra_days;
  const endDate = (t) => (t.start ? Ik.addDays(t.start, length(t)) : null);
  const dayOf = (t) => (t.start ? Ik.daysBetween(t.start, today) + 1 : null);

  function statusOf(t) {
    if (t.verdict) return t.verdict;
    if (t.action_error) return "action_failed";
    if (t.left_server) return "left";
    if (!t.start) return "no_start";
    const day = dayOf(t);
    const daysLeft = length(t) - day;
    if (day > length(t)) return "verdict_due";
    if (!t.content_roles.length) {
      if (t.lost_content_role) return "lost_content";
      if (day >= settings.reminder_day) return "no_content";
    }
    if (daysLeft <= 2) return "ending_soon";
    return "active";
  }

  function reasonOf(t) {
    const s = statusOf(t);
    const day = dayOf(t);
    switch (s) {
      case "no_content":
        return `Day ${day} · no content role${t.ping_sent_at ? " · reminder sent" : ""}`;
      case "lost_content":
        return "Content role removed after reminder";
      case "no_start":
        return "No start date";
      case "verdict_due":
        return `Trial ended ${Ik.formatDate(endDate(t))}`;
      case "ending_soon": {
        const left = length(t) - day + 1;
        return left === 1 ? "Ends tomorrow" : `Ends in ${left} days`;
      }
      case "action_failed":
        return "Role change failed";
      default:
        return STATUS[s].label;
    }
  }

  function log(t, text, type = "system") {
    t.timeline.push({ type, at: Ik.nowIso(today), text });
  }

  function roleNames(ids) {
    return ids.map((id) => roleById(id)).filter(Boolean).map((r) => Ik.roleLabel(r, roles));
  }

  function progressBar(t) {
    if (!t.start) return '<span class="muted">—</span>';
    const day = Math.min(dayOf(t), length(t));
    const pct = Math.max(4, Math.round((day / length(t)) * 100));
    const s = statusOf(t);
    const tone = STATUS[s].tone === "red" ? "red" : STATUS[s].tone === "orange" ? "orange" : "accent";
    const label = dayOf(t) > length(t) ? `Ended · ${length(t)} days` : `Day ${day} of ${length(t)}`;
    return `<div class="progress progress--${tone}"><span class="progress__bar"><span style="width:${pct}%"></span></span><span class="progress__label">${label}</span></div>`;
  }

  function contentChips(t) {
    if (!t.content_roles.length) return '<span class="muted">—</span>';
    return t.content_roles.map((id) => Ik.roleChip(roleById(id), roles)).join("");
  }

  function renderStats() {
    const counts = { attention: 0, ending: 0, verdict: 0, open: 0 };
    trials.forEach((t) => {
      const group = STATUS[statusOf(t)].group;
      if (group !== "closed") counts.open += 1;
      if (group in counts) counts[group] += 1;
    });
    const cards = [
      { key: "attention", label: "Needs attention", icon: "alert", tone: "red" },
      { key: "ending", label: "Ending soon", icon: "clock", tone: "orange" },
      { key: "verdict", label: "Verdict due", icon: "gavel", tone: "orange" },
      { key: "open", label: "Open trials", icon: "users", tone: "accent" },
    ];
    document.getElementById("stats").innerHTML = cards
      .map(
        (c) => `<button class="stat-card stat-card--${c.tone} ${state.filter === c.key ? "is-selected" : ""}" type="button" data-filter="${c.key}">
          <span class="stat-card__icon">${Ik.icon(c.icon, 22)}</span>
          <span class="stat-card__body"><span class="stat-card__label">${c.label}</span><span class="stat-card__value">${counts[c.key]}</span></span>
        </button>`
      )
      .join("");
  }

  function actionButton(t) {
    const s = statusOf(t);
    const map = {
      no_start: ["set-start", "Set start date"],
      verdict_due: ["open", "Give verdict"],
      action_failed: ["retry", "Retry"],
    };
    const [action, label] = map[s] || ["open", "View"];
    return `<button class="button button--outline button--sm" type="button" data-action="${action}" data-id="${t.id}">${label} ${Ik.icon("arrow-right", 14)}</button>`;
  }

  function renderActionList() {
    const items = trials
      .filter((t) => ["attention", "verdict", "ending"].includes(STATUS[statusOf(t)].group))
      .sort((a, b) => STATUS[statusOf(a)].rank - STATUS[statusOf(b)].rank);
    const root = document.getElementById("action-list");
    if (!items.length) {
      root.innerHTML = `<div class="action-list__empty">${Ik.icon("check")} Nothing needs action right now.</div>`;
      return;
    }
    root.innerHTML = items
      .map((t) => {
        const s = statusOf(t);
        return `<div class="action-row" data-open="${t.id}">
          ${Ik.avatar(t.name, t.color)}
          <span class="action-row__name">${esc(t.name)}</span>
          <span class="tag tag--${STATUS[s].tone}">${esc(reasonOf(t))}</span>
          <span class="action-row__spacer"></span>
          ${actionButton(t)}
        </div>`;
      })
      .join("");
  }

  function renderFilters() {
    document.getElementById("filters").innerHTML = FILTERS.map((f) => {
      const count = trials.filter((t) => f.match(statusOf(t))).length;
      return `<button class="chip ${state.filter === f.key ? "is-active" : ""}" type="button" role="tab" data-filter="${f.key}">${f.label}<span class="chip__count">${count}</span></button>`;
    }).join("");
  }

  function sortValue(t, key) {
    switch (key) {
      case "name":
        return t.name.toLowerCase();
      case "start":
        return t.start || "0000";
      case "end":
        return endDate(t) || "0000";
      case "progress":
        return t.start ? dayOf(t) / length(t) : -1;
      default:
        return STATUS[statusOf(t)].rank;
    }
  }

  function renderTable() {
    const filter = FILTERS.find((f) => f.key === state.filter);
    const query = state.search.trim().toLowerCase();
    const rows = trials
      .filter((t) => filter.match(statusOf(t)))
      .filter((t) => !query || t.name.toLowerCase().includes(query) || t.username.toLowerCase().includes(query))
      .sort((a, b) => {
        const va = sortValue(a, state.sort.key);
        const vb = sortValue(b, state.sort.key);
        return (va > vb ? 1 : va < vb ? -1 : 0) * state.sort.dir;
      });

    document.getElementById("trial-rows").innerHTML = rows
      .map((t) => {
        const s = statusOf(t);
        const extended = t.extra_days ? `<span class="tag tag--accent tag--xs">+${t.extra_days}d</span>` : "";
        return `<tr class="${state.selected === t.id ? "is-selected" : ""}" data-open="${t.id}" tabindex="0">
          <td data-label="Name"><span class="cell-user">${Ik.avatar(t.name, t.color, "sm")}<span><span class="cell-user__name">${esc(t.name)}</span><span class="cell-user__sub">@${esc(t.username)}</span></span></span></td>
          <td data-label="Start">${Ik.formatDate(t.start)}</td>
          <td data-label="Ends">${Ik.formatDate(endDate(t))} ${extended}</td>
          <td data-label="Progress">${progressBar(t)}</td>
          <td data-label="Content role"><span class="chips">${contentChips(t)}</span></td>
          <td data-label="Status">${Ik.pill(STATUS[s].label, STATUS[s].tone)}</td>
        </tr>`;
      })
      .join("");
    document.getElementById("table-empty").hidden = rows.length > 0;

    document.querySelectorAll("th[data-sort]").forEach((th) => {
      th.classList.toggle("is-sorted", th.dataset.sort === state.sort.key);
      th.dataset.dir = th.dataset.sort === state.sort.key ? (state.sort.dir > 0 ? "asc" : "desc") : "";
    });
  }

  function observationSummary(t) {
    const summary = {};
    t.timeline
      .filter((e) => e.type === "observation")
      .forEach((e) => {
        summary[e.category] = summary[e.category] || { positive: 0, neutral: 0, negative: 0 };
        summary[e.category][e.rating] += 1;
      });
    const cats = CATEGORIES.filter((c) => summary[c]);
    if (!cats.length) return '<p class="muted small">No observations yet.</p>';
    return `<div class="assessment">${cats
      .map(
        (c) => `<div class="assessment__row"><span class="assessment__cat">${c}</span>
          <span class="assessment__counts">
            ${summary[c].positive ? `<span class="count count--green">+${summary[c].positive}</span>` : ""}
            ${summary[c].neutral ? `<span class="count count--grey">○${summary[c].neutral}</span>` : ""}
            ${summary[c].negative ? `<span class="count count--red">−${summary[c].negative}</span>` : ""}
          </span></div>`
      )
      .join("")}</div>`;
  }

  function timelineIcon(e) {
    if (e.type === "observation") return RATINGS[e.rating].sign;
    if (e.type === "error") return Ik.icon("alert", 14);
    const text = e.text.toLowerCase();
    if (text.startsWith("joined")) return Ik.icon("user-plus", 14);
    if (text.includes("reminder")) return Ik.icon("bell", 14);
    if (text.includes("message")) return Ik.icon("message", 14);
    if (text.includes("accepted") || text.includes("rejected")) return Ik.icon("gavel", 14);
    if (text.includes("start date") || text.includes("extended") || text.includes("ended")) return Ik.icon("calendar", 14);
    if (text.includes("role")) return Ik.icon("tag", 14);
    return Ik.icon("info", 14);
  }

  function observationChips(t) {
    const summary = {};
    t.timeline
      .filter((e) => e.type === "observation")
      .forEach((e) => {
        summary[e.category] = summary[e.category] || { positive: 0, neutral: 0, negative: 0 };
        summary[e.category][e.rating] += 1;
      });
    const cats = CATEGORIES.filter((c) => summary[c]);
    if (!cats.length) return "";
    return `<div class="obs-chips">${cats
      .map((c) => {
        const n = summary[c];
        const counts = [
          n.positive ? `<span class="obs-chip__n obs-chip__n--green">+${n.positive}</span>` : "",
          n.neutral ? `<span class="obs-chip__n obs-chip__n--grey">○${n.neutral}</span>` : "",
          n.negative ? `<span class="obs-chip__n obs-chip__n--red">−${n.negative}</span>` : "",
        ].join("");
        return `<span class="obs-chip">${c}${counts}</span>`;
      })
      .join("")}</div>`;
  }

  function renderTimeline(t, filter = () => true) {
    const entries = t.timeline.map((e, index) => ({ ...e, index })).filter(filter).reverse();
    if (!entries.length) return "";
    return `<ol class="timeline">${entries
      .map((e) => {
        if (e.type === "observation") {
          const mine = e.author === viewer;
          const editing = state.editing === e.index;
          const body = editing
            ? `<textarea class="input textarea" rows="3" data-edit-text>${esc(e.text)}</textarea>
               <div class="timeline__edit-actions">
                 <button class="button button--ghost button--sm" type="button" data-action="cancel-edit">Cancel</button>
                 <button class="button button--accent button--sm" type="button" data-action="save-edit" data-index="${e.index}">Save</button>
               </div>`
            : `<p class="timeline__text">${esc(e.text)}</p>`;
          return `<li class="timeline__item timeline__item--obs timeline__item--${RATINGS[e.rating].tone}">
            <span class="timeline__marker">${timelineIcon(e)}</span>
            <div class="timeline__content">
              <div class="timeline__meta">
                <span class="timeline__author">${esc(e.author)}</span>
                <span class="tag tag--xs tag--${RATINGS[e.rating].tone}">${esc(e.category)} · ${RATINGS[e.rating].label}</span>
                <span class="timeline__time">${Ik.formatDateTime(e.at)}${e.edited ? " · edited" : ""}</span>
                ${mine && !editing ? `<span class="timeline__tools">
                  <button class="icon-button icon-button--sm" type="button" title="Edit" data-action="edit-obs" data-index="${e.index}">${Ik.icon("pencil", 13)}</button>
                  <button class="icon-button icon-button--sm" type="button" title="Delete" data-action="delete-obs" data-index="${e.index}">${Ik.icon("trash", 13)}</button>
                </span>` : ""}
              </div>
              ${body}
            </div>
          </li>`;
        }
        return `<li class="timeline__item ${e.type === "error" ? "timeline__item--error" : ""}">
          <span class="timeline__marker">${timelineIcon(e)}</span>
          <div class="timeline__content">
            <p class="timeline__text">${esc(e.text)}</p>
            <span class="timeline__time">${Ik.formatDateTime(e.at)}</span>
          </div>
        </li>`;
      })
      .join("")}</ol>`;
  }

  function renderPanel() {
    const panel = document.getElementById("panel");
    const overlay = document.getElementById("panel-overlay");
    const t = trialById(state.selected);
    if (!t) {
      panel.hidden = true;
      overlay.hidden = true;
      document.body.classList.remove("has-panel");
      return;
    }
    const s = statusOf(t);
    const closed = STATUS[s].group === "closed";
    const observations = t.timeline.filter((e) => e.type === "observation");
    const history = t.timeline.filter((e) => e.type !== "observation");
    const isObs = (e) => e.type === "observation";

    let when;
    if (!t.start) {
      when = `<div class="panel__nostart"><span class="muted">No start date yet. Day count and reminder are paused.</span>
        ${closed ? "" : `<button class="button button--outline button--sm" type="button" data-action="set-start" data-id="${t.id}">${Ik.icon("calendar", 14)} Set start date</button>`}</div>`;
    } else {
      const day = dayOf(t);
      const over = day > length(t);
      const pct = Math.max(4, Math.round((Math.min(day, length(t)) / length(t)) * 100));
      const tone = STATUS[s].tone === "red" ? "red" : STATUS[s].tone === "orange" ? "orange" : "accent";
      when = `<div class="progress progress--${tone}">
          <div class="panel__when"><strong>${over ? "Trial ended" : `Day ${day} of ${length(t)}`}</strong><span class="muted">${over ? Ik.formatDate(endDate(t)) : `ends ${Ik.formatDate(endDate(t))}`}</span></div>
          <span class="progress__bar"><span style="width:${pct}%"></span></span>
        </div>`;
    }

    const tab = state.tab;
    panel.innerHTML = `
      <header class="panel__header">
        ${Ik.avatar(t.name, t.color, "lg")}
        <div class="panel__title">
          <h2>${esc(t.name)}</h2>
          <div class="panel__subline">${Ik.pill(STATUS[s].label, STATUS[s].tone)}<span class="muted small">@${esc(t.username)}</span></div>
        </div>
        <button class="icon-button" type="button" data-action="close" title="Close">${Ik.icon("x", 18)}</button>
      </header>

      <div class="panel__scroll">
        ${t.action_error ? `<div class="callout callout--red">${Ik.icon("alert")}<div><strong>Role change failed.</strong><p>${esc(t.action_error)}</p></div><button class="button button--outline button--sm" type="button" data-action="retry" data-id="${t.id}">Retry</button></div>` : ""}

        <section class="panel__section panel__summary">
          ${when}
          <div class="chips">${t.content_roles.length ? contentChips(t) : '<span class="tag tag--red tag--xs">No content role</span>'}</div>
          ${closed
            ? `<p class="verdict-note">${Ik.icon("gavel", 14)} ${STATUS[s].label}${t.verdict_by ? ` by ${esc(t.verdict_by)}` : ""}${t.verdict_at ? ` on ${Ik.formatDate(t.verdict_at)}` : ""}.</p>`
            : `<div class="panel__actions">
                <button class="button button--green" type="button" data-action="accept" data-id="${t.id}">${Ik.icon("check", 15)} Accept</button>
                <button class="button button--red-outline" type="button" data-action="reject" data-id="${t.id}">${Ik.icon("x", 15)} Reject</button>
                <span class="panel__actions-spacer"></span>
                <div class="more" data-dropdown>
                  <button class="button button--ghost" type="button" data-dropdown-toggle title="More actions">More ${Ik.icon("chevron-down", 14)}</button>
                  <div class="dropdown dropdown--right" hidden>
                    <button class="dropdown__item" type="button" data-action="extend" data-id="${t.id}">${Ik.icon("calendar", 15)} Extend trial</button>
                    <button class="dropdown__item" type="button" data-action="set-start" data-id="${t.id}">${Ik.icon("clock", 15)} ${t.start ? "Change" : "Set"} start date</button>
                  </div>
                </div>
              </div>`}
        </section>

        <div class="tabs" role="tablist">
          <button class="tabs__tab ${tab === "notes" ? "is-active" : ""}" type="button" role="tab" data-tab="notes">Observations <span class="tabs__count">${observations.length}</span></button>
          <button class="tabs__tab ${tab === "history" ? "is-active" : ""}" type="button" role="tab" data-tab="history">History <span class="tabs__count">${history.length}</span></button>
        </div>

        ${tab === "notes"
          ? `<section class="panel__section">
              ${observationChips(t)}
              ${closed ? "" : state.formOpen
                ? `<form class="obs-form" data-obs-form>
                    <div class="obs-form__row">
                      <select class="input select" name="category" aria-label="Category">${CATEGORIES.map((c) => `<option>${c}</option>`).join("")}</select>
                      <div class="segmented" role="radiogroup" aria-label="Rating">
                        ${Object.entries(RATINGS).map(([key, r], i) => `<label class="segmented__opt segmented__opt--${r.tone}"><input type="radio" name="rating" value="${key}" ${i === 0 ? "checked" : ""}><span>${r.label}</span></label>`).join("")}
                      </div>
                    </div>
                    <textarea class="input textarea" name="text" rows="2" placeholder="What did you notice?" autofocus></textarea>
                    <div class="obs-form__footer">
                      <span class="muted small">Only recruiters see this.</span>
                      <span>
                        <button class="button button--ghost button--sm" type="button" data-action="close-form">Cancel</button>
                        <button class="button button--accent button--sm" type="submit">Add</button>
                      </span>
                    </div>
                  </form>`
                : `<button class="button button--outline button--sm obs-add" type="button" data-action="open-form">${Ik.icon("plus", 14)} Add observation</button>`}
              ${observations.length ? renderTimeline(t, isObs) : `<p class="muted small panel__empty">No observations yet.</p>`}
            </section>`
          : `<section class="panel__section">${renderTimeline(t, (e) => !isObs(e))}</section>`}
      </div>`;

    const textarea = panel.querySelector("[data-obs-form] textarea");
    if (textarea) textarea.focus();

    panel.hidden = false;
    overlay.hidden = false;
    document.body.classList.add("has-panel");
  }

  function renderAll() {
    renderStats();
    renderActionList();
    renderFilters();
    renderTable();
    renderPanel();
  }

  function openTrial(id) {
    if (state.selected !== id) {
      state.tab = "notes";
      state.formOpen = false;
    }
    state.selected = id;
    state.editing = null;
    renderAll();
  }

  function openStartModal(t) {
    Ik.openModal(
      `<header class="modal__header"><h2>${t.start ? "Change" : "Set"} start date for ${esc(t.name)}</h2></header>
       <div class="modal__body">
         <p class="muted">Discord doesn't record when a role was given, so trials that started before Ironkeep was installed need a start date once. The end date and the day-${settings.reminder_day} reminder are counted from this date.</p>
         <label class="field"><span class="field__label">Start date</span>
           <input class="input" type="date" name="start" value="${t.start || ""}" max="${today}" autofocus></label>
       </div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--accent" type="button" data-save>Save</button>
       </footer>`,
      {
        onMount(modal) {
          modal.querySelector("[data-save]").addEventListener("click", () => {
            const value = modal.querySelector("[name=start]").value;
            if (!value) return;
            const previous = t.start;
            t.start = value;
            log(t, previous ? `Start date changed from ${Ik.formatDate(previous)} to ${Ik.formatDate(value)} by ${viewer}` : `Start date set to ${Ik.formatDate(value)} by ${viewer}`);
            Ik.closeModal();
            Ik.toast(`Start date saved for ${t.name}`);
            renderAll();
          });
        },
      }
    );
  }

  function openExtendModal(t) {
    Ik.openModal(
      `<header class="modal__header"><h2>Extend ${esc(t.name)}'s trial</h2></header>
       <div class="modal__body">
         <div class="field-row">
           <label class="field"><span class="field__label">Extra days</span>
             <input class="input" type="number" name="days" min="1" max="60" value="7" autofocus></label>
           <div class="field"><span class="field__label">New end date</span><span class="field__value" data-new-end></span></div>
         </div>
         <label class="field"><span class="field__label">Reason <span class="muted">(optional, shown in the timeline)</span></span>
           <input class="input" type="text" name="reason" placeholder="e.g. was on holiday for a week"></label>
       </div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--accent" type="button" data-save>Extend trial</button>
       </footer>`,
      {
        onMount(modal) {
          const input = modal.querySelector("[name=days]");
          const out = modal.querySelector("[data-new-end]");
          const update = () => {
            const days = parseInt(input.value, 10) || 0;
            out.textContent = t.start ? Ik.formatDate(Ik.addDays(endDate(t), days)) : "Set a start date first";
          };
          input.addEventListener("input", update);
          update();
          modal.querySelector("[data-save]").addEventListener("click", () => {
            const days = parseInt(input.value, 10);
            if (!days || days < 1) return;
            const reason = modal.querySelector("[name=reason]").value.trim();
            t.extra_days += days;
            log(t, `Trial extended by ${days} days by ${viewer}${reason ? `: ${reason}` : ""}`);
            Ik.closeModal();
            Ik.toast(`${t.name}'s trial now ends ${Ik.formatDate(endDate(t))}`);
            renderAll();
          });
        },
      }
    );
  }

  function verdictPlan(kind) {
    const conf = kind === "accepted" ? settings.accept : settings.reject;
    const add = kind === "accepted" ? conf.add : [];
    const remove = conf.remove;
    const message = settings.messages[kind];
    return { add, remove, message };
  }

  function openVerdictModal(t, kind) {
    const accept = kind === "accepted";
    const plan = verdictPlan(kind);
    const channel = channelById(plan.message.channel);
    const observations = t.timeline.filter((e) => e.type === "observation").slice(-3).reverse();
    const values = { member: t.name, guild: guild.name, days: length(t), day: dayOf(t) || 0, start_date: Ik.formatDate(t.start), end_date: Ik.formatDate(endDate(t)) };

    Ik.openModal(
      `<header class="modal__header">
         <h2>${accept ? "Accept" : "Reject"} ${esc(t.name)}?</h2>
         <p class="muted small">${t.start ? `Day ${Math.min(dayOf(t), length(t))} of ${length(t)}` : "No start date"} · ${t.content_roles.length ? roleNames(t.content_roles).join(", ") : "no content role"}</p>
       </header>
       <div class="modal__body">
         <div class="modal__cols">
           <section>
             <h3 class="panel__heading">Assessment</h3>
             ${observationSummary(t)}
             ${observations.length ? `<ul class="obs-mini">${observations.map((o) => `<li><span class="tag tag--xs tag--${RATINGS[o.rating].tone}">${esc(o.category)}</span> ${esc(o.text)} <span class="muted small">— ${esc(o.author)}</span></li>`).join("")}</ul>` : ""}
           </section>
           <section>
             <h3 class="panel__heading">What happens</h3>
             <ul class="plan">
               ${plan.add.map((id) => `<li class="plan__item plan__item--add">${Ik.icon("plus", 14)} Give ${Ik.roleChip(roleById(id), roles)}</li>`).join("")}
               ${plan.remove.map((id) => `<li class="plan__item plan__item--remove">${Ik.icon("minus", 14)} Remove ${Ik.roleChip(roleById(id), roles)}</li>`).join("")}
               ${!plan.add.length && !plan.remove.length ? `<li class="plan__item muted">No role changes configured.</li>` : ""}
               ${plan.message.enabled && channel
                 ? `<li class="plan__item">${Ik.icon("message", 14)} Post in <span class="channel">#${esc(channel.name)}</span></li>`
                 : `<li class="plan__item muted">${Ik.icon("message", 14)} No message (turned off in settings)</li>`}
             </ul>
             ${plan.message.enabled && channel ? `<div class="discord-preview discord-preview--compact"><div class="discord-preview__text">${Ik.renderMessage(plan.message.text, values)}</div></div>` : ""}
           </section>
         </div>
         <label class="field"><span class="field__label">Reason <span class="muted">(optional, only visible to recruiters)</span></span>
           <textarea class="input textarea" name="reason" rows="2"></textarea></label>
       </div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--${accept ? "green" : "red"}" type="button" data-confirm>${accept ? "Accept" : "Reject"} ${esc(t.name)}</button>
       </footer>`,
      {
        wide: true,
        onMount(modal) {
          modal.querySelector("[data-confirm]").addEventListener("click", () => {
            const reason = modal.querySelector("[name=reason]").value.trim();
            applyVerdict(t, kind, reason);
            Ik.closeModal();
            Ik.toast(`${t.name} ${accept ? "accepted" : "rejected"}`);
            renderAll();
          });
        },
      }
    );
  }

  function applyVerdict(t, kind, reason) {
    const plan = verdictPlan(kind);
    const channel = channelById(plan.message.channel);
    t.verdict = kind;
    t.verdict_at = Ik.nowIso(today);
    t.verdict_by = viewer;
    t.action_error = null;
    log(t, `${kind === "accepted" ? "Accepted" : "Rejected"} by ${viewer}${reason ? `: ${reason}` : ""}`);
    const changes = [...roleNames(plan.add).map((n) => `+ ${n}`), ...roleNames(plan.remove).map((n) => `− ${n}`)];
    if (changes.length) log(t, `Roles changed: ${changes.join(", ")}`);
    if (plan.message.enabled && channel) log(t, `Message posted in #${channel.name}`);
  }

  function retry(t) {
    const plan = verdictPlan("accepted");
    Ik.confirm({
      title: `Retry role change for ${t.name}?`,
      body: `<p class="muted">${esc(t.action_error)}</p><p>Ironkeep will try again to ${[...roleNames(plan.add).map((n) => `give ${n}`), ...roleNames(plan.remove).map((n) => `remove ${n}`)].join(" and ")}. Make sure the Ironkeep role sits above these roles in Discord.</p>`,
      confirmLabel: "Retry",
      onConfirm() {
        t.action_error = null;
        t.verdict = "accepted";
        t.verdict_at = Ik.nowIso(today);
        t.verdict_by = t.verdict_by || viewer;
        const changes = [...roleNames(plan.add).map((n) => `+ ${n}`), ...roleNames(plan.remove).map((n) => `− ${n}`)];
        log(t, `Role change retried by ${viewer}: ${changes.join(", ")}`);
        Ik.toast(`Roles updated for ${t.name}`);
        renderAll();
      },
    });
  }

  document.addEventListener("click", (event) => {
    const filterBtn = event.target.closest("[data-filter]");
    if (filterBtn) {
      state.filter = filterBtn.dataset.filter;
      renderAll();
      return;
    }

    const tabBtn = event.target.closest("[data-tab]");
    if (tabBtn) {
      state.tab = tabBtn.dataset.tab;
      state.editing = null;
      renderPanel();
      return;
    }

    const sortTh = event.target.closest("th[data-sort]");
    if (sortTh) {
      const key = sortTh.dataset.sort;
      state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : 1 };
      renderTable();
      return;
    }

    const actionEl = event.target.closest("[data-action]");
    if (actionEl) {
      const t = trialById(Number(actionEl.dataset.id)) || trialById(state.selected);
      const action = actionEl.dataset.action;
      event.stopPropagation();
      if (action === "close") {
        state.selected = null;
        renderAll();
      } else if (action === "open") openTrial(t.id);
      else if (action === "set-start") openStartModal(t);
      else if (action === "extend") openExtendModal(t);
      else if (action === "accept") openVerdictModal(t, "accepted");
      else if (action === "reject") openVerdictModal(t, "rejected");
      else if (action === "retry") retry(t);
      else if (action === "open-form" || action === "close-form") {
        state.formOpen = action === "open-form";
        renderPanel();
      }
      else if (action === "edit-obs") {
        state.editing = Number(actionEl.dataset.index);
        renderPanel();
      } else if (action === "cancel-edit") {
        state.editing = null;
        renderPanel();
      } else if (action === "save-edit") {
        const entry = t.timeline[Number(actionEl.dataset.index)];
        const text = document.querySelector("[data-edit-text]").value.trim();
        if (text && text !== entry.text) {
          entry.text = text;
          entry.edited = true;
          Ik.toast("Observation updated");
        }
        state.editing = null;
        renderPanel();
      } else if (action === "delete-obs") {
        const index = Number(actionEl.dataset.index);
        const entry = t.timeline[index];
        Ik.confirm({
          title: "Delete this observation?",
          body: `<p class="muted">"${esc(entry.text)}"</p><p>The timeline will keep a line saying that an observation was deleted.</p>`,
          confirmLabel: "Delete",
          tone: "red",
          onConfirm() {
            t.timeline.splice(index, 1);
            log(t, `${entry.category} observation deleted by ${viewer}`);
            renderAll();
          },
        });
      }
      return;
    }

    const row = event.target.closest("[data-open]");
    if (row) {
      openTrial(Number(row.dataset.open));
      return;
    }

    if (event.target.id === "panel-overlay") {
      state.selected = null;
      renderAll();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("tr[data-open]")) openTrial(Number(event.target.dataset.open));
    if (event.key === "Escape" && state.selected && document.getElementById("modal-root").hidden) {
      state.selected = null;
      renderAll();
    }
  });

  document.addEventListener("submit", (event) => {
    if (!event.target.matches("[data-obs-form]")) return;
    event.preventDefault();
    const form = new FormData(event.target);
    const text = String(form.get("text") || "").trim();
    if (!text) {
      event.target.querySelector("textarea").focus();
      return;
    }
    const t = trialById(state.selected);
    t.timeline.push({ type: "observation", at: Ik.nowIso(today), author: viewer, category: form.get("category"), rating: form.get("rating"), text });
    state.formOpen = false;
    Ik.toast("Observation added");
    renderAll();
  });

  document.getElementById("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderTable();
  });

  renderAll();
})();
