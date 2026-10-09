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

  const groupOf = (t) => STATUS[statusOf(t)].group;
  const needsAttention = (t) => groupOf(t) === "attention" || albionFlags(t).length > 0;

  const FILTERS = [
    { key: "open", label: "All open", match: (t) => groupOf(t) !== "closed" },
    { key: "attention", label: "Needs attention", match: needsAttention },
    { key: "ending", label: "Ending soon", match: (t) => groupOf(t) === "ending" },
    { key: "verdict", label: "Verdict due", match: (t) => groupOf(t) === "verdict" },
    { key: "closed", label: "Closed", match: (t) => groupOf(t) === "closed" },
  ];

  const FAME_KINDS = [
    { key: "pve", label: "PvE", color: "var(--accent)" },
    { key: "pvp", label: "PvP (kill fame)", color: "var(--red)" },
    { key: "gathering", label: "Gathering", color: "var(--green)" },
    { key: "crafting", label: "Crafting", color: "var(--orange)" },
  ];
  const albionGuild = settings.albion.guild_name || "the guild";

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

  function albionFlags(t) {
    if (groupOf(t) === "closed") return [];
    const a = t.albion;
    if (!a.name) return [{ key: "unlinked", label: "No Albion name", tone: "orange" }];
    const graceOver = !t.start || dayOf(t) >= 2;
    if (settings.albion.guild_check !== "off" && settings.albion.guild_name && a.in_guild === false && graceOver) {
      return [{ key: "not_in_guild", label: "Not in guild in-game", tone: "red" }];
    }
    return [];
  }

  function flagTags(t, size = "xs") {
    return albionFlags(t).map((f) => `<span class="tag tag--${size} tag--${f.tone}">${esc(f.label)}</span>`).join("");
  }

  const fameTotals = (t) => {
    const totals = { pve: 0, pvp: 0, gathering: 0, crafting: 0 };
    t.albion.fame.forEach((d) => FAME_KINDS.forEach((k) => (totals[k.key] += d[k.key])));
    return totals;
  };
  const fameSum = (totals) => FAME_KINDS.reduce((sum, k) => sum + totals[k.key], 0);

  function formatFame(n) {
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${Math.round(n / 1e3)}K`;
    return String(n);
  }

  function persist(t) {
    if (!data.live) return;
    fetch(`/api/${guild.slug}/trials/${t.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start: t.start,
        extra_days: t.extra_days,
        timeline: t.timeline,
        albion: t.albion,
        lost_content_role: t.lost_content_role,
        ping_sent_at: t.ping_sent_at,
      }),
    });
  }

  function log(t, text, type = "system") {
    t.timeline.push({ type, at: Ik.nowIso(today), text });
    persist(t);
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

  function fameCell(t) {
    if (!t.albion.name) return '<span class="muted">—</span>';
    const totals = fameTotals(t);
    const top = FAME_KINDS.slice().sort((a, b) => totals[b.key] - totals[a.key])[0];
    const sum = fameSum(totals);
    return `<span class="fame-cell"><strong>${formatFame(sum)}</strong>${sum ? `<span class="muted small">mostly ${top.label.split(" ")[0]}</span>` : ""}</span>`;
  }

  function fameSummaryLine(t) {
    if (!settings.albion.track_fame) return "";
    if (!t.albion.name) return `<p class="muted small fame-line">No Albion name linked, so no fame numbers.</p>`;
    const totals = fameTotals(t);
    const parts = FAME_KINDS.filter((k) => totals[k.key]).map((k) => `${k.label.split(" ")[0]} ${formatFame(totals[k.key])}`);
    return `<p class="small fame-line"><strong>${formatFame(fameSum(totals))} fame</strong> during the trial${parts.length ? ` <span class="muted">· ${parts.join(" · ")}</span>` : ""}</p>`;
  }

  function renderAlbionTab(t) {
    const a = t.albion;
    const closed = groupOf(t) === "closed";
    if (!a.name) {
      return `<section class="panel__section">
        <div class="albion-empty">
          <p><strong>No Albion name linked.</strong></p>
          <p class="muted small">Ironkeep couldn't find a player called "${esc(t.name)}" on the ${esc(regionLabel())} server. Link the right name to start tracking fame${settings.albion.guild_check !== "off" ? ` and check if they're in ${esc(albionGuild)}` : ""}.</p>
          ${closed ? "" : `<button class="button button--accent button--sm" type="button" data-action="link-albion" data-id="${t.id}">${Ik.icon("user-plus", 14)} Link Albion name</button>`}
        </div>
      </section>`;
    }

    const linkText = a.link === "manual" ? "Set by a recruiter" : "From Discord nickname";
    let guildRow = "";
    if (settings.albion.guild_check !== "off" && settings.albion.guild_name) {
      if (a.in_guild) {
        guildRow = `<div class="albion-row"><span class="muted">In-game guild</span><span class="tag tag--xs tag--green">${Ik.icon("check", 12)} In ${esc(albionGuild)}</span></div>`;
      } else {
        const seen = a.last_in_guild ? `Was in ${esc(albionGuild)} until ${Ik.formatDate(a.last_in_guild)}.` : `Hasn't been seen in ${esc(albionGuild)} since the trial started.`;
        guildRow = `<div class="callout callout--red albion-callout">${Ik.icon("alert")}<div><strong>Not in ${esc(albionGuild)} in-game</strong>
          <p>${seen} They may have left, never joined, or the linked name is wrong.</p></div></div>`;
      }
    }

    let fame = "";
    if (settings.albion.track_fame) {
      const totals = fameTotals(t);
      const sum = fameSum(totals);
      const max = Math.max(1, ...FAME_KINDS.map((k) => totals[k.key]));
      const dayMax = Math.max(1, ...a.fame.map((d) => fameSum(d)));
      const sinceNote = t.start ? "" : ` Ironkeep started tracking on ${Ik.formatDate(a.fame_since)}; fame from before that isn't known.`;
      fame = `<section class="panel__section">
        <h3 class="panel__heading">Fame during trial</h3>
        <div class="fame-total"><strong>${formatFame(sum)}</strong><span class="muted small">since ${Ik.formatDate(a.fame_since)}</span></div>
        <div class="fame-kinds">${FAME_KINDS.map((k) => `<div class="fame-kind">
            <span class="fame-kind__label">${k.label}</span>
            <span class="fame-kind__bar"><span style="width:${Math.round((totals[k.key] / max) * 100)}%;background:${k.color}"></span></span>
            <span class="fame-kind__value">${formatFame(totals[k.key])}</span>
          </div>`).join("")}</div>
        ${a.fame.length ? `<div class="fame-chart" role="img" aria-label="Fame per day">${a.fame.map((d) => {
            const total = fameSum(d);
            return `<span class="fame-chart__day" title="${Ik.formatDate(d.date)}: ${formatFame(total)}"><span style="height:${total ? Math.max(4, Math.round((total / dayMax) * 100)) : 0}%"></span></span>`;
          }).join("")}</div>
          <div class="fame-chart__axis muted small"><span>${Ik.formatDate(a.fame[0].date)}</span><span>${Ik.formatDate(a.fame[a.fame.length - 1].date)}</span></div>`
          : `<p class="muted small">No daily numbers yet. The first update comes tomorrow.</p>`}
        <p class="muted small fame-note">Albion updates these numbers about once a day. Last update: ${Ik.formatDateTime(data.albionUpdatedAt)}.${sinceNote}</p>
      </section>`;
    }

    return `<section class="panel__section">
        <div class="albion-head">
          <div>
            ${settings.albion.region === "europe"
              ? `<a class="albion-name" href="https://europe.albiondb.net/player/${encodeURIComponent(a.name)}" target="_blank" rel="noopener">${esc(a.name)}</a>`
              : `<span class="albion-name">${esc(a.name)}</span>`}
            <span class="muted small">${linkText} · ${esc(regionLabel())}</span>
          </div>
          ${closed ? "" : `<button class="button button--ghost button--sm" type="button" data-action="link-albion" data-id="${t.id}">${Ik.icon("pencil", 13)} Change</button>`}
        </div>
        ${guildRow}
      </section>
      ${fame}`;
  }

  function regionLabel() {
    return { europe: "Europe", americas: "Americas", asia: "Asia" }[settings.albion.region] || settings.albion.region;
  }

  function openLinkModal(t) {
    Ik.openModal(
      `<header class="modal__header"><h2>${t.albion.name ? "Change" : "Link"} Albion name for ${esc(t.name)}</h2></header>
       <div class="modal__body">
         <p class="muted">Use the character name exactly as it is in the game, on the ${esc(regionLabel())} server. Ironkeep uses it to check guild membership and to track fame from today on.</p>
         <label class="field"><span class="field__label">Character name</span>
           <input class="input" type="text" name="albion" value="${esc(t.albion.name || "")}" spellcheck="false" autofocus></label>
         <span class="field__hint" data-lookup></span>
       </div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--accent" type="button" data-save>Save</button>
       </footer>`,
      {
        onMount(modal) {
          const input = modal.querySelector("[name=albion]");
          const hint = modal.querySelector("[data-lookup]");
          const update = () => {
            const value = input.value.trim();
            hint.innerHTML = value.length >= 3
              ? `${Ik.icon("check", 13)} Found <strong>${esc(value)}</strong> · ${esc(albionGuild)} <span class="muted">(prototype: every name is found)</span>`
              : "At least 3 characters.";
          };
          input.addEventListener("input", update);
          update();
          modal.querySelector("[data-save]").addEventListener("click", () => {
            const value = input.value.trim();
            if (value.length < 3) return input.focus();
            const previous = t.albion.name;
            if (value !== previous) {
              t.albion = { name: value, link: "manual", in_guild: true, last_in_guild: null, fame_since: today, fame: [] };
              log(t, previous ? `Albion name changed from ${previous} to ${value} by ${viewer}` : `Albion name ${value} linked by ${viewer}`);
            }
            persist(t);
            Ik.closeModal();
            Ik.toast(`Albion name saved for ${t.name}`);
            state.tab = "albion";
            state.selected = t.id;
            renderAll();
          });
        },
      }
    );
  }

  function renderStats() {
    const counts = { attention: 0, ending: 0, verdict: 0, open: 0 };
    trials.forEach((t) => {
      const group = groupOf(t);
      if (group !== "closed") counts.open += 1;
      if (group === "ending" || group === "verdict") counts[group] += 1;
      if (needsAttention(t)) counts.attention += 1;
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
    const flags = albionFlags(t).map((f) => f.key);
    let [action, label] = map[s] || ["open", "View"];
    if (!map[s] && flags.includes("unlinked")) [action, label] = ["link-albion", "Link Albion name"];
    else if (!map[s] && flags.includes("not_in_guild")) [action, label] = ["open-albion", "Check"];
    return `<button class="button button--outline button--sm" type="button" data-action="${action}" data-id="${t.id}">${label} ${Ik.icon("arrow-right", 14)}</button>`;
  }

  const actionRank = (t) => (groupOf(t) === "active" ? 3.5 : STATUS[statusOf(t)].rank);

  function renderActionList() {
    const items = trials
      .filter((t) => ["attention", "verdict", "ending"].includes(groupOf(t)) || needsAttention(t))
      .sort((a, b) => actionRank(a) - actionRank(b));
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
          ${groupOf(t) === "active" ? "" : `<span class="tag tag--${STATUS[s].tone}">${esc(reasonOf(t))}</span>`}
          ${flagTags(t, "sm")}
          <span class="action-row__spacer"></span>
          ${actionButton(t)}
        </div>`;
      })
      .join("");
  }

  function renderFilters() {
    document.getElementById("filters").innerHTML = FILTERS.map((f) => {
      const count = trials.filter(f.match).length;
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
      case "fame":
        return t.albion.name ? fameSum(fameTotals(t)) : -1;
      default:
        return STATUS[statusOf(t)].rank;
    }
  }

  function renderTable() {
    const filter = FILTERS.find((f) => f.key === state.filter);
    const query = state.search.trim().toLowerCase();
    const rows = trials
      .filter(filter.match)
      .filter((t) => !query || [t.name, t.username, t.albion.name || ""].some((v) => v.toLowerCase().includes(query)))
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
          ${settings.albion.track_fame ? `<td data-label="Trial fame">${fameCell(t)}</td>` : ""}
          <td data-label="Status"><span class="status-cell">${Ik.pill(STATUS[s].label, STATUS[s].tone)}${flagTags(t)}</span></td>
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
          <div class="panel__subline">${Ik.pill(STATUS[s].label, STATUS[s].tone)}${flagTags(t)}<span class="muted small">@${esc(t.username)}</span></div>
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
          <button class="tabs__tab ${tab === "albion" ? "is-active" : ""}" type="button" role="tab" data-tab="albion">Albion${albionFlags(t).length ? '<span class="tabs__dot"></span>' : ""}</button>
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
          : tab === "albion"
            ? renderAlbionTab(t)
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
             ${fameSummaryLine(t)}
             ${albionFlags(t).some((f) => f.key === "not_in_guild") ? `<p class="small fame-line" style="color:var(--red)">${Ik.icon("alert", 13)} Not in ${esc(albionGuild)} in-game</p>` : ""}
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
            submitVerdict(t, kind, reason, accept);
          });
        },
      }
    );
  }

  function submitVerdict(t, kind, reason, accept) {
    if (!data.live) {
      applyVerdict(t, kind, reason);
      Ik.closeModal();
      Ik.toast(`${t.name} ${accept ? "accepted" : "rejected"}`);
      renderAll();
      return;
    }
    fetch(`/api/${guild.slug}/trials/${t.id}/verdict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, reason }),
    })
      .then(async (response) => {
        const updated = await response.json();
        Object.assign(t, updated);
        Ik.closeModal();
        if (!response.ok) Ik.toast(updated.action_error || "Role change failed", "red");
        else Ik.toast(`${t.name} ${accept ? "accepted" : "rejected"}`);
        renderAll();
      })
      .catch(() => Ik.toast("Could not reach Ironkeep", "red"));
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
        if (data.live) {
          submitVerdict(t, "accepted", "", true);
          return;
        }
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
      else if (action === "link-albion") openLinkModal(t);
      else if (action === "open-albion") {
        openTrial(t.id);
        state.tab = "albion";
        renderPanel();
      }
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
          persist(t);
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
    persist(t);
    state.formOpen = false;
    Ik.toast("Observation added");
    renderAll();
  });

  document.getElementById("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderTable();
  });

  const syncMembers = document.getElementById("sync-members");
  if (syncMembers) {
    syncMembers.addEventListener("click", () => {
      if (!data.live) {
        Ik.toast("Members who already have a trial role would be added");
        return;
      }
      syncMembers.disabled = true;
      fetch(`/api/${guild.slug}/sync`, { method: "POST" }).then((response) => {
        syncMembers.disabled = false;
        if (!response.ok) {
          Ik.toast("Could not start the sync", "red");
          return;
        }
        Ik.toast("Checking who already has a trial role. Refresh in a minute. Their start date stays empty.");
      });
    });
  }

  renderAll();
})();
