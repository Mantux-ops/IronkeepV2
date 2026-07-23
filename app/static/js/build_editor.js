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

// Equipment slot -> spell field-key prefix (mirrors app/albion/spell_catalog.py).
// Only these slots carry spells; order defines display order of spell groups.
const SPELL_SLOT_PREFIX = {
  main_hand: 'weapon',
  off_hand:  'offhand',
  head:      'head',
  chest:     'chest',
  shoes:     'shoes',
  cape:      'cape',
};
const SPELL_SLOT_ORDER = ['main_hand', 'off_hand', 'head', 'chest', 'shoes', 'cape'];

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
  // Ephemeral build contents. Each slot holds { primary, alt }; either may be
  // null. `primary` is the canonical item; `alt` is the optional swap item.
  slots: Object.fromEntries(SLOT_DEFS.map(s => [s.key, { primary: null, alt: null }])),
  // Key of the slot whose picker is currently open, or null
  activeSlot:     null,
  // Which variant the open picker edits: 'primary' | 'alt'
  activeVariant:  'primary',
  // Whether off_hand is locked because main_hand holds a 2H weapon
  offHandLocked:  false,
  // Picker filters and loaded data
  picker: _defaultPickerState(),
  // Chosen spells: field_key -> spell display name
  spells: {},
  // Available spell data per slot: slot -> { item_id, apiSlots:[...] }
  spellData: {},
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
const elSpells     = $('vbe-spells');

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

/* §4b — Spell catalog client ────────────────────────────── */

const spellClient = {
  // item_id -> API response {item_type, slots:[...]}. Cached for the session.
  _cache: {},

  /** Return spell data for an item_id, or null on failure. */
  async load(itemId) {
    if (!itemId) return null;
    if (this._cache[itemId]) return this._cache[itemId];
    const url = new URL('/api/catalog/spells', location.origin);
    url.searchParams.set('item_id', itemId);
    let res;
    try {
      res = await fetch(url.toString());
    } catch {
      return null;   // network error — degrade gracefully (no spell rows)
    }
    if (!res.ok) return null;
    let data;
    try {
      data = await res.json();
    } catch {
      return null;
    }
    this._cache[itemId] = data;
    return data;
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

  // ── Individual clear button (hidden until slot is filled) — clears the
  // whole slot (primary + alt).
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

  // ── Alt (swap) overlay — small icon in the bottom-right, shown when an
  // alternative item is set. Clicking it re-opens the picker in alt mode.
  const altOverlay = document.createElement('span');
  altOverlay.className = 'vbe-slot__alt';
  altOverlay.hidden    = true;
  altOverlay.setAttribute('role', 'button');
  altOverlay.setAttribute('tabindex', '0');
  altOverlay.setAttribute('aria-label', `Change alternative for ${def.label}`);
  const altImg = document.createElement('img');
  altImg.className = 'vbe-slot__alt-icon';
  altImg.alt       = '';
  altOverlay.appendChild(altImg);
  const altClear = document.createElement('button');
  altClear.type      = 'button';
  altClear.className = 'vbe-slot__alt-clear';
  altClear.setAttribute('aria-label', `Clear alternative for ${def.label}`);
  altClear.textContent = '✕';
  altClear.addEventListener('click', e => {
    e.stopPropagation();
    clearAlt(def.key);
  });
  altOverlay.appendChild(altClear);
  altOverlay.addEventListener('click', e => {
    e.stopPropagation();
    openPicker(def.key, 'alt');
  });
  altOverlay.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      e.stopPropagation();
      openPicker(def.key, 'alt');
    }
  });

  iconWrap.appendChild(placeholder);
  iconWrap.appendChild(img);
  iconWrap.appendChild(badges);
  iconWrap.appendChild(clearBtn);
  iconWrap.appendChild(altOverlay);

  const label = document.createElement('span');
  label.className   = 'vbe-slot__label';
  label.textContent = def.label;

  // ── "+ alt" affordance — shown only when a primary is set but no alt yet.
  const altAdd = document.createElement('button');
  altAdd.type      = 'button';
  altAdd.className = 'vbe-slot__alt-add';
  altAdd.hidden    = true;
  altAdd.textContent = '+ alt';
  altAdd.setAttribute('aria-label', `Add alternative for ${def.label}`);
  altAdd.addEventListener('click', e => {
    e.stopPropagation();
    openPicker(def.key, 'alt');
  });

  btn.appendChild(iconWrap);
  btn.appendChild(label);
  btn.appendChild(altAdd);

  btn.addEventListener('click', () => {
    // aria-disabled blocks interaction for the locked off_hand tile
    if (btn.getAttribute('aria-disabled') === 'true') return;
    openPicker(def.key, 'primary');
  });

  return btn;
}

