(function () {
  const table = document.getElementById("roster-table");
  const search = document.getElementById("roster-search");
  const classFilter = document.getElementById("roster-class");
  const rankFilter = document.getElementById("roster-rank");
  const count = document.getElementById("roster-count");
  const empty = document.getElementById("roster-none");
  if (!table || !search || !classFilter || !rankFilter || !count || !empty) return;

  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const total = rows.length;
  let sortKey = "name";
  let sortDir = 1;

  function fold(value) {
    return String(value || "").toLocaleLowerCase();
  }

  function matches(row) {
    if (classFilter.value && row.dataset.classToken !== classFilter.value) return false;
    if (rankFilter.value && row.dataset.rank !== rankFilter.value) return false;
    const query = fold(search.value.trim());
    if (!query) return true;
    const haystack = [row.dataset.name, row.dataset.className, row.dataset.classToken, row.dataset.rank]
      .map(fold)
      .join("\n");
    return haystack.includes(query);
  }

  function compare(a, b) {
    let result;
    if (sortKey === "level") {
      result = (Number(a.dataset.level) || 0) - (Number(b.dataset.level) || 0);
    } else {
      const left = sortKey === "class" ? a.dataset.className : sortKey === "rank" ? a.dataset.rank : a.dataset.name;
      const right = sortKey === "class" ? b.dataset.className : sortKey === "rank" ? b.dataset.rank : b.dataset.name;
      result = String(left || "").localeCompare(String(right || ""), undefined, { sensitivity: "base" });
    }
    if (result === 0) result = String(a.dataset.name || "").localeCompare(String(b.dataset.name || ""), undefined, { sensitivity: "base" });
    if (result === 0) result = String(a.dataset.guid || "").localeCompare(String(b.dataset.guid || ""));
    return result * sortDir;
  }

  function updateSort() {
    table.querySelectorAll("th[data-sort]").forEach((header) => {
      const active = header.dataset.sort === sortKey;
      header.classList.toggle("is-sorted", active);
      header.setAttribute("aria-sort", active ? (sortDir > 0 ? "ascending" : "descending") : "none");
      if (active) header.dataset.dir = sortDir > 0 ? "asc" : "desc";
      else delete header.dataset.dir;
    });
  }

  function render() {
    const visible = rows.filter(matches).sort(compare);
    const hidden = rows.filter((row) => visible.indexOf(row) === -1);
    visible.forEach((row) => {
      row.hidden = false;
      tbody.appendChild(row);
    });
    hidden.forEach((row) => {
      row.hidden = true;
      tbody.appendChild(row);
    });
    count.textContent = visible.length + " of " + total + " characters";
    empty.hidden = visible.length !== 0;
    updateSort();
  }

  search.addEventListener("input", render);
  classFilter.addEventListener("change", render);
  rankFilter.addEventListener("change", render);
  table.querySelectorAll("th[data-sort] button").forEach((button) => {
    button.addEventListener("click", () => {
      const header = button.closest("th");
      const key = header.dataset.sort;
      if (key === sortKey) sortDir = -sortDir;
      else {
        sortKey = key;
        sortDir = 1;
      }
      render();
    });
  });

  render();
})();
