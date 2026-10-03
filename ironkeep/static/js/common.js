(function () {
  const Ik = (window.Ik = {});

  Ik.escape = function (value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  Ik.pageData = function () {
    const node = document.getElementById("page-data");
    return node ? JSON.parse(node.textContent) : null;
  };

  const DAY_MS = 86400000;

  Ik.parseDate = function (iso) {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  };

  Ik.toIsoDate = function (date) {
    return date.toISOString().slice(0, 10);
  };

  Ik.addDays = function (iso, days) {
    return Ik.toIsoDate(new Date(Ik.parseDate(iso).getTime() + days * DAY_MS));
  };

  Ik.daysBetween = function (fromIso, toIso) {
    return Math.round((Ik.parseDate(toIso) - Ik.parseDate(fromIso)) / DAY_MS);
  };

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  Ik.formatDate = function (iso) {
    if (!iso) return "—";
    const d = Ik.parseDate(iso);
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  };

  Ik.formatDateTime = function (iso) {
    if (!iso) return "—";
    const [datePart, timePart = "00:00"] = iso.split("T");
    return `${Ik.formatDate(datePart)} · ${timePart.slice(0, 5)}`;
  };

  Ik.nowIso = function (todayIso) {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return `${todayIso}T${hh}:${mm}:00`;
  };

  Ik.icon = function (name, size = 16) {
    const paths = {
      check: '<path d="M20 6L9 17l-5-5"/>',
      x: '<path d="M18 6L6 18"/><path d="M6 6l12 12"/>',
      "arrow-right": '<path d="M5 12h14"/><path d="M12 5l7 7-7 7"/>',
      plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
      minus: '<path d="M5 12h14"/>',
      calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
      clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      alert: '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
      bell: '<path d="M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>',
      message: '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>',
      pencil: '<path d="M17 3a2.8 2.8 0 014 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
      trash: '<path d="M3 6h18"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
      "user-plus": '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/>',
      flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
      gavel: '<path d="M14 13l-7.5 7.5a2.1 2.1 0 01-3-3L11 10"/><path d="M16 16l6-6"/><path d="M8 8l6-6"/><path d="M9 7l8 8"/><path d="M21 11l-8-8"/>',
      tag: '<path d="M20.6 13.4l-7.2 7.2a2 2 0 01-2.8 0L2 12V2h10l8.6 8.6a2 2 0 010 2.8z"/><path d="M7 7h.01"/>',
      info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
      scale: '<path d="M12 4v16"/><path d="M7 20h10"/><path d="M5 7h14"/><path d="M5 7l-3 6a3 3 0 006 0L5 7z"/><path d="M19 7l-3 6a3 3 0 006 0l-3-6z"/>',
      hourglass: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.2a2 2 0 00-.6-1.4L12 12l-4.4 4.4a2 2 0 00-.6 1.4V22"/><path d="M7 2v4.2a2 2 0 00.6 1.4L12 12l4.4-4.4a2 2 0 00.6-1.4V2"/>',
      users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.9"/><path d="M16 3.1a4 4 0 010 7.8"/>',
      download: '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
      search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
      "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    };
    return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
  };

  Ik.avatar = function (name, color, size = "md") {
    return `<span class="avatar avatar--${size}" style="--avatar-color:${Ik.escape(color)}">${Ik.escape((name || "?").slice(0, 1).toUpperCase())}</span>`;
  };

  Ik.pill = function (text, tone, dot = true) {
    return `<span class="pill pill--${tone}">${dot ? '<span class="pill__dot"></span>' : ""}${Ik.escape(text)}</span>`;
  };

  Ik.roleLabel = function (role, roles) {
    const sameName = roles.filter((r) => r.name === role.name);
    return sameName.length > 1 ? `${role.name} · …${role.id.slice(-4)}` : role.name;
  };

  Ik.roleChip = function (role, roles, extra = "") {
    if (!role) return "";
    return `<span class="role-chip" style="--role-color:${Ik.escape(role.color)}"><span class="role-chip__dot"></span>${Ik.escape(Ik.roleLabel(role, roles || [role]))}${extra}</span>`;
  };

  Ik.renderMessage = function (text, values) {
    return Ik.escape(text).replace(/\{(\w+)\}/g, (match, key) => {
      if (!(key in values)) return match;
      const value = Ik.escape(values[key]);
      return key === "member" ? `<span class="mention">@${value}</span>` : value;
    });
  };

  Ik.toast = function (message, tone = "accent") {
    const stack = document.getElementById("toasts");
    if (!stack) return;
    const node = document.createElement("div");
    node.className = `toast toast--${tone}`;
    node.innerHTML = `${Ik.icon(tone === "red" ? "alert" : "check")}<span>${Ik.escape(message)}</span>`;
    stack.appendChild(node);
    requestAnimationFrame(() => node.classList.add("is-visible"));
    setTimeout(() => {
      node.classList.remove("is-visible");
      setTimeout(() => node.remove(), 250);
    }, 3200);
  };

  let modalCleanup = null;

  Ik.openModal = function (html, { onMount, wide = false } = {}) {
    const root = document.getElementById("modal-root");
    if (!root) return null;
    root.innerHTML = `<div class="modal-backdrop" data-modal-close></div><div class="modal ${wide ? "modal--wide" : ""}" role="dialog" aria-modal="true">${html}</div>`;
    root.hidden = false;
    const modal = root.querySelector(".modal");
    const onKey = (event) => {
      if (event.key === "Escape") Ik.closeModal();
    };
    document.addEventListener("keydown", onKey);
    root.querySelectorAll("[data-modal-close]").forEach((el) => el.addEventListener("click", Ik.closeModal));
    modalCleanup = () => document.removeEventListener("keydown", onKey);
    if (onMount) onMount(modal);
    const focusTarget = modal.querySelector("[autofocus], input, textarea, select, button.button--accent");
    if (focusTarget) focusTarget.focus();
    return modal;
  };

  Ik.closeModal = function () {
    const root = document.getElementById("modal-root");
    if (!root) return;
    root.hidden = true;
    root.innerHTML = "";
    if (modalCleanup) modalCleanup();
    modalCleanup = null;
  };

  Ik.confirm = function ({ title, body, confirmLabel = "Confirm", tone = "accent", onConfirm }) {
    Ik.openModal(
      `<header class="modal__header"><h2>${Ik.escape(title)}</h2></header>
       <div class="modal__body">${body}</div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--${tone}" type="button" data-confirm>${Ik.escape(confirmLabel)}</button>
       </footer>`,
      {
        onMount(modal) {
          modal.querySelector("[data-confirm]").addEventListener("click", () => {
            const keepOpen = onConfirm && onConfirm(modal) === false;
            if (!keepOpen) Ik.closeModal();
          });
        },
      }
    );
  };

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-dropdown-toggle]");
    document.querySelectorAll("[data-dropdown] .dropdown").forEach((menu) => {
      if (!toggle || !toggle.parentElement.contains(menu)) menu.hidden = true;
    });
    if (toggle) {
      const menu = toggle.parentElement.querySelector(".dropdown");
      menu.hidden = !menu.hidden;
    }

    if (event.target.closest("[data-sidebar-toggle]")) {
      document.getElementById("sidebar").classList.toggle("is-open");
    } else if (!event.target.closest("#sidebar")) {
      const sidebar = document.getElementById("sidebar");
      if (sidebar) sidebar.classList.remove("is-open");
    }

    const protoAction = event.target.closest("[data-prototype-note]");
    if (protoAction) {
      event.preventDefault();
      Ik.toast(protoAction.dataset.prototypeNote);
    }
  });
})();