// Called when a slot tile's icon fails to load — show placeholder instead
function _onSlotIconError(img, placeholder) {
  img.hidden         = true;
  placeholder.hidden = false;
}

function updateTile(slotKey) {
  const btn = $(`vbe-slot-${slotKey}`);
  if (!btn) return;
  const def       = SLOT_DEFS.find(s => s.key === slotKey);
  const slotState = state.slots[slotKey] || { primary: null, alt: null };
  const item      = slotState.primary;
  const alt       = slotState.alt;
  const ph        = btn.querySelector('.vbe-slot__placeholder');
  const img       = btn.querySelector('.vbe-slot__icon');
  const badges    = btn.querySelector('.vbe-slot__badges');
  const tierBadge = btn.querySelector('.vbe-tier-badge');
  const enchBadge = btn.querySelector('.vbe-ench-badge');
  const clearBtn  = btn.querySelector('.vbe-slot__clear');
  const altAdd    = btn.querySelector('.vbe-slot__alt-add');
  const altOver   = btn.querySelector('.vbe-slot__alt');
  const altImg    = btn.querySelector('.vbe-slot__alt-icon');

  // ── Primary
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

  // ── Alt (only meaningful when a primary is set and the tile isn't locked)
  const locked = btn.getAttribute('aria-disabled') === 'true';
  if (alt && item) {
    altImg.src        = alt.icon_url;
    altImg.alt        = alt.display_name;
    altOver.hidden    = false;
    altOver.title     = `Alt: ${alt.display_name} T${alt.tier}.${alt.enchantment}`;
    if (altAdd) altAdd.hidden = true;
  } else {
    altOver.hidden = true;
    altImg.src     = '';
    // Offer "+ alt" only once a primary exists and the tile isn't locked.
    if (altAdd) altAdd.hidden = !(item && !locked);
  }
}

/* §6 — Modal lifecycle ──────────────────────────────────── */

// The slot tile that triggered openPicker(); focus returns here on close.
let _returnFocusTarget = null;

function openPicker(slotKey, variant = 'primary') {
  state.activeSlot      = slotKey;
  state.activeVariant   = variant;
  _returnFocusTarget    = $(`vbe-slot-${slotKey}`);

  const def = SLOT_DEFS.find(s => s.key === slotKey);
  elModalTitle.textContent =
    variant === 'alt' ? `Select alternative — ${def.label}` : `Select — ${def.label}`;

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
  const variant = state.activeVariant === 'alt' ? 'alt' : 'primary';
  if (!state.slots[slotKey]) state.slots[slotKey] = { primary: null, alt: null };
  state.slots[slotKey][variant] = item;
  updateTile(slotKey);
  // Two-handed lock only depends on the PRIMARY main-hand weapon.
  if (slotKey === 'main_hand' && variant === 'primary') {
    applyTwoHandedLogic(item);
  }
  // Spells depend only on the PRIMARY item of a spell-bearing slot.
  if (variant === 'primary' && SPELL_SLOT_PREFIX[slotKey]) {
    refreshSpellData(slotKey);
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
    // Clear and lock off_hand (both primary and alt)
    state.slots['off_hand'] = { primary: null, alt: null };
    offBtn.setAttribute('aria-disabled', 'true');
    offBtn.classList.add('vbe-slot--disabled');
    updateTile('off_hand');
    elNotice.hidden = false;
  } else {
    offBtn.removeAttribute('aria-disabled');
    offBtn.classList.remove('vbe-slot--disabled');
    updateTile('off_hand');
    elNotice.hidden = true;
  }
  // Keep off-hand spell rows in sync with its (now possibly cleared) item.
  if (typeof refreshSpellData === 'function') refreshSpellData('off_hand');
}

/* §11 — Slot removal ────────────────────────────────────── */

function clearSlot(slotKey) {
  // The main ✕ clears the entire slot (primary and alt).
  state.slots[slotKey] = { primary: null, alt: null };
  updateTile(slotKey);
  // Clearing main_hand also unlocks off_hand if it was locked
  if (slotKey === 'main_hand') {
    applyTwoHandedLogic(null);
  }
  // Clearing a spell-bearing slot removes its spell options + selections.
  if (SPELL_SLOT_PREFIX[slotKey]) {
    refreshSpellData(slotKey);
  }
}

