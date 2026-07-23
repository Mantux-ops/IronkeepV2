/* ==========================================================
   Visual Build Editor — Phase 12.2b
   app/static/js/build_editor.js

   Loaded by build_editor.html via <script src="..." defer>.
   defer guarantees the DOM is ready when this runs.

   Section index:
     §1  Constants and slot definitions
     §2  State — single source of truth
     §3  DOM references
     §4  Catalog client — fetch, cache, abort, retry
     §5  Grid — slot tile creation and update
     §6  Modal lifecycle — open, close, focus trap, focus restore
     §7  Filter chips — state sync, enable/disable per slot
     §8  Results — filter, render-limit, item cards, fallbacks
     §9  Item selection
    §10  Two-handed weapon logic
    §11  Slot removal — individual clear and reset-all
    §12  Loading / empty / error state helpers
    §13  Event wiring
    §14  Bootstrap
   ========================================================== */
'use strict';

/* §1 — Constants and slot definitions ───────────────────── */

const SLOT_DEFS = [
  { key: 'main_hand', label: 'Main Hand', area: 'main'   },
  { key: 'off_hand',  label: 'Off Hand',  area: 'off'    },
  { key: 'head',      label: 'Head',      area: 'head'   },
  { key: 'chest',     label: 'Chest',     area: 'chest'  },
  { key: 'shoes',     label: 'Shoes',     area: 'shoes'  },
  { key: 'cape',      label: 'Cape',      area: 'cape'   },
  { key: 'food',      label: 'Food',      area: 'food'   },
  { key: 'potion',    label: 'Potion',    area: 'potion' },
];

// Slots for which the two-handed / one-handed weapon-type filter is shown
const WEAPON_SLOTS = new Set(['main_hand', 'off_hand']);

// Maximum item cards rendered per query.
// main_hand has 1 096 catalog entries; rendering all at once is wasteful.
const RENDER_LIMIT = 100;

/* §2 — State — single source of truth ───────────────────── */

// Returns a fresh picker sub-state. Called on every openPicker().
function _defaultPickerState() {
  return {
    tiers:         new Set([7, 8]),
    enchantments:  new Set([0, 1, 2, 3]),
    handedness:    'any',   // 'any' | '1h' | '2h'
    query:         '',
    allItems:      [],      // raw catalog response for activeSlot
    availEnch:     new Set(),  // enchantments present in allItems
  };
}

const state = {
  // Ephemeral build contents — null means slot is empty
  slots: Object.fromEntries(SLOT_DEFS.map(s => [s.key, null])),
  // Key of the slot whose picker is currently open, or null
  activeSlot:     null,
  // Whether off_hand is locked because main_hand holds a 2H weapon
  offHandLocked:  false,
  // Picker filters and loaded data
  picker: _defaultPickerState(),
};

/* §3 — DOM references ───────────────────────────────────── */

const $ = id => document.getElementById(id);

const elGrid       = $('vbe-equip-grid');
const elBackdrop   = $('vbe-backdrop');
const elModal      = elBackdrop.querySelector('.vbe-modal');
const elClose      = $('vbe-close');
const elModalTitle = $('vbe-modal-title');
const elSearch     = $('vbe-search');
const elResults    = $('vbe-results');
const el2hGroup    = $('vbe-2h-filter-group');
const el2hChips    = $('vbe-2h-chips');
const elTierChips  = $('vbe-tier-chips');
const elEnchChips  = $('vbe-ench-chips');
const elNotice     = $('vbe-two-handed-notice');
const elResetBtn   = $('vbe-reset-btn');

/* §4 — Catalog client ───────────────────────────────────── */

const catalogClient = {
  // Slot-keyed cache. Once a slot's items are fetched they are never
  // re-fetched unless the caller invokes retry().
  _cache: {},
  // AbortController for the current in-flight request.
  _ctrl:  null,

  /**
   * Return catalog items for `slot`.
   * Resolves from cache when available; aborts any concurrent request first.
   * Returns null when the request was intentionally aborted (slot changed).
   * Throws for genuine network or server errors.
   */
  async load(slot) {
    if (this._cache[slot]) return this._cache[slot];

    // Cancel any previous in-flight request
    if (this._ctrl) {
      this._ctrl.abort();
      this._ctrl = null;
    }
    this._ctrl = new AbortController();

    const url = new URL('/api/catalog/items', location.origin);
    url.searchParams.set('slot', slot);

    let res;
    try {
      res = await fetch(url.toString(), { signal: this._ctrl.signal });
    } catch (err) {
      this._ctrl = null;
      if (err.name === 'AbortError') return null;
      throw new Error(`Network error: ${err.message}`);
    }

    this._ctrl = null;

    if (!res.ok) throw new Error(`Server error: HTTP ${res.status}`);

    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error('Invalid JSON response from catalog');
    }

    if (!Array.isArray(data)) throw new Error('Unexpected response format');

    this._cache[slot] = data;
    return data;
  },

  /** Evict the cache for `slot` then call load(). */
  async retry(slot) {
    delete this._cache[slot];
    return this.load(slot);
  },
};

