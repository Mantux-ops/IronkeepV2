(function () {
  const data = Ik.pageData();
  if (!data) return;

  const list = document.getElementById("character-list");
  const count = document.getElementById("character-count");
  const search = document.getElementById("character-search");
  const chips = Array.from(document.querySelectorAll(".member-filters [data-filter]"));
  let filter = "all";

  function personById(id) {
    return data.people.find((person) => String(person.id) === String(id));
  }

  function klassById(id) {
    return data.classes.find((klass) => klass.id === id);
  }

  function lineHtml(person, character) {
    const color = Ik.escape(character.color);
    const actions = [
      character.is_main
        ? ""
        : `<button class="button button--ghost button--sm" type="button" data-main="${character.id}">Make main</button>`,
      `<button class="button button--ghost button--sm" type="button" data-edit="${character.id}" data-user="${Ik.escape(person.id)}">Edit</button>`,
      `<button class="button button--ghost button--sm" type="button" data-remove="${character.id}" data-name="${Ik.escape(character.name)}">Remove</button>`,
    ].join("");
    return `<div class="character-line">
      <span class="class-swatch" style="background:${color}"></span>
      <span class="character-line__name" style="color:${color}">${Ik.escape(character.name)}</span>
      ${character.is_main ? '<span class="pill pill--accent">Main</span>' : '<span class="character-line__alt">Alt</span>'}
      <span class="character-line__meta">${Ik.escape(character.class_name)} · ${Ik.escape(character.spec_name)} · ${Ik.escape(character.role_name)}</span>
      <span class="character-line__actions">${actions}</span>
    </div>`;
  }

  function cardHtml(person) {
    const characters = person.characters || [];
    const body = characters.length
      ? characters.map((character) => lineHtml(person, character)).join("")
      : `<p class="muted small character-empty">No character yet.</p>`;
    const addLabel = characters.length ? "Add alt" : "Add character";
    const add = person.gone
      ? ""
      : `<button class="button button--ghost button--sm" type="button" data-add-for="${Ik.escape(person.id)}">${addLabel}</button>`;
    const handle = person.username ? `<span class="cell-user__sub">@${Ik.escape(person.username)}</span>` : "";
    return `<article class="card character-card" data-user="${Ik.escape(person.id)}">
      <div class="character-card__head">
        <span class="cell-user">${Ik.avatar(person.name, person.color, "sm")}
          <span>
            <span class="cell-user__name">${Ik.escape(person.label || person.name)}</span>
            ${handle}
          </span>
        </span>
        ${add}
      </div>
      <div class="character-lines">${body}</div>
    </article>`;
  }

  function matches(person) {
    const characters = person.characters || [];
    if (filter === "ready" && !characters.length) return false;
    if (filter === "missing" && characters.length) return false;
    const query = search ? search.value.trim().toLowerCase() : "";
    if (!query) return true;
    const blob = [person.name, person.username, person.label]
      .concat(characters.map((character) => `${character.name} ${character.class_name} ${character.spec_name}`))
      .join(" ")
      .toLowerCase();
    return blob.indexOf(query) !== -1;
  }

  function render() {
    const visible = data.people.filter(matches);
    const mains = data.people.reduce((sum, person) => sum + (person.characters || []).filter((character) => character.is_main).length, 0);
    const alts = data.people.reduce((sum, person) => sum + (person.characters || []).filter((character) => !character.is_main).length, 0);
    if (count) {
      const noun = mains === 1 ? "main" : "mains";
      const altNoun = alts === 1 ? "alt" : "alts";
      count.textContent = `${mains} ${noun} · ${alts} ${altNoun}`;
    }
    if (!visible.length) {
      list.innerHTML = `<section class="empty-state"><h2>${data.people.length ? "No one matches" : "No characters yet"}</h2><p>${data.people.length ? "Try another name, or clear the filter." : "Add a main for someone on the member list. Alts go on that same person."}</p></section>`;
      return;
    }
    list.innerHTML = visible.map(cardHtml).join("");
  }

  function roleOptions(selected) {
    return ["tank", "healer", "dps"].map((role) => {
      const label = role === "dps" ? "DPS" : role.charAt(0).toUpperCase() + role.slice(1);
      return `<option value="${role}"${role === selected ? " selected" : ""}>${label}</option>`;
    }).join("");
  }

  function openForm({ personId, character }) {
    const editing = Boolean(character);
    const person = personId ? personById(personId) : null;
    const lockedPerson = editing || Boolean(person);
    const memberChoices = data.people.filter((item) => !item.gone);
    const selectedId = character ? String(character.user_id) : person ? String(person.id) : "";
    const memberField = lockedPerson
      ? `<div class="field__value">${Ik.escape((personById(selectedId) || {}).label || selectedId)}</div><input type="hidden" name="user_id" value="${Ik.escape(selectedId)}">`
      : `<select class="input select" name="user_id">${memberChoices.map((item) => `<option value="${Ik.escape(item.id)}"${String(item.id) === selectedId ? " selected" : ""}>${Ik.escape(item.label || item.name)}</option>`).join("")}</select>`;
    const classId = character ? character.class_id : "";
    const classOptions = [`<option value="">Choose a class</option>`]
      .concat(data.classes.map((klass) => `<option value="${klass.id}"${klass.id === classId ? " selected" : ""}>${Ik.escape(klass.name)}</option>`))
      .join("");
    Ik.openModal(
      `<header class="modal__header"><h2>${editing ? "Edit character" : person && (person.characters || []).length ? "Add alt" : "Add character"}</h2></header>
       <div class="modal__body">
         <form id="character-form" autocomplete="off">
           <div class="field" style="margin-top:0">
             <span class="field__label">Discord member</span>
             ${memberField}
           </div>
           <div class="field">
             <label class="field__label" for="character-name">Character name</label>
             <input class="input" id="character-name" name="name" maxlength="12" value="${Ik.escape(character ? character.name : "")}" autofocus spellcheck="false" placeholder="2 to 12 letters">
           </div>
           <div class="field-row">
             <div class="field">
               <label class="field__label" for="character-class">Class</label>
               <select class="input select" id="character-class" name="class_id">${classOptions}</select>
             </div>
             <div class="field">
               <label class="field__label" for="character-spec">Spec</label>
               <select class="input select" id="character-spec" name="spec_id"></select>
             </div>
           </div>
           <div class="field">
             <label class="field__label" for="character-role">Role</label>
             <select class="input select" id="character-role" name="role">${roleOptions(character ? character.role : "dps")}</select>
             <span class="field__hint">Feral can be a tank or damage. The spec only picks a starting role.</span>
           </div>
           <label class="radio"><input type="checkbox" name="is_main" ${character && character.is_main ? "checked" : ""}>
             <span><strong>This is the main</strong><span class="muted small">The raid list uses the main. One person has one main.</span></span>
           </label>
         </form>
       </div>
       <footer class="modal__footer">
         <button class="button button--ghost" type="button" data-modal-close>Cancel</button>
         <button class="button button--accent" type="button" data-save>${editing ? "Save" : "Add"}</button>
       </footer>`,
      {
        onMount(modal) {
          const form = modal.querySelector("#character-form");
          const classSelect = form.querySelector("[name=class_id]");
          const specSelect = form.querySelector("[name=spec_id]");
          const roleSelect = form.querySelector("[name=role]");
          const mainBox = form.querySelector("[name=is_main]");
          const userInput = () => form.querySelector("[name=user_id]").value;

          function currentPerson() {
            return personById(userInput());
          }

          function fillSpecs(keepSaved) {
            const klass = klassById(classSelect.value);
            const specs = klass ? klass.specs : [];
            const previous = keepSaved && character ? character.spec_id : specSelect.value;
            specSelect.innerHTML = specs.map((spec) => `<option value="${spec.id}">${Ik.escape(spec.name)}</option>`).join("");
            specSelect.disabled = !specs.length;
            if (specs.some((spec) => spec.id === previous)) specSelect.value = previous;
            if (!keepSaved) {
              const spec = specs.find((item) => item.id === specSelect.value);
              if (spec) roleSelect.value = spec.role;
            }
          }

          function syncMain() {
            const owner = currentPerson();
            const others = ((owner && owner.characters) || []).filter((item) => !character || item.id !== character.id);
            const hasMain = others.some((item) => item.is_main);
            if (character && character.is_main) {
              mainBox.checked = true;
              mainBox.disabled = true;
              return;
            }
            if (!hasMain) {
              mainBox.checked = true;
              mainBox.disabled = true;
              return;
            }
            mainBox.disabled = false;
            if (!character) mainBox.checked = false;
          }

          classSelect.addEventListener("change", () => fillSpecs(false));
          specSelect.addEventListener("change", () => {
            const klass = klassById(classSelect.value);
            const spec = klass && klass.specs.find((item) => item.id === specSelect.value);
            if (spec) roleSelect.value = spec.role;
          });
          const userSelect = form.querySelector("select[name=user_id]");
          if (userSelect) userSelect.addEventListener("change", syncMain);
          fillSpecs(true);
          syncMain();

          modal.querySelector("[data-save]").addEventListener("click", async () => {
            const button = modal.querySelector("[data-save]");
            const payload = {
              user_id: userInput(),
              name: form.name.value,
              class_id: classSelect.value,
              spec_id: specSelect.value,
              role: roleSelect.value,
              is_main: mainBox.checked,
            };
            button.disabled = true;
            const saved = await send(editing ? `/api/${data.slug}/characters/${character.id}` : `/api/${data.slug}/characters`, "POST", payload);
            button.disabled = false;
            if (!saved) return;
            Ik.closeModal();
            Ik.toast(editing ? "Character saved" : payload.is_main ? "Main added" : "Alt added");
          });
        },
      }
    );
  }

  async function send(url, method, body) {
    try {
      const response = await fetch(url, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        Ik.toast(payload.error || "Could not save the character", "red");
        return null;
      }
      data.people = payload.people || [];
      render();
      return payload;
    } catch (error) {
      Ik.toast("Could not reach Ironkeep", "red");
      return null;
    }
  }

  list.addEventListener("click", (event) => {
    const add = event.target.closest("[data-add-for]");
    if (add) {
      openForm({ personId: add.dataset.addFor });
      return;
    }
    const edit = event.target.closest("[data-edit]");
    if (edit) {
      const person = personById(edit.dataset.user);
      const character = person && (person.characters || []).find((item) => String(item.id) === edit.dataset.edit);
      if (character) openForm({ personId: person.id, character });
      return;
    }
    const main = event.target.closest("[data-main]");
    if (main) {
      send(`/api/${data.slug}/characters/${main.dataset.main}/main`, "POST").then((saved) => {
        if (saved) Ik.toast("Main updated");
      });
      return;
    }
    const remove = event.target.closest("[data-remove]");
    if (remove) {
      Ik.confirm({
        title: `Remove ${remove.dataset.name}?`,
        body: "<p>The character leaves this guild list. If it was the main, the oldest alt becomes the main.</p>",
        confirmLabel: "Remove",
        tone: "red",
        onConfirm() {
          send(`/api/${data.slug}/characters/${remove.dataset.remove}`, "DELETE").then((saved) => {
            if (saved) Ik.toast("Character removed");
          });
        },
      });
    }
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      filter = chip.dataset.filter;
      chips.forEach((item) => {
        const active = item === chip;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", active ? "true" : "false");
      });
      render();
    });
  });
  if (search) search.addEventListener("input", render);
  document.getElementById("add-character").addEventListener("click", () => openForm({}));

  render();
})();