// Clear only the alternative (swap) item for a slot, keeping the primary.
function clearAlt(slotKey) {
  if (state.slots[slotKey]) state.slots[slotKey].alt = null;
  updateTile(slotKey);
}

function resetAllSlots() {
  for (const def of SLOT_DEFS) {
    state.slots[def.key] = { primary: null, alt: null };
    updateTile(def.key);
  }
  applyTwoHandedLogic(null);
  state.spells = {};
  state.spellData = {};
  rebuildSpellsUI();
}

/* §11b — Spells & passives ──────────────────────────────── */

// Field keys currently valid for a slot, based on loaded spell data.
function _fieldKeysForSlot(slot) {
  const data = state.spellData[slot];
  if (!data) return [];
  const prefix = SPELL_SLOT_PREFIX[slot];
  return (data.apiSlots || []).map(s => `${prefix}_${s.field_suffix}`);
}

// Fetch (or clear) spell options for a slot's primary item, prune stale
// selections, then rebuild the spell UI.
async function refreshSpellData(slot) {
  const prefix = SPELL_SLOT_PREFIX[slot];
  if (!prefix) return;  // slot carries no spells (food/potion/…)

  const primary = state.slots[slot] && state.slots[slot].primary;
  if (!primary) {
    // Clear this slot's spell data and any chosen spells for its fields.
    for (const fk of _fieldKeysForSlot(slot)) delete state.spells[fk];
    delete state.spellData[slot];
    rebuildSpellsUI();
    return;
  }

  // Same item already loaded — nothing to fetch.
  if (state.spellData[slot] && state.spellData[slot].item_id === primary.item_id) {
    rebuildSpellsUI();
    return;
  }

  // Drop selections tied to the previous item in this slot before loading.
  for (const fk of _fieldKeysForSlot(slot)) delete state.spells[fk];

  const data = await spellClient.load(primary.item_id);
  const apiSlots = (data && Array.isArray(data.slots)) ? data.slots : [];
  if (apiSlots.length === 0) {
    delete state.spellData[slot];
  } else {
    state.spellData[slot] = { item_id: primary.item_id, apiSlots };
    // Prune selections that are no longer valid options for the new item.
    for (const apiSlot of apiSlots) {
      const fk = `${prefix}_${apiSlot.field_suffix}`;
      const names = new Set(apiSlot.spells.map(sp => sp.name));
      if (state.spells[fk] && !names.has(state.spells[fk])) {
        delete state.spells[fk];
      }
    }
  }
  rebuildSpellsUI();
}

function _iconUrlForSelection(apiSlot, name) {
  const sp = (apiSlot.spells || []).find(s => s.name === name);
  return sp ? sp.icon_url : '';
}

function rebuildSpellsUI() {
  if (!elSpells) return;
  elSpells.innerHTML = '';

  const anyData = SPELL_SLOT_ORDER.some(slot => state.spellData[slot]);
  if (!anyData) {
    const p = document.createElement('p');
    p.className   = 'text-muted';
    p.id          = 'vbe-spells-empty';
    p.textContent = 'Select weapons and armor above to choose spells.';
    elSpells.appendChild(p);
    return;
  }

  for (const slot of SPELL_SLOT_ORDER) {
    const data = state.spellData[slot];
    if (!data) continue;
    const prefix = SPELL_SLOT_PREFIX[slot];
    const def    = SLOT_DEFS.find(s => s.key === slot);

    const group = document.createElement('div');
    group.className = 'vbe-spell-group';

    const heading = document.createElement('div');
    heading.className   = 'vbe-spell-group__title';
    heading.textContent = def ? def.label : slot;
    group.appendChild(heading);

    for (const apiSlot of data.apiSlots) {
      const fieldKey = `${prefix}_${apiSlot.field_suffix}`;
      const selected = state.spells[fieldKey] || '';

      const row = document.createElement('div');
      row.className    = 'vbe-spell-row';
      row.dataset.field = fieldKey;

      const icon = document.createElement('img');
      icon.className = 'vbe-spell-row__icon';
      icon.alt       = '';
      const iconUrl = selected ? _iconUrlForSelection(apiSlot, selected) : '';
      if (iconUrl) { icon.src = iconUrl; } else { icon.style.visibility = 'hidden'; }
      icon.addEventListener('error', () => { icon.style.visibility = 'hidden'; });

      const label = document.createElement('span');
      label.className   = 'vbe-spell-row__label';
      label.textContent = apiSlot.label;

      const select = document.createElement('select');
      select.className = 'vbe-spell-row__select';
      const none = document.createElement('option');
      none.value = '';
      none.textContent = '— none —';
      select.appendChild(none);
      for (const sp of apiSlot.spells) {
        const opt = document.createElement('option');
        opt.value = sp.name;
        opt.textContent = sp.name;
        if (sp.name === selected) opt.selected = true;
        select.appendChild(opt);
      }
      select.addEventListener('change', () => {
        const val = select.value;
        if (val) {
          state.spells[fieldKey] = val;
          const u = _iconUrlForSelection(apiSlot, val);
          if (u) { icon.src = u; icon.style.visibility = ''; }
          else   { icon.style.visibility = 'hidden'; }
        } else {
          delete state.spells[fieldKey];
          icon.style.visibility = 'hidden';
        }
      });

      row.appendChild(icon);
      row.appendChild(label);
      row.appendChild(select);
      group.appendChild(row);
    }

    elSpells.appendChild(group);
  }
}