/* §5 — Grid — slot tile creation and update ─────────────── */

function initGrid() {
  for (const def of SLOT_DEFS) {
    elGrid.appendChild(_createTile(def));
  }
}

function _createTile(def) {
  const btn = document.createElement('button');
  btn.type           = 'button';
  btn.id             = `vbe-slot-${def.key}`;
  btn.className      = 'vbe-slot';
  btn.style.gridArea = def.area;
  btn.dataset.slot   = def.key;
  btn.setAttribute('aria-label', `${def.label} — empty, click to select`);

  // ── Icon wrap (placeholder / real icon / badges)
  const iconWrap = document.createElement('div');
  iconWrap.className = 'vbe-slot__icon-wrap';

  const placeholder = document.createElement('div');
  placeholder.className = 'vbe-slot__placeholder';
  placeholder.setAttribute('aria-hidden', 'true');

  const img = document.createElement('img');
  img.className = 'vbe-slot__icon';
  img.alt       = '';
  img.hidden    = true;
  img.addEventListener('error', () => _onSlotIconError(img, placeholder));

  const badges    = document.createElement('div');
  badges.className = 'vbe-slot__badges';
  badges.hidden   = true;
  const tierBadge = document.createElement('span');
  tierBadge.className = 'vbe-tier-badge';
  const enchBadge = document.createElement('span');
  enchBadge.className = 'vbe-ench-badge';
  badges.appendChild(tierBadge);
  badges.appendChild(enchBadge);

  // ── Individual clear button (hidden until slot is filled)
  const clearBtn = document.createElement('button');
  clearBtn.type      = 'button';
  clearBtn.className = 'vbe-slot__clear';
  clearBtn.hidden    = true;
  clearBtn.setAttribute('aria-label', `Clear ${def.label}`);
  clearBtn.textContent = '✕';
  clearBtn.addEventListener('click', e => {
    e.stopPropagation(); // prevent opening the picker
    clearSlot(def.key);
  });

  iconWrap.appendChild(placeholder);
  iconWrap.appendChild(img);
  iconWrap.appendChild(badges);
  iconWrap.appendChild(clearBtn);

  const label = document.createElement('span');
  label.className   = 'vbe-slot__label';
  label.textContent = def.label;

  btn.appendChild(iconWrap);
  btn.appendChild(label);

  btn.addEventListener('click', () => {
    // aria-disabled blocks interaction for the locked off_hand tile
    if (btn.getAttribute('aria-disabled') === 'true') return;
    openPicker(def.key);
  });

  return btn;
}

// Called when a slot tile's icon fails to load — show placeholder instead
function _onSlotIconError(img, placeholder) {
  img.hidden         = true;
  placeholder.hidden = false;
}

function updateTile(slotKey, item) {
  const btn = $(`vbe-slot-${slotKey}`);
  if (!btn) return;
  const def       = SLOT_DEFS.find(s => s.key === slotKey);
  const ph        = btn.querySelector('.vbe-slot__placeholder');
  const img       = btn.querySelector('.vbe-slot__icon');
  const badges    = btn.querySelector('.vbe-slot__badges');
  const tierBadge = btn.querySelector('.vbe-tier-badge');
  const enchBadge = btn.querySelector('.vbe-ench-badge');
  const clearBtn  = btn.querySelector('.vbe-slot__clear');

  if (item) {
    ph.hidden             = true;
    img.src               = item.icon_url;
    img.alt               = item.display_name;
    img.hidden            = false;
    tierBadge.textContent = `T${item.tier}`;
    enchBadge.textContent = item.enchantment > 0 ? `.${item.enchantment}` : '';
    badges.hidden         = false;
    clearBtn.hidden       = false;
    btn.classList.add('vbe-slot--filled');
    btn.setAttribute('aria-label',
      `${def.label} — ${item.display_name} T${item.tier}.${item.enchantment}, click to change`);
  } else {
    ph.hidden        = false;
    img.hidden       = true;
    img.src          = '';
    badges.hidden    = true;
    clearBtn.hidden  = true;
    btn.classList.remove('vbe-slot--filled');
    btn.setAttribute('aria-label', `${def.label} — empty, click to select`);
  }
}

