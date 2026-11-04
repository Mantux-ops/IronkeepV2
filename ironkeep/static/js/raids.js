(function () {
  const data = Ik.pageData();
  if (!data) return;

  const PALETTE = ["#d97706", "#b91c1c", "#7e22ce", "#0284c7", "#0f766e", "#1d4ed8", "#b45309", "#be123c"];
  const byRaid = {};
  data.raids.forEach((raid) => {
    byRaid[raid.id] = [];
  });
  (data.signups || []).forEach((row) => {
    if (byRaid[row.raid_id]) byRaid[row.raid_id].push(row);
  });

  function color(id) {
    const number = Number(id);
    return PALETTE[(Number.isFinite(number) ? number : 0) % PALETTE.length];
  }

  function avatar(name, id) {
    const letter = Ik.escape((name || "?").slice(0, 1).toUpperCase());
    return `<span class="avatar avatar--sm" style="--avatar-color: ${color(id)}">${letter}</span>`;
  }

  function byName(a, b) {
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  }

  function personOf(userId) {
    return (data.people || []).find((item) => String(item.id) === String(userId));
  }

  function identityHtml(name, userId) {
    const main = (personOf(userId) || {}).main;
    if (!main) {
      return `<span class="raid-row__name"><span class="raid-row__title">${Ik.escape(name)}</span><span class="raid-row__sub">No character yet</span></span>`;
    }
    const color = Ik.escape(main.color);
    return `<span class="raid-row__name">
      <span class="raid-row__title" style="color:${color}"><span class="class-swatch" style="background:${color}"></span>${Ik.escape(main.name)}</span>
      <span class="raid-row__sub">${Ik.escape(name)} · ${Ik.escape(main.class_name)} · ${Ik.escape(main.role_name)}</span>
    </span>`;
  }

  function rowHtml(row, seat) {
    const next = seat === "roster" ? "reserve" : "roster";
    const label = seat === "roster" ? "Reserve" : "Raid";
    const user = Ik.escape(row.user_id);
    return `<div class="raid-row">
      ${avatar(row.name, row.user_id)}
      ${identityHtml(row.name, row.user_id)}
      <button class="button button--ghost button--sm" type="button" data-move="${next}" data-user="${user}">${label}</button>
      <button class="button button--ghost button--sm" type="button" data-move="off" data-user="${user}">Remove</button>
    </div>`;
  }

  function resultHtml(person) {
    const user = Ik.escape(person.id);
    return `<div class="raid-row">
      ${avatar(person.name, person.id)}
      ${identityHtml(person.name, person.id)}
      <button class="button button--outline button--sm" type="button" data-move="roster" data-user="${user}">Raid</button>
      <button class="button button--ghost button--sm" type="button" data-move="reserve" data-user="${user}">Reserve</button>
    </div>`;
  }

  function cardFor(raidId) {
    return document.querySelector(`[data-raid="${raidId}"]`);
  }

  function renderSearch(card, rows) {
    const input = card.querySelector("[data-search]");
    const box = card.querySelector("[data-results]");
    const query = input.value.trim().toLowerCase();
    if (!query) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    const taken = new Set(rows.map((row) => String(row.user_id)));
    const matches = data.people.filter((person) => {
      if (taken.has(String(person.id))) return false;
      return person.name.toLowerCase().includes(query);
    });
    box.hidden = false;
    if (!matches.length) {
      box.innerHTML = `<p class="muted small">No one matches.</p>`;
      return;
    }
    box.innerHTML = matches.slice(0, 8).map(resultHtml).join("");
  }

  function render(raidId) {
    const raid = data.raids.find((item) => item.id === raidId);
    const card = cardFor(raidId);
    if (!raid || !card) return;
    const rows = byRaid[raidId] || [];
    const roster = rows.filter((row) => row.seat === "roster").sort(byName);
    const reserve = rows.filter((row) => row.seat === "reserve").sort(byName);
    const count = card.querySelector("[data-count]");
    count.textContent = `${roster.length} / ${raid.size}`;
    count.classList.toggle("is-full", roster.length >= raid.size);
    card.querySelector("[data-reserve-count]").textContent = String(reserve.length);
    card.querySelector("[data-roster]").innerHTML = roster.length
      ? roster.map((row) => rowHtml(row, "roster")).join("")
      : `<p class="muted small">Nobody on this raid yet.</p>`;
    card.querySelector("[data-reserve]").innerHTML = reserve.length
      ? reserve.map((row) => rowHtml(row, "reserve")).join("")
      : `<p class="muted small">The reserve is empty.</p>`;
    renderSearch(card, rows);
  }

  async function save(raidId, userId, seat) {
    const card = cardFor(raidId);
    if (card && card.dataset.busy === "1") return;
    if (card) card.dataset.busy = "1";
    try {
      const response = await fetch(`/api/${data.slug}/raids/${raidId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, seat: seat }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        Ik.toast(body.error || "Could not update the raid", "red");
        return;
      }
      byRaid[raidId] = body.signups || [];
      render(raidId);
      if (seat === "roster") Ik.toast("On the raid");
      else if (seat === "reserve") Ik.toast("On the reserve");
      else Ik.toast("Removed from the raid");
    } catch (error) {
      Ik.toast("Could not reach Ironkeep", "red");
    } finally {
      if (card) delete card.dataset.busy;
    }
  }

  const grid = document.getElementById("raid-grid");
  grid.addEventListener("click", (event) => {
    const button = event.target.closest("[data-move]");
    if (!button) return;
    const card = button.closest("[data-raid]");
    const seat = button.dataset.move === "off" ? null : button.dataset.move;
    save(card.dataset.raid, button.dataset.user, seat);
  });
  grid.addEventListener("input", (event) => {
    if (!event.target.matches("[data-search]")) return;
    render(event.target.closest("[data-raid]").dataset.raid);
  });

  data.raids.forEach((raid) => render(raid.id));

  const keyField = document.getElementById("companion-key");
  const copyKey = document.getElementById("companion-copy");
  if (copyKey && keyField) {
    copyKey.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(keyField.value);
        Ik.toast("Key copied");
      } catch (error) {
        keyField.select();
        Ik.toast("Select the key and copy it");
      }
    });
  }
  const rotateKey = document.getElementById("companion-rotate");
  if (rotateKey) {
    rotateKey.addEventListener("click", () => {
      Ik.confirm({
        title: "New companion key",
        body: "The program keeps the old key until you paste this new one.",
        confirmLabel: "Make a new key",
        onConfirm() {
          const form = document.createElement("form");
          form.method = "post";
          form.action = `/api/${data.slug}/attendance/token`;
          document.body.appendChild(form);
          form.submit();
        },
      });
    });
  }
})();