// Serialize chosen spells for the hidden form field.
function serializeSpells() {
  const out = [];
  for (const [fieldKey, name] of Object.entries(state.spells)) {
    if (name) out.push({ field_key: fieldKey, spell_name: name });
  }
  return JSON.stringify(out);
}

// Prefill chosen spells from embedded JSON (edit mode). Selections are applied
// to state now; refreshSpellData() renders them once options are fetched.
function loadInitialSpells() {
  const el = document.getElementById('vbe-initial-spells');
  if (!el) return;
  let items;
  try {
    items = JSON.parse(el.textContent);
  } catch (e) {
    console.error('[VBE] Failed to parse initial spells JSON:', e);
    return;
  }
  if (!Array.isArray(items)) return;
  for (const it of items) {
    if (it && it.field_key && it.spell_name) {
      state.spells[it.field_key] = it.spell_name;
    }
  }
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
    const slotState = state.slots[def.key] || { primary: null, alt: null };
    if (slotState.primary) {
      items.push({
        slot:       def.key,
        item_id:    slotState.primary.item_id,
        is_primary: true,
        priority:   0,
      });
    }
    // Alternatives only make sense alongside a primary.
    if (slotState.primary && slotState.alt) {
      items.push({
        slot:       def.key,
        item_id:    slotState.alt.item_id,
        is_primary: false,
        priority:   1,
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
    if (!state.slots[item.slot]) state.slots[item.slot] = { primary: null, alt: null };
    // is_primary may be a boolean or 0/1; treat missing as primary.
    const isPrimary = (item.is_primary === undefined) ? true : !!item.is_primary;
    if (isPrimary) {
      state.slots[item.slot].primary = item;
    } else {
      state.slots[item.slot].alt = item;
    }
  }

  // Re-render all tiles with loaded data
  for (const def of SLOT_DEFS) {
    updateTile(def.key);
  }

  // Apply two-handed logic if a 2H main weapon is loaded
  const mainItem = state.slots['main_hand'] && state.slots['main_hand'].primary;
  if (mainItem && mainItem.is_two_handed) {
    state.offHandLocked = true;
    state.slots['off_hand'] = { primary: null, alt: null };
    const tile = document.querySelector(`[data-slot="off_hand"]`);
    if (tile) {
      tile.classList.add('vbe-slot--disabled');
      tile.setAttribute('disabled', '');
      tile.setAttribute('aria-disabled', 'true');
    }
    updateTile('off_hand');  // disable + hide alt affordance
    if (elNotice) elNotice.removeAttribute('hidden');
  }

  // Prefill chosen spells, then fetch options for each equipped spell slot so
  // the spell rows render with the saved selections applied.
  loadInitialSpells();
  for (const slot of SPELL_SLOT_ORDER) {
    if (state.slots[slot] && state.slots[slot].primary) {
      refreshSpellData(slot);
    }
  }
}

/**
 * Wire up the save form:
 * - On submit, serialize current slot and spell state into the hidden fields.
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
    const spellsField = document.getElementById('vbe-spells-json');
    if (spellsField) {
      spellsField.value = serializeSpells();
    }
    // HTML5 validation handles required fields; no extra JS needed here.
  });
}

initGrid();
initEvents();
loadInitialSlots();
initSaveForm();