/* §6 — Modal lifecycle ──────────────────────────────────── */

// The slot tile that triggered openPicker(); focus returns here on close.
let _returnFocusTarget = null;

function openPicker(slotKey) {
  state.activeSlot      = slotKey;
  _returnFocusTarget    = $(`vbe-slot-${slotKey}`);

  const def = SLOT_DEFS.find(s => s.key === slotKey);
  elModalTitle.textContent = `Select — ${def.label}`;

  // Reset picker state; syncs chip UI to defaults
  state.picker = _defaultPickerState();
  _syncFilterUI();

  // Weapon-type filter only for weapon slots
  el2hGroup.hidden = !WEAPON_SLOTS.has(slotKey);

  // Show modal and lock body scroll
  elBackdrop.hidden = false;
  elBackdrop.removeAttribute('aria-hidden');
  document.body.style.overflow = 'hidden';

  // Two rAF calls: first paints the element, second applies the class
  // so the CSS transition actually fires.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => elBackdrop.classList.add('vbe-modal-backdrop--visible'))
  );

  // Loading state immediately (clears any stale result from a previous slot)
  _showLoading();

  catalogClient.load(slotKey).then(items => {
    // Guard: user may have closed the picker or switched slots while loading
    if (state.activeSlot !== slotKey || items === null) return;
    state.picker.allItems = items;
    state.picker.availEnch = new Set(items.map(i => i.enchantment));
    _applyAvailableEnchantments();
    renderResults();
    elSearch.focus({ preventScroll: true });
  }).catch(err => {
    if (state.activeSlot !== slotKey) return;
    _showError(`Failed to load items: ${err.message}`, () => _retryLoad(slotKey));
  });
}

function _retryLoad(slotKey) {
  _showLoading();
  catalogClient.retry(slotKey).then(items => {
    if (state.activeSlot !== slotKey || items === null) return;
    state.picker.allItems  = items;
    state.picker.availEnch = new Set(items.map(i => i.enchantment));
    _applyAvailableEnchantments();
    renderResults();
    elSearch.focus({ preventScroll: true });
  }).catch(err => {
    if (state.activeSlot !== slotKey) return;
    _showError(`Retry failed: ${err.message}`, () => _retryLoad(slotKey));
  });
}

function closePicker() {
  // Capture the return target before clearing it so the setTimeout can use it.
  // Focus is restored AFTER the backdrop receives display:none; restoring it
  // before causes the browser to reset focus back to body when the element
  // transitions to hidden.
  const returnTarget    = _returnFocusTarget;
  _returnFocusTarget    = null;

  elBackdrop.classList.remove('vbe-modal-backdrop--visible');
  document.body.style.overflow = '';

  setTimeout(() => {
    elBackdrop.hidden = true;
    elBackdrop.setAttribute('aria-hidden', 'true');
    state.activeSlot  = null;
    if (returnTarget) returnTarget.focus({ preventScroll: true });
  }, 200);
}

// Focus trap: keep Tab navigation inside the modal while it is open
const _FOCUSABLE = 'button:not([disabled]):not([hidden]), input:not([disabled]):not([hidden])';

