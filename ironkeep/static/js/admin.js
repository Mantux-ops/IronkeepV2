(function () {
  const esc = Ik.escape;

  document.querySelectorAll("[data-datetime]").forEach((node) => {
    node.textContent = Ik.formatDateTime(node.dataset.datetime);
  });

  const search = document.getElementById("guild-search");
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      document.querySelectorAll("#guild-table tbody tr").forEach((row) => {
        row.hidden = q && !row.dataset.search.includes(q);
      });
    });
  }

  function resolvePending(slug, approved) {
    document.querySelector(`[data-pending="${slug}"]`)?.remove();
    const cell = document.querySelector(`[data-row="${slug}"] [data-approval-cell]`);
    if (cell) {
      const setupDone = cell.dataset.setupComplete === "true";
      cell.innerHTML = !approved ? Ik.pill("Rejected", "grey") : setupDone ? Ik.pill("Active", "green") : Ik.pill("Setup not finished", "orange");
    }
    if (!document.querySelector("[data-pending]")) document.getElementById("pending-empty").hidden = false;
  }

  document.addEventListener("click", (event) => {
    const approve = event.target.closest("[data-approve]");
    if (approve) {
      const { approve: slug, name } = approve.dataset;
      Ik.confirm({
        title: `Approve ${name}?`,
        body: `<p>Ironkeep starts working in <strong>${esc(name)}</strong> as soon as the setup is complete. The person who added the bot gets a message in Discord.</p>`,
        confirmLabel: "Approve",
        tone: "green",
        onConfirm() {
          resolvePending(slug, true);
          Ik.toast(`${name} approved`);
        },
      });
      return;
    }

    const reject = event.target.closest("[data-reject]");
    if (reject) {
      const { reject: slug, name } = reject.dataset;
      Ik.confirm({
        title: `Reject ${name}?`,
        body: `<p>The bot leaves <strong>${esc(name)}</strong> and this environment is deleted after 30 days.</p>
               <label class="field"><span class="field__label">Message to the person who added the bot <span class="muted">(optional)</span></span>
               <textarea class="input textarea" rows="2" name="reason"></textarea></label>`,
        confirmLabel: "Reject and leave server",
        tone: "red",
        onConfirm() {
          resolvePending(slug, false);
          Ik.toast(`${name} rejected. The bot left the server.`);
        },
      });
    }
  });

  const lookup = document.getElementById("lookup");
  if (lookup) {
    const { records } = Ik.pageData();
    const result = document.getElementById("lookup-result");
    let deleted = new Set();

    function show(userId) {
      const found = records.filter((r) => r.user_id === userId && !deleted.has(r.user_id));
      if (!found.length) {
        result.innerHTML = `<div class="callout">${Ik.icon("info")}<div><p>Nothing stored for <span class="mono">${esc(userId)}</span>.</p></div></div>`;
        return;
      }
      const first = found[0];
      const observations = found.reduce((n, r) => n + r.timeline.filter((e) => e.type === "observation").length, 0);
      const events = found.reduce((n, r) => n + r.timeline.length, 0);
      result.innerHTML = `
        <div class="table-wrap">
          <table class="table table--cards">
            <thead><tr><th>Person</th><th>Guild</th><th>Trial</th><th class="num">Timeline entries</th><th class="num">Observations</th></tr></thead>
            <tbody>${found
              .map(
                (r) => `<tr>
                  <td data-label="Person"><span class="cell-user">${Ik.avatar(r.name, r.color, "sm")}<span><span class="cell-user__name">${esc(r.name)}</span><span class="cell-user__sub">@${esc(r.username)}</span></span></span></td>
                  <td data-label="Guild">${esc(r.guild)}</td>
                  <td data-label="Trial">${Ik.formatDate(r.start)}${r.verdict ? ` · ${esc(r.verdict)}` : " · open"}</td>
                  <td data-label="Timeline entries" class="num">${r.timeline.length}</td>
                  <td data-label="Observations" class="num">${r.timeline.filter((e) => e.type === "observation").length}</td>
                </tr>`
              )
              .join("")}</tbody>
          </table>
        </div>
        <div class="panel__actions">
          <span class="muted small">${events} timeline entries, ${observations} observations in ${found.length} guild${found.length > 1 ? "s" : ""}.</span>
          <span class="panel__actions-spacer"></span>
          <button class="button button--outline" type="button" data-export>${Ik.icon("download", 15)} Export as JSON</button>
          <button class="button button--red-outline" type="button" data-delete>${Ik.icon("trash", 15)} Delete everything</button>
        </div>`;

      result.querySelector("[data-export]").addEventListener("click", () => {
        const blob = new Blob([JSON.stringify({ discord_user_id: userId, exported_at: new Date().toISOString(), trials: found }, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `ironkeep-${userId}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
        Ik.toast("Export downloaded");
      });

      result.querySelector("[data-delete]").addEventListener("click", () => {
        Ik.confirm({
          title: `Delete all data for ${first.name}?`,
          body: `<p>This removes ${found.length} trial${found.length > 1 ? "s" : ""}, ${observations} observations and the full timeline from every guild. It can't be undone.</p>
                 <label class="field"><span class="field__label">Type the Discord user ID to confirm</span>
                 <input class="input mono" name="confirm" autocomplete="off"></label>`,
          confirmLabel: "Delete permanently",
          tone: "red",
          onConfirm(modal) {
            if (modal.querySelector("[name=confirm]").value.trim() !== userId) {
              modal.querySelector("[name=confirm]").focus();
              Ik.toast("The ID doesn't match", "red");
              return false;
            }
            deleted.add(userId);
            show(userId);
            Ik.toast(`All data for ${first.name} deleted`);
          },
        });
      });
    }

    lookup.addEventListener("submit", (event) => {
      event.preventDefault();
      const userId = new FormData(lookup).get("user_id").trim();
      if (userId) show(userId);
    });
    show(lookup.querySelector("[name=user_id]").value.trim());
  }
})();
