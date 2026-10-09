(function () {
  const data = Ik.pageData();
  if (!data || !document.getElementById("settings-form")) return;

  const esc = Ik.escape;
  const { roles, channels, guild, setupMode } = data;
  const state = JSON.parse(JSON.stringify(data.settings));
  state.overview_enabled = true;
  let saved = JSON.stringify(state);

  const botRole = roles.find((r) => r.managed && r.name === "Ironkeep");
  const roleById = (id) => roles.find((r) => r.id === id);
  const channelById = (id) => channels.find((c) => c.id === id);
  const pickableRoles = roles.filter((r) => !r.everyone && !r.managed).sort((a, b) => b.position - a.position);
  const manageable = (role) => !botRole || role.position < botRole.position;

  const MESSAGES = [
    { key: "welcome", title: "Welcome in the perms channel", when: "When someone joins the server.", placeholders: ["member", "guild"] },
    { key: "trial_started", title: "Trial started", when: "When the trial role is given. The start date is recorded at that moment.", placeholders: ["member", "guild", "days", "start_date", "end_date"] },
    { key: "reminder", title: "Content role reminder", when: "Sent once, pinging the trial member, if they have no content role on the reminder day. Pick a channel the trial role can see.", placeholders: ["member", "guild", "day", "days", "end_date"] },
    { key: "accepted", title: "Accepted", when: "When a recruiter accepts a trial on this website.", placeholders: ["member", "guild"] },
    { key: "rejected", title: "Rejected", when: "When a recruiter rejects a trial on this website.", placeholders: ["member", "guild"] },
  ];

  function get(path) {
    return path.split(".").reduce((obj, key) => (obj == null ? obj : obj[key]), state);
  }

  function set(path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    keys.reduce((obj, key) => obj[key], state)[last] = value;
  }

  /* Pickers */

  function renderPicker(el) {
    const path = el.dataset.picker;
    const multi = el.hasAttribute("data-multi");
    const kind = el.dataset.kind;
    const value = get(path);
    const ids = multi ? value || [] : value ? [value] : [];
    const open = el.classList.contains("is-open");
    const query = el.querySelector(".picker__search")?.value || "";

    const chips = ids
      .map((id) => {
        if (kind === "role") {
          const role = roleById(id);
          if (!role) return "";
          const remove = multi ? `<span class="picker__remove" role="button" tabindex="0" data-remove="${id}" aria-label="Remove ${esc(role.name)}">${Ik.icon("x", 12)}</span>` : "";
          return Ik.roleChip(role, roles, remove);
        }
        const channel = channelById(id);
        return channel ? `<span class="channel">#${esc(channel.name)}</span>` : "";
      })
      .join("");

    el.innerHTML = `
      <div class="picker__field" role="button" tabindex="0" aria-haspopup="listbox" aria-expanded="${open}" data-picker-toggle>
        ${chips || `<span class="picker__placeholder">${kind === "role" ? (multi ? "Choose roles…" : "Choose a role…") : "Choose a channel…"}</span>`}
      </div>
      ${open ? `<div class="picker__menu">
        <input class="input picker__search" type="search" placeholder="Search ${kind === "role" ? "roles" : "channels"}" value="${esc(query)}">
        <div class="picker__list">${pickerOptions(el, ids, query)}</div>
      </div>` : ""}`;

    if (open) {
      const search = el.querySelector(".picker__search");
      search.focus();
      search.setSelectionRange(search.value.length, search.value.length);
    }
  }

  function pickerOptions(el, ids, query) {
    const q = query.trim().toLowerCase();
    const needsManage = el.hasAttribute("data-manageable");
    if (el.dataset.kind === "role") {
      const options = pickableRoles.filter((r) => !q || r.name.toLowerCase().includes(q));
      if (!options.length) return '<div class="picker__empty">No roles match.</div>';
      return options
        .map((r) => {
          const dup = roles.filter((x) => x.name === r.name).length > 1;
          const meta = needsManage && !manageable(r)
            ? '<span class="picker__option-meta" style="color:var(--orange)">above Ironkeep</span>'
            : dup ? `<span class="picker__option-meta">ID …${r.id.slice(-4)}</span>` : "";
          return `<button class="picker__option ${ids.includes(r.id) ? "is-selected" : ""}" type="button" data-option="${r.id}">
            <span class="role-chip__dot" style="background:${esc(r.color)}"></span>
            <span class="picker__option-name">${esc(r.name)}</span>${meta}
            <span class="picker__check">${Ik.icon("check", 15)}</span>
          </button>`;
        })
        .join("");
    }
    const groups = {};
    channels
      .filter((c) => !q || c.name.includes(q))
      .forEach((c) => {
        (groups[c.category] = groups[c.category] || []).push(c);
      });
    const names = Object.keys(groups);
    if (!names.length) return '<div class="picker__empty">No channels match.</div>';
    return names
      .map(
        (g) => `<div class="picker__group">${esc(g)}</div>${groups[g]
          .map(
            (c) => `<button class="picker__option ${ids.includes(c.id) ? "is-selected" : ""}" type="button" data-option="${c.id}">
              <span class="muted">#</span><span class="picker__option-name">${esc(c.name)}</span>
              ${c.bot_can_send ? "" : '<span class="picker__option-meta" style="color:var(--red)">can\'t post</span>'}
              <span class="picker__check">${Ik.icon("check", 15)}</span>
            </button>`
          )
          .join("")}`
      )
      .join("");
  }

  function closePickers(except) {
    document.querySelectorAll("[data-picker].is-open").forEach((el) => {
      if (el !== except) {
        el.classList.remove("is-open");
        renderPicker(el);
      }
    });
  }

  function renderAllPickers() {
    document.querySelectorAll("[data-picker]").forEach(renderPicker);
  }

  /* Messages */

  function previewValues() {
    const todayIso = new Date().toISOString().slice(0, 10);
    return {
      member: "Velorn",
      guild: guild.name,
      days: state.trial_days,
      day: state.reminder_day,
      start_date: Ik.formatDate(todayIso),
      end_date: Ik.formatDate(Ik.addDays(todayIso, Number(state.trial_days) || 0)),
    };
  }

  function discordPreview(bodyHtml) {
    return `<span class="discord-preview__avatar">${Ik.icon("scale", 18)}</span>
      <div>
        <div class="discord-preview__head"><span class="discord-preview__name">Ironkeep</span><span class="discord-preview__bot">APP</span><span class="discord-preview__time">Today at 20:14</span></div>
        <div class="discord-preview__text">${bodyHtml}</div>
      </div>`;
  }

  function renderMessageCards() {
    document.getElementById("message-cards").innerHTML = MESSAGES.map((m) => {
      const msg = state.messages[m.key];
      const when = m.key === "reminder" ? m.when.replace("the reminder day", `day ${esc(state.reminder_day)}`) : m.when;
      return `<div class="message-card ${msg.enabled ? "" : "is-disabled"}" data-message="${m.key}">
        <div class="message-card__head">
          <div>
            <div class="message-card__title">${m.title}</div>
            <div class="setting__hint" data-when="${m.key}">${when}</div>
          </div>
          <label class="toggle" title="${msg.enabled ? "On" : "Off"}"><input type="checkbox" data-message-toggle="${m.key}" ${msg.enabled ? "checked" : ""}><span class="toggle__track"></span></label>
        </div>
        <div class="message-card__body">
          <div>
            <div class="field"><span class="field__label">Channel</span>
              <div class="picker" data-picker="messages.${m.key}.channel" data-kind="channel"></div>
              <div data-warnings="messages.${m.key}.channel"></div>
            </div>
            <label class="field"><span class="field__label">Text</span>
              <textarea class="input textarea" rows="4" data-message-text="${m.key}">${esc(msg.text)}</textarea>
            </label>
            <div class="placeholders" style="margin-top:8px">${m.placeholders.map((p) => `<button class="placeholder-chip" type="button" data-insert="${p}" data-target="${m.key}">{${p}}</button>`).join("")}</div>
          </div>
          <div class="field"><span class="field__label">Preview</span>
            <div class="discord-preview" data-preview="${m.key}"></div>
          </div>
        </div>
      </div>`;
    }).join("");
  }

  function renderPreviews() {
    const values = previewValues();
    MESSAGES.forEach((m) => {
      const node = document.querySelector(`[data-preview="${m.key}"]`);
      if (node) node.innerHTML = discordPreview(Ik.renderMessage(state.messages[m.key].text, values));
      const when = document.querySelector(`[data-when="reminder"]`);
      if (when) when.textContent = MESSAGES[2].when.replace("the reminder day", `day ${state.reminder_day}`);
    });
    const overview = document.getElementById("overview-preview");
    if (overview) {
      overview.innerHTML = discordPreview(
        `<strong>Trials that need attention (3)</strong>\n• <span class="mention">@Velorn</span> day 9, no content role\n• <span class="mention">@Crylen</span> no start date\n• <span class="mention">@Orain</span> verdict due\nFull list: <a href="/${esc(guild.slug)}/trial">ironkeep.gg/${esc(state.slug || guild.slug)}/trial</a>`
      );
    }
  }

  /* Checks */

  function slugError() {
    const slug = state.slug ?? guild.slug;
    if (!/^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/.test(slug)) return "Use 1–32 lowercase letters, numbers or dashes.";
    if (data.taken.includes(slug)) return "This address is already taken.";
    return null;
  }

  function channelWarnings(path) {
    const id = get(path);
    const out = [];
    const isMessage = path.startsWith("messages.");
    const key = isMessage ? path.split(".")[1] : null;
    const enabled = isMessage ? state.messages[key].enabled : state.overview_enabled;
    if (!enabled) return out;
    if (!id) {
      out.push({ level: "error", text: "Choose a channel." });
      return out;
    }
    const channel = channelById(id);
    if (!channel.bot_can_send) out.push({ level: "error", text: `Ironkeep can't send messages in #${channel.name}.` });
    if (key === "reminder" && !channel.trial_visible) out.push({ level: "warn", text: `The trial role can't see #${channel.name}, so the ping won't reach them.` });
    return out;
  }

  function roleWarnings(path) {
    return (get(path) || [])
      .map(roleById)
      .filter((r) => r && !manageable(r))
      .map((r) => ({ level: "error", text: `Ironkeep can't manage ${r.name}. Move the Ironkeep role above it in Server Settings → Roles.` }));
  }

  function computeChecks() {
    const checks = [];
    const add = (section, level, title, detail = "") => checks.push({ section, level, title, detail });

    add("review", "ok", "Server Members intent is on", "Needed to see joins and role changes.");
    if (slugError()) add("basics", "error", "Web address is not valid", slugError());
    if (Number(state.reminder_day) > Number(state.trial_days)) add("basics", "warn", "Reminder comes after the trial ends", `Day ${state.reminder_day} is later than the ${state.trial_days}-day trial.`);

    if (!state.recruitment_roles.length) add("roles", "error", "No recruitment role chosen", "Nobody except the server owner could open this dashboard.");
    else add("roles", "ok", "Recruitment roles chosen", state.recruitment_roles.map((id) => roleById(id)?.name).join(", "));
    if (!state.trial_role) add("roles", "error", "No trial role chosen", "Ironkeep won't know when a trial starts.");
    else add("roles", "ok", "Trial role chosen", roleById(state.trial_role)?.name);
    if (!state.content_roles.length) add("roles", "warn", "No content roles chosen", "Every trial will count as having no content role.");

    MESSAGES.forEach((m) => {
      channelWarnings(`messages.${m.key}.channel`).forEach((w) => add("messages", w.level, `${m.title}: ${w.text}`));
    });
    channelWarnings("channels.recruiter_overview").forEach((w) => add("messages", w.level, `Recruiter overview: ${w.text}`));
    if (!checks.some((c) => c.section === "messages" && c.level !== "ok")) add("messages", "ok", "Ironkeep can post all enabled messages");

    if (!state.albion.guild_name && state.albion.guild_check !== "off") add("albion", "warn", "No Albion guild set", "The guild check can't run until you enter the in-game guild name.");
    else if (state.albion.guild_name) add("albion", "ok", "Albion guild set", `${state.albion.guild_name} on the ${state.albion.region} server`);

    ["accept.add", "accept.remove", "reject.remove"].forEach((path) => roleWarnings(path).forEach((w) => add("verdict", w.level, w.text)));
    if (!state.accept.add.length && !state.accept.remove.length) add("verdict", "warn", "Accepting changes no roles", "Recruiters will have to change roles by hand.");
    if (!state.reject.remove.length) add("verdict", "warn", "Rejecting removes no roles");
    if (!checks.some((c) => c.section === "verdict" && c.level === "error")) add("verdict", "ok", "Ironkeep can manage all verdict roles");

    return checks;
  }

  function renderChecks() {
    const checks = computeChecks();
    const order = { error: 0, warn: 1, ok: 2 };
    const icons = { ok: "check", warn: "alert", error: "x" };
    document.getElementById("checks").innerHTML = checks
      .slice()
      .sort((a, b) => order[a.level] - order[b.level])
      .map((c) => `<li class="check check--${c.level}">${Ik.icon(icons[c.level], 16)}<span class="check__text"><strong>${esc(c.title)}</strong>${c.detail ? `<span>${esc(c.detail)}</span>` : ""}</span></li>`)
      .join("");

    document.querySelectorAll("[data-status]").forEach((dot) => {
      const section = dot.dataset.status;
      const bad = checks.some((c) => (section === "review" || c.section === section) && c.level === "error");
      const warn = checks.some((c) => (section === "review" || c.section === section) && c.level === "warn");
      dot.classList.toggle("is-missing", bad || warn);
      dot.style.background = bad ? "var(--red)" : "";
    });

    document.querySelectorAll("[data-warnings]").forEach((node) => {
      const path = node.dataset.warnings;
      node.innerHTML = channelWarnings(path)
        .map((w) => `<span class="setting__warning" style="${w.level === "error" ? "color:var(--red)" : ""}">${Ik.icon("alert", 14)} ${esc(w.text)}</span>`)
        .join("");
    });

    document.querySelectorAll("[data-picker][data-manageable]").forEach((el) => {
      let node = el.nextElementSibling;
      if (!node || !node.matches("[data-role-warnings]")) {
        node = document.createElement("div");
        node.setAttribute("data-role-warnings", "");
        el.after(node);
      }
      node.innerHTML = roleWarnings(el.dataset.picker)
        .map((w) => `<span class="setting__warning" style="color:var(--red)">${Ik.icon("alert", 14)} ${esc(w.text)}</span>`)
        .join("");
    });

    const guildHint = document.querySelector("[data-albion-guild-hint]");
    const original = data.settings.albion;
    if (!state.albion.guild_name) guildHint.textContent = "Leave empty to skip the guild check.";
    else if (state.albion.guild_name.toLowerCase() === original.guild_name.toLowerCase() && state.albion.region === original.region) {
      guildHint.innerHTML = `<span style="color:var(--green)">Found: ${esc(original.guild_name)} · ${original.guild_members} members</span>`;
    } else guildHint.textContent = "Ironkeep looks this guild up when you save.";

    const hint = document.querySelector("[data-slug-hint]");
    const err = slugError();
    hint.innerHTML = err ? `<span style="color:var(--red)">${esc(err)}</span>` : `Recruiters open <span class="mono">ironkeep.gg/${esc(state.slug ?? guild.slug)}/trial</span>`;
    document.querySelector("[data-reminder-warning]").hidden = !(Number(state.reminder_day) > Number(state.trial_days));

    return checks;
  }

  function markDirty() {
    const dirty = JSON.stringify(state) !== saved;
    const text = document.querySelector("[data-save-text]");
    if (text) {
      text.textContent = dirty ? "You have unsaved changes." : "All changes saved.";
      document.querySelector("[data-discard]").disabled = !dirty;
    }
  }

  function refresh() {
    renderPreviews();
    renderChecks();
    markDirty();
  }

  /* Events */

  const form = document.getElementById("settings-form");

  form.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove]");
    if (remove) {
      const el = remove.closest("[data-picker]");
      set(el.dataset.picker, get(el.dataset.picker).filter((id) => id !== remove.dataset.remove));
      renderPicker(el);
      refresh();
      event.stopPropagation();
      return;
    }

    const toggle = event.target.closest("[data-picker-toggle]");
    if (toggle) {
      const el = toggle.closest("[data-picker]");
      closePickers(el);
      el.classList.toggle("is-open");
      renderPicker(el);
      return;
    }

    const option = event.target.closest("[data-option]");
    if (option) {
      const el = option.closest("[data-picker]");
      const path = el.dataset.picker;
      const id = option.dataset.option;
      if (el.hasAttribute("data-multi")) {
        const current = get(path) || [];
        set(path, current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
      } else {
        set(path, id);
        el.classList.remove("is-open");
      }
      renderPicker(el);
      refresh();
      return;
    }

    const insert = event.target.closest("[data-insert]");
    if (insert) {
      const area = form.querySelector(`[data-message-text="${insert.dataset.target}"]`);
      const token = `{${insert.dataset.insert}}`;
      const start = area.selectionStart ?? area.value.length;
      area.value = area.value.slice(0, start) + token + area.value.slice(area.selectionEnd ?? start);
      area.focus();
      area.setSelectionRange(start + token.length, start + token.length);
      area.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });

  document.addEventListener("click", (event) => {
    const insidePicker = event.composedPath().some((node) => node instanceof Element && node.matches("[data-picker]"));
    if (!insidePicker) closePickers();
  });

  form.addEventListener("input", (event) => {
    const target = event.target;
    if (target.classList.contains("picker__search")) {
      const el = target.closest("[data-picker]");
      const list = el.querySelector(".picker__list");
      const value = get(el.dataset.picker);
      const ids = el.hasAttribute("data-multi") ? value || [] : value ? [value] : [];
      list.innerHTML = pickerOptions(el, ids, target.value);
      return;
    }
    if (target.dataset.messageText) {
      state.messages[target.dataset.messageText].text = target.value;
    } else if (target.dataset.messageToggle) {
      state.messages[target.dataset.messageToggle].enabled = target.checked;
      target.closest(".message-card").classList.toggle("is-disabled", !target.checked);
    } else if (target.name === "overview_enabled") {
      state.overview_enabled = target.checked;
      document.getElementById("overview-card").classList.toggle("is-disabled", !target.checked);
    } else if (target.name === "slug") {
      state.slug = target.value.trim().toLowerCase();
    } else if (target.name === "trial_days" || target.name === "reminder_day") {
      state[target.name] = Number(target.value);
    } else if (target.name === "timezone") {
      state.timezone = target.value;
    } else if (target.name?.startsWith("albion.")) {
      const key = target.name.slice(7);
      state.albion[key] = target.type === "checkbox" ? target.checked : key === "guild_name" ? target.value.trim() : target.value;
    }
    refresh();
  });

  form.addEventListener("change", (event) => {
    if (event.target.name === "timezone") {
      state.timezone = event.target.value;
      refresh();
    }
  });

  form.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePickers();
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-picker-toggle], [data-remove]")) {
      event.preventDefault();
      event.target.click();
      return;
    }
    if (event.key === "Enter" && event.target.classList.contains("picker__search")) {
      event.preventDefault();
      const first = event.target.closest("[data-picker]").querySelector("[data-option]");
      if (first) first.click();
    }
  });

  const recheck = document.querySelector("[data-recheck]");
  if (recheck) {
    recheck.addEventListener("click", () => {
      renderChecks();
      Ik.toast("Permissions checked just now");
    });
  }

  /* Settings mode */

  const saveBtn = document.querySelector("[data-save]");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const errors = renderChecks().filter((c) => c.level === "error");
      saved = JSON.stringify(state);
      markDirty();
      if (errors.length) Ik.toast(`Saved, but ${errors.length} check${errors.length > 1 ? "s need" : " needs"} attention`, "red");
      else Ik.toast("Settings saved");
    });
    document.querySelector("[data-discard]").addEventListener("click", () => window.location.reload());

    const links = document.querySelectorAll("[data-section-link]");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            links.forEach((a) => a.classList.toggle("is-active", a.dataset.sectionLink === entry.target.id));
          }
        });
      },
      { rootMargin: "-20% 0px -70% 0px" }
    );
    document.querySelectorAll(".settings-form > .card").forEach((card) => observer.observe(card));
  }

  /* Setup wizard */

  let step = 0;
  const STEP_COUNT = 5;

  function showStep(n) {
    step = Math.max(0, Math.min(STEP_COUNT - 1, n));
    document.querySelectorAll("[data-step-panel]").forEach((panel) => {
      panel.hidden = Number(panel.dataset.stepPanel) !== step;
    });
    document.querySelectorAll("[data-step]").forEach((btn) => {
      const i = Number(btn.dataset.step);
      btn.classList.toggle("is-active", i === step);
      btn.classList.toggle("is-done", i < step);
    });
    document.querySelector("[data-step-back]").disabled = step === 0;
    document.querySelector("[data-step-text]").textContent = `Step ${step + 1} of ${STEP_COUNT}`;
    const next = document.querySelector("[data-step-next]");
    next.innerHTML = step === STEP_COUNT - 1 ? `${Ik.icon("check", 15)} Finish setup` : `Next ${Ik.icon("arrow-right", 15)}`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function finishSetup() {
    const errors = renderChecks().filter((c) => c.level === "error");
    if (errors.length) {
      Ik.toast(`Fix the ${errors.length} check${errors.length > 1 ? "s" : ""} marked red first`, "red");
      return;
    }
    const pending = guild.approval === "pending";
    Ik.openModal(
      `<header class="modal__header"><h2>${pending ? "Setup saved" : "Ironkeep is ready"}</h2></header>
       <div class="modal__body">
         ${pending
           ? `<p>Your settings are saved. Ironkeep stays silent in <strong>${esc(guild.name)}</strong> until the request is approved. You'll get a message in Discord once it's approved.</p>`
           : `<p>From now on, Ironkeep follows joins and the trial role in <strong>${esc(guild.name)}</strong>.</p>`}
         <p class="muted" style="margin-top:10px">Trials that were already running have no reliable start date. They'll show up as "No start date" so you can fill them in once.</p>
       </div>
       <footer class="modal__footer">
         <a class="button button--accent" href="/${esc(guild.slug)}/trial">Go to trials ${Ik.icon("arrow-right", 15)}</a>
       </footer>`
    );
  }

  if (setupMode) {
    document.querySelectorAll("[data-step]").forEach((btn) => btn.addEventListener("click", () => showStep(Number(btn.dataset.step))));
    document.querySelector("[data-step-back]").addEventListener("click", () => showStep(step - 1));
    document.querySelector("[data-step-next]").addEventListener("click", () => (step === STEP_COUNT - 1 ? finishSetup() : showStep(step + 1)));
  }

  renderMessageCards();
  renderAllPickers();
  refresh();
  if (setupMode) showStep(0);
})();