function _trapFocus(e) {
  if (e.key !== 'Tab') return;

  const focusable = Array.from(elModal.querySelectorAll(_FOCUSABLE))
    .filter(el => !el.closest('[hidden]') && !el.hidden);

  if (focusable.length === 0) return;

  const first = focusable[0];
  const last  = focusable[focusable.length - 1];

  if (e.shiftKey) {
    if (document.activeElement === first) {
      e.preventDefault();
      last.focus();
    }
  } else {
    if (document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
}

/* §7 — Filter chips — state sync, enable/disable ──────── */

function _syncFilterUI() {
  elTierChips.querySelectorAll('[data-tier]').forEach(btn => {
    const t = parseInt(btn.dataset.tier, 10);
    btn.classList.toggle('vbe-chip--active', state.picker.tiers.has(t));
    btn.disabled = false;
    btn.classList.remove('vbe-chip--unavailable');
  });
  elEnchChips.querySelectorAll('[data-ench]').forEach(btn => {
    const en = parseInt(btn.dataset.ench, 10);
    btn.classList.toggle('vbe-chip--active', state.picker.enchantments.has(en));
    btn.disabled = false;
    btn.classList.remove('vbe-chip--unavailable');
  });
  el2hChips.querySelectorAll('[data-2h]').forEach(btn => {
    btn.classList.toggle('vbe-chip--active', btn.dataset['2h'] === state.picker.handedness);
  });
  elSearch.value = state.picker.query;
}

// After loading items, disable enchantment chips that don't exist for this slot.
// Example: mount only has enchantment 0 — chips .1/.2/.3 are disabled.
function _applyAvailableEnchantments() {
  const avail = state.picker.availEnch;
  elEnchChips.querySelectorAll('[data-ench]').forEach(btn => {
    const en        = parseInt(btn.dataset.ench, 10);
    const available = avail.has(en);
    btn.disabled    = !available;
    btn.classList.toggle('vbe-chip--unavailable', !available);
    if (!available) {
      state.picker.enchantments.delete(en);
      btn.classList.remove('vbe-chip--active');
    }
  });
}

function initFilterChips() {
  // Tier chips — toggle, at least one must stay active
  elTierChips.addEventListener('click', e => {
    const btn = e.target.closest('[data-tier]');
    if (!btn || btn.disabled) return;
    const t = parseInt(btn.dataset.tier, 10);
    if (state.picker.tiers.has(t)) {
      if (state.picker.tiers.size === 1) return;
      state.picker.tiers.delete(t);
      btn.classList.remove('vbe-chip--active');
    } else {
      state.picker.tiers.add(t);
      btn.classList.add('vbe-chip--active');
    }
    renderResults();
  });

  // Enchantment chips — toggle, at least one must stay active
  elEnchChips.addEventListener('click', e => {
    const btn = e.target.closest('[data-ench]');
    if (!btn || btn.disabled) return;
    const en = parseInt(btn.dataset.ench, 10);
    if (state.picker.enchantments.has(en)) {
      if (state.picker.enchantments.size === 1) return;
      state.picker.enchantments.delete(en);
      btn.classList.remove('vbe-chip--active');
    } else {
      state.picker.enchantments.add(en);
      btn.classList.add('vbe-chip--active');
    }
    renderResults();
  });

  // Handedness chips — radio-like single selection
  el2hChips.addEventListener('click', e => {
    const btn = e.target.closest('[data-2h]');
    if (!btn) return;
    state.picker.handedness = btn.dataset['2h'];
    el2hChips.querySelectorAll('[data-2h]').forEach(c =>
      c.classList.toggle('vbe-chip--active', c === btn)
    );
    renderResults();
  });
}

/* §8 — Results — filter, render-limit, item cards ──────── */

function _getFilteredItems() {
  const { tiers, enchantments, handedness, query, allItems } = state.picker;
  const words = query.trim().toLowerCase().replace(/\s+/g, ' ')
    .split(' ').filter(Boolean);

  return allItems.filter(item => {
    if (!tiers.has(item.tier))               return false;
    if (!enchantments.has(item.enchantment)) return false;
    if (handedness === '1h' &&  item.is_two_handed) return false;
    if (handedness === '2h' && !item.is_two_handed) return false;
    if (words.length > 0) {
      const name = item.display_name.toLowerCase();
      if (!words.every(w => name.includes(w))) return false;
    }
    return true;
  });
}

function renderResults() {
  elResults.innerHTML = '';

  // allItems is empty only when loading failed silently (should not happen
  // under normal conditions; the error path shows an error state instead).
  if (state.picker.allItems.length === 0 && !state.activeSlot) return;

  const filtered = _getFilteredItems();

  if (filtered.length === 0) {
    _showEmpty();
    return;
  }

  const truncated = filtered.length > RENDER_LIMIT;
  const toRender  = truncated ? filtered.slice(0, RENDER_LIMIT) : filtered;

  const frag = document.createDocumentFragment();
  for (const item of toRender) {
    frag.appendChild(_createItemCard(item));
  }

  if (truncated) {
    const notice = document.createElement('p');
    notice.className   = 'vbe-results-limit';
    notice.textContent =
      `Showing ${RENDER_LIMIT} of ${filtered.length} — refine your search to see more.`;
    frag.appendChild(notice);
  }

  elResults.appendChild(frag);
}

function _createItemCard(item) {
  const card = document.createElement('button');
  card.type      = 'button';
  card.className = 'vbe-item-card';
  card.setAttribute('role', 'listitem');

  const tierLabel = `T${item.tier}${item.enchantment > 0 ? '.' + item.enchantment : ''}`;
  card.setAttribute('aria-label',
    `${item.display_name} ${tierLabel}${item.is_two_handed ? ', two-handed' : ''}`);

  // Icon with error fallback
  const img = document.createElement('img');
  img.className = 'vbe-item-card__icon';
  img.src       = item.icon_url;
  img.alt       = '';
  img.loading   = 'lazy';
  img.addEventListener('error', () => _onCardIconError(img));

  // Text body
  const body = document.createElement('div');
  body.className = 'vbe-item-card__body';

  const nameEl = document.createElement('span');
  nameEl.className   = 'vbe-item-card__name';
  nameEl.textContent = item.display_name;

  const meta = document.createElement('div');
  meta.className = 'vbe-item-card__meta';

  const tb = document.createElement('span');
  tb.className   = 'vbe-tier-badge';
  tb.textContent = tierLabel;
  meta.appendChild(tb);

  if (item.is_two_handed) {
    const tag = document.createElement('span');
    tag.className   = 'vbe-2h-tag';
    tag.textContent = '2H';
    meta.appendChild(tag);
  }

  body.appendChild(nameEl);
  body.appendChild(meta);
  card.appendChild(img);
  card.appendChild(body);

  card.addEventListener('click', () => selectItem(item));
  return card;
}

// Called when an item card's icon fails to load — replace with a placeholder div
function _onCardIconError(img) {
  const fallback = document.createElement('div');
  fallback.className = 'vbe-item-card__icon-fallback';
  fallback.setAttribute('aria-hidden', 'true');
  img.parentNode.insertBefore(fallback, img);
  img.remove();
}

/* §9 — Item selection ───────────────────────────────────── */

function selectItem(item) {
  const slotKey = state.activeSlot;
  if (!slotKey) return;
  state.slots[slotKey] = item;
  updateTile(slotKey, item);
  if (slotKey === 'main_hand') {
    applyTwoHandedLogic(item);
  }
  closePicker();
}

/* §10 — Two-handed weapon logic ─────────────────────────── */

function applyTwoHandedLogic(weaponItem) {
  const shouldLock = !!(weaponItem && weaponItem.is_two_handed);
  state.offHandLocked = shouldLock;

  const offBtn = $('vbe-slot-off_hand');
  if (!offBtn) return;

  if (shouldLock) {
    // Clear and lock off_hand
    state.slots['off_hand'] = null;
    updateTile('off_hand', null);
    offBtn.setAttribute('aria-disabled', 'true');
    offBtn.classList.add('vbe-slot--disabled');
    elNotice.hidden = false;
  } else {
    offBtn.removeAttribute('aria-disabled');
    offBtn.classList.remove('vbe-slot--disabled');
    elNotice.hidden = true;
  }
}

/* §11 — Slot removal ────────────────────────────────────── */

function clearSlot(slotKey) {
  state.slots[slotKey] = null;
  updateTile(slotKey, null);
  // Clearing main_hand also unlocks off_hand if it was locked
  if (slotKey === 'main_hand') {
    applyTwoHandedLogic(null);
  }
}

function resetAllSlots() {
  for (const def of SLOT_DEFS) {
    state.slots[def.key] = null;
    updateTile(def.key, null);
  }
  applyTwoHandedLogic(null);
}

/* §12 — Loading / empty / error state helpers ───────────── */

function _showLoading() {
  elResults.innerHTML = '';
  const p = document.createElement('p');
  p.className = 'vbe-loading';
  p.setAttribute('role', 'status');
  p.textContent = 'Loading…';
  elResults.appendChild(p);
}

function _showEmpty() {
  elResults.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'vbe-state-wrap';

  const p = document.createElement('p');
  p.className   = 'vbe-empty';
  p.textContent = 'No items match your filters.';
  wrap.appendChild(p);

  // Offer a reset button when the empty state is caused by active filters
  const hasFilter = (
    state.picker.tiers.size < 2         ||
    state.picker.enchantments.size < state.picker.availEnch.size ||
    state.picker.handedness !== 'any'   ||
    state.picker.query.trim() !== ''
  );

  if (hasFilter) {
    const btn = document.createElement('button');
    btn.type        = 'button';
    btn.className   = 'btn btn-sm btn-ghost';
    btn.textContent = 'Reset filters';
    btn.addEventListener('click', () => {
      state.picker.tiers        = new Set([7, 8]);
      state.picker.enchantments = new Set(state.picker.availEnch);
      state.picker.handedness   = 'any';
      state.picker.query        = '';
      elSearch.value            = '';
      _syncFilterUI();
      _applyAvailableEnchantments();
      renderResults();
    });
    wrap.appendChild(btn);
  }

  elResults.appendChild(wrap);
}

function _showError(msg, onRetry) {
  elResults.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'vbe-state-wrap';

  const p = document.createElement('p');
  p.className   = 'vbe-error';
  p.textContent = msg;
  wrap.appendChild(p);

  const btn = document.createElement('button');
  btn.type        = 'button';
  btn.className   = 'btn btn-sm';
  btn.textContent = 'Retry';
  btn.addEventListener('click', onRetry);
  wrap.appendChild(btn);

  elResults.appendChild(wrap);
}

/* §13 — Event wiring ────────────────────────────────────── */

function initEvents() {
  // Close button
  elClose.addEventListener('click', closePicker);

  // Clicking the backdrop itself (not the modal panel) closes the picker
  elBackdrop.addEventListener('mousedown', e => {
    if (e.target === elBackdrop) closePicker();
  });

  // Keyboard: Escape closes; Tab is trapped inside the modal
  document.addEventListener('keydown', e => {
    if (!state.activeSlot) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closePicker();
    } else if (e.key === 'Tab') {
      _trapFocus(e);
    }
  });

  // Live search — 110ms debounce
  let _debounce = null;
  elSearch.addEventListener('input', e => {
    state.picker.query = e.target.value;
    clearTimeout(_debounce);
    _debounce = setTimeout(renderResults, 110);
  });

  // Filter chips
  initFilterChips();

  // Reset-all button
  elResetBtn.addEventListener('click', resetAllSlots);
}

/* §14 — Bootstrap ───────────────────────────────────────── */

/* §15 — Phase 12.3: Save form integration ───────────────── */

/**
 * Serialize filled slots to a JSON array for the hidden form field.
 * Only the item_id and slot are sent; server re-derives all other fields
 * from the catalog (display_name, tier, enchantment, is_two_handed).
 */
function serializeSlots() {
  const items = [];
  for (const def of SLOT_DEFS) {
    const item = state.slots[def.key];
    if (item) {
      items.push({
        slot:       def.key,
        item_id:    item.item_id,
        is_primary: true,
      });
    }
  }
  return JSON.stringify(items);
}

/**
 * Load initial slot items into state and update all tiles.
 * Called in edit mode from data embedded in a <script type="application/json">
 * tag with id="vbe-initial-slots".
 */
function loadInitialSlots() {
  const el = document.getElementById('vbe-initial-slots');
  if (!el) return;

  let items;
  try {
    items = JSON.parse(el.textContent);
  } catch (e) {
    console.error('[VBE] Failed to parse initial slots JSON:', e);
    return;
  }

  if (!Array.isArray(items)) return;

  for (const item of items) {
    const def = SLOT_DEFS.find(s => s.key === item.slot);
    if (!def) continue;
    state.slots[item.slot] = item;
  }

  // Re-render all tiles with loaded data
  for (const def of SLOT_DEFS) {
    updateTile(def.key, state.slots[def.key]);
  }

  // Apply two-handed logic if a 2H main weapon is loaded
  const mainItem = state.slots['main_hand'];
  if (mainItem && mainItem.is_two_handed) {
    state.offHandLocked = true;
    updateTile('off_hand', null);  // disable
    const tile = document.querySelector(`[data-slot="off_hand"]`);
    if (tile) {
      tile.classList.add('vbe-slot--disabled');
      tile.setAttribute('disabled', '');
      tile.setAttribute('aria-disabled', 'true');
    }
    if (elNotice) elNotice.removeAttribute('hidden');
  }
}

/**
 * Wire up the save form:
 * - On submit, serialize current slot state into the hidden JSON field.
 * - Prevent submission if the form is invalid per HTML5 constraints.
 */
function initSaveForm() {
  const form = document.getElementById('vbe-save-form');
  if (!form) return;

  form.addEventListener('submit', e => {
    const hiddenField = document.getElementById('vbe-slot-items-json');
    if (hiddenField) {
      hiddenField.value = serializeSlots();
    }
    // HTML5 validation handles required fields; no extra JS needed here.
  });
}

initGrid();
initEvents();
loadInitialSlots();
initSaveForm();
