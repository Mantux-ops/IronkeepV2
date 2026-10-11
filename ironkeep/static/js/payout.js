(function () {
  const data = Ik.pageData();
  if (!data || !data.payout) return;
  const payout = data.payout;
  const esc = Ik.escape;

  function silver(amount, withSign) {
    const abs = Math.abs(Math.round(amount)).toLocaleString("nl-NL");
    if (!withSign) return abs;
    if (amount > 0) return "+" + abs;
    if (amount < 0) return "−" + abs;
    return abs;
  }

  function shortSilver(amount) {
    const sign = amount < 0 ? "−" : "";
    const abs = Math.abs(amount);
    if (abs >= 1_000_000) {
      const millions = abs / 1_000_000;
      const text = millions.toLocaleString("nl-NL", { maximumFractionDigits: 1 });
      return sign + text + "M";
    }
    return sign + silver(abs, false);
  }

  function parseAmount(raw) {
    if (!raw) return 0;
    let text = String(raw).trim().toLowerCase().replace(/\s/g, "");
    let mult = 1;
    if (/[km]$/.test(text)) {
      const suffix = text.slice(-1);
      text = text.slice(0, -1);
      mult = suffix === "m" ? 1_000_000 : 1_000;
    }
    if (mult > 1) {
      const value = parseFloat(text.replace(",", "."));
      return Number.isNaN(value) ? 0 : Math.round(value * mult);
    }
    const digits = text.replace(/[.,]/g, "");
    const value = parseInt(digits, 10);
    return Number.isNaN(value) ? 0 : value;
  }

  function share(total, count, pct) {
    if (!count || !pct) return 0;
    return Math.floor(((total / count) * (pct / 100)) / 1000) * 1000;
  }

  function stateName(key) {
    if (key === "repaired") return "Repaired";
    if (key === "niet") return "Niet repaired";
    return "";
  }

  function kindLabel(kind) {
    if (kind === "lootsplit") return "Lootsplit";
    if (kind === "payout") return "Payout";
    if (kind === "fine") return "Fine";
    return "Other";
  }

  if (data.page === "member") renderMember();
  if (data.page === "officer") renderOfficer();

  function renderMember() {
    const rows = payout.mutations || [];
    if (!rows.length) {
      document.getElementById("payout-stats").innerHTML = [
        stat("Open balance", "—", "grey"),
        stat("Since last payout", "—", "grey"),
        stat("Pickup from", "—", "grey"),
      ].join("");
      const callout = document.getElementById("payout-callout");
      callout.className = "callout";
      callout.innerHTML = "<div><strong>Nothing to show yet.</strong><p>When payouts are connected, this page shows your own balance, the lootsplits you were in, and your mutations.</p></div>";
      document.getElementById("loot-cards").innerHTML = '<p class="muted">No lootsplits yet.</p>';
      document.getElementById("mut-rows").innerHTML = '<tr><td colspan="4" class="muted">No mutations yet.</td></tr>';
      return;
    }
    const open = rows.reduce((sum, row) => sum + row.amount, 0);
    const lastPayout = rows.find((row) => row.kind === "payout");
    const since = lastPayout
      ? rows.filter((row) => row.date > lastPayout.date).reduce((sum, row) => sum + row.amount, 0)
      : open;
    const ready = open >= payout.threshold;

    document.getElementById("payout-stats").innerHTML = [
      stat("Open balance", shortSilver(open) + " silver", ready ? "green" : "orange"),
      stat("Since last payout", shortSilver(since) + " silver", "accent"),
      stat("Pickup from", shortSilver(payout.threshold) + " silver", "grey"),
    ].join("");

    const callout = document.getElementById("payout-callout");
    callout.className = ready ? "callout callout--accent" : "callout";
    callout.innerHTML = ready
      ? "<div><strong>You can collect this.</strong><p>Your open balance is above " + shortSilver(payout.threshold) + " silver. An officer pays it out; this page only shows your own lines.</p></div>"
      : "<div><strong>Not at the pickup line yet.</strong><p>Payouts are collected from " + shortSilver(payout.threshold) + " silver. You are at " + shortSilver(open) + ".</p></div>";

    document.getElementById("loot-cards").innerHTML = rows
      .filter((row) => row.kind === "lootsplit")
      .map((row) => {
        const label = stateName(row.state) + " (" + row.pct + "%)";
        return `<article class="loot-card">
          <div>
            <strong>${esc(Ik.formatDate(row.date))}</strong>
            <p class="muted small">${esc(label)} · with ${row.people - 1} others</p>
          </div>
          <span class="silver silver--plus">${silver(row.amount, true)}</span>
        </article>`;
      })
      .join("");

    const filters = [
      ["all", "All"],
      ["lootsplit", "Lootsplit"],
      ["payout", "Payout"],
      ["fine", "Fine"],
      ["other", "Other"],
    ];
    const bar = document.getElementById("mut-filters");
    let current = "all";
    bar.innerHTML = filters
      .map(([key, label]) => `<button class="chip ${key === "all" ? "is-active" : ""}" type="button" data-kind="${key}">${label}</button>`)
      .join("");

    function draw() {
      const visible = rows.filter((row) => current === "all" || row.kind === current);
      document.getElementById("mut-rows").innerHTML = visible
        .map((row) => {
          const tone = row.amount < 0 ? "silver--minus" : "silver--plus";
          return `<tr>
            <td data-label="Date">${esc(Ik.formatDate(row.date))}</td>
            <td data-label="What">${esc(kindLabel(row.kind))}</td>
            <td data-label="Amount"><span class="silver ${tone}">${silver(row.amount, true)}</span></td>
            <td data-label="Note">${esc(row.note)}</td>
          </tr>`;
        })
        .join("");
    }

    bar.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-kind]");
      if (!chip) return;
      current = chip.dataset.kind;
      bar.querySelectorAll(".chip").forEach((item) => item.classList.toggle("is-active", item === chip));
      draw();
    });
    draw();
  }

  function stat(label, value, tone) {
    return `<div class="stat-card stat-card--${tone}">
      <span class="stat-card__body">
        <span class="stat-card__label">${esc(label)}</span>
        <span class="stat-card__value">${esc(value)}</span>
      </span>
    </div>`;
  }

  function renderOfficer() {
    const splits = payout.splits.map((split) => Object.assign({}, split, { people: split.people.slice() }));
    let state = "";
    let picked = new Set();
    let editing = -1;

    const market = document.getElementById("market");
    const bags = document.getElementById("bags");
    const note = document.getElementById("note");
    const who = document.getElementById("who");
    const fine = document.getElementById("fine");
    const finePct = document.getElementById("fine-pct");
    const fineNote = document.getElementById("fine-note");
    const fineFields = document.getElementById("fine-fields");
    const book = document.getElementById("book");
    const cancel = document.getElementById("cancel-edit");

    function selectedState() {
      document.querySelectorAll(".loot-opt").forEach((button) => {
        button.classList.toggle("is-on", button.dataset.state === state);
      });
    }

    function rosterEntries() {
      return (payout.roster || []).map((item) => (typeof item === "string" ? { id: item, name: item } : item));
    }

    function drawRoster() {
      const query = who.value.trim().toLowerCase();
      const entries = rosterEntries();
      if (!entries.length) {
        document.getElementById("roster").innerHTML = '<p class="muted small">' + esc(payout.rosterHint || "Choose the roles for this list under Settings → Roles → Lootsplit names.") + "</p>";
        document.getElementById("picked").innerHTML = "";
        return;
      }
      const visible = entries.filter((item) => !query || item.name.toLowerCase().includes(query));
      document.getElementById("roster").innerHTML = visible.length
        ? visible.map((item) => `<label class="loot-person"><input type="checkbox" value="${esc(item.id)}" ${picked.has(item.id) ? "checked" : ""}> ${esc(item.name)}</label>`).join("")
        : '<p class="muted small">No names match.</p>';
      const byId = Object.fromEntries(entries.map((item) => [item.id, item.name]));
      document.getElementById("picked").innerHTML = Array.from(picked)
        .filter((id) => byId[id])
        .map((id) => `<button class="chip" type="button" data-remove="${esc(id)}">${esc(byId[id])} <span aria-hidden="true">×</span></button>`)
        .join("");
    }

    function drawPreview() {
      const total = parseAmount(market.value) + parseAmount(bags.value);
      const count = picked.size;
      const pct = state ? payout.pct[state] : 0;
      const each = share(total, count, pct);
      const raw = document.getElementById("raw-line");
      raw.textContent = total > 0 ? "Raw value " + silver(total, false) + " silver" : "Raw value shows up once both fields have a number.";
      const preview = document.getElementById("preview");
      if (!payout.sample || !state || !count || each <= 0) {
        preview.hidden = !state || !count || each <= 0;
        book.disabled = true;
        if (!(!state || !count || each <= 0)) {
          const booked = each * count;
          preview.textContent = count + " × " + silver(each, false) + " = " + silver(booked, false) + " silver · " + stateName(state) + " (" + pct + "%)";
        }
        return;
      }
      const booked = each * count;
      let text = count + " × " + silver(each, false) + " = " + silver(booked, false) + " silver · " + stateName(state) + " (" + pct + "%)";
      if (fine.checked) {
        const pctFine = Number(String(finePct.value).replace(",", ".")) || 0;
        const eachFine = share(total, count, pctFine);
        text += " · Fine " + count + " × −" + silver(eachFine, false);
      }
      preview.hidden = false;
      preview.textContent = text;
      book.disabled = false;
    }

    function drawSplits() {
      if (!splits.length) {
        document.getElementById("split-list").innerHTML = '<p class="muted">No splits yet.</p>';
        return;
      }
      document.getElementById("split-list").innerHTML = splits
        .map((split, index) => {
          const total = split.market + split.bags;
          const each = share(total, split.people.length, payout.pct[split.state]);
          const when = Ik.formatDate(split.date.slice(0, 10)) + " · " + split.date.slice(11, 16);
          return `<button class="split-row ${index === editing ? "is-on" : ""}" type="button" data-edit="${index}">
            <span>
              <strong>${esc(when)}</strong>
              <span class="muted small">${esc(stateName(split.state))} (${payout.pct[split.state]}%) · ${split.people.length} people</span>
            </span>
            <span class="silver silver--plus">${silver(each, true)}</span>
          </button>`;
        })
        .join("");
    }

    function resetForm() {
      editing = -1;
      state = "";
      picked = new Set();
      market.value = "";
      bags.value = "";
      note.value = "";
      fine.checked = false;
      finePct.value = String(payout.fine_pct);
      fineNote.value = "Boete - onjuiste lootsplit";
      fineFields.hidden = true;
      who.value = "";
      document.getElementById("form-title").textContent = "New split";
      document.getElementById("form-msg").textContent = payout.sample ? "" : "Booking is off until payouts are connected.";
      book.textContent = "Book split";
      cancel.hidden = true;
      selectedState();
      drawRoster();
      drawPreview();
      drawSplits();
    }

    document.querySelector(".loot-opts").addEventListener("click", (event) => {
      const button = event.target.closest("[data-state]");
      if (!button) return;
      state = state === button.dataset.state ? "" : button.dataset.state;
      selectedState();
      drawPreview();
    });

    document.getElementById("roster").addEventListener("change", (event) => {
      const box = event.target;
      if (!box.value) return;
      if (box.checked) picked.add(box.value);
      else picked.delete(box.value);
      drawRoster();
      drawPreview();
    });

    document.getElementById("picked").addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove]");
      if (!button) return;
      picked.delete(button.dataset.remove);
      drawRoster();
      drawPreview();
    });

    [market, bags, finePct].forEach((input) => input.addEventListener("input", drawPreview));
    who.addEventListener("input", drawRoster);
    fine.addEventListener("change", () => {
      fineFields.hidden = !fine.checked;
      drawPreview();
    });

    book.addEventListener("click", () => {
      if (!payout.sample) return;
      const total = parseAmount(market.value) + parseAmount(bags.value);
      const entry = {
        date: new Date().toISOString().slice(0, 16),
        state: state,
        market: parseAmount(market.value),
        bags: parseAmount(bags.value),
        people: Array.from(picked),
        note: note.value.trim(),
        fine: fine.checked,
      };
      if (editing >= 0) splits[editing] = entry;
      else splits.unshift(entry);
      const each = share(total, entry.people.length, payout.pct[state]);
      document.getElementById("form-msg").textContent = editing >= 0
        ? "Updated in this mockup. The sheet was not touched."
        : "Booked " + entry.people.length + " × " + silver(each, false) + " in this mockup. The sheet was not touched.";
      Ik.toast(editing >= 0 ? "Split updated in the mockup" : "Split booked in the mockup");
      const keepMessage = document.getElementById("form-msg").textContent;
      resetForm();
      document.getElementById("form-msg").textContent = keepMessage;
    });

    cancel.addEventListener("click", resetForm);

    document.getElementById("split-list").addEventListener("click", (event) => {
      const button = event.target.closest("[data-edit]");
      if (!button) return;
      const split = splits[Number(button.dataset.edit)];
      editing = Number(button.dataset.edit);
      state = split.state;
      picked = new Set(split.people);
      market.value = silver(split.market, false);
      bags.value = silver(split.bags, false);
      note.value = split.note || "";
      fine.checked = !!split.fine;
      fineFields.hidden = !split.fine;
      if (split.fine_pct) finePct.value = String(split.fine_pct);
      document.getElementById("form-title").textContent = "Edit this split";
      document.getElementById("form-msg").textContent = "";
      book.textContent = "Save split";
      cancel.hidden = false;
      selectedState();
      drawRoster();
      drawPreview();
      drawSplits();
    });

    resetForm();
  }
})();
