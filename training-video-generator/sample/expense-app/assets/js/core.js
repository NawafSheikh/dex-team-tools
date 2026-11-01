/* Core helpers: formatting, persisted state, toasts. Exposed as window.BW. */
(function () {
  'use strict';

  const D = window.BWData;
  const icon = window.BWIcons.icon;
  const STORAGE_KEY = 'bw-expenses-state-v1';
  const STATE_VERSION = 1;

  /* ---------- formatting ---------- */

  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (c) {
      return ESCAPES[c];
    });
  }

  function money(amount, currency) {
    const code = currency || 'EUR';
    try {
      return new Intl.NumberFormat('en-IE', { style: 'currency', currency: code }).format(amount);
    } catch (err) {
      return code + ' ' + Number(amount).toFixed(2);
    }
  }

  function pad(n) {
    return String(n).padStart(2, '0');
  }

  function toISODate(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function todayISO() {
    return toISODate(new Date());
  }

  function nowStamp() {
    const d = new Date();
    return toISODate(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function parseISODate(iso) {
    const parts = String(iso).split('-').map(Number);
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function fmtDay(d) {
    return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  }

  function fmtDate(iso) {
    if (!iso) return '';
    return fmtDay(parseISODate(iso));
  }

  function fmtStamp(stamp) {
    if (!stamp) return '';
    const d = new Date(stamp);
    return fmtDay(d) + ' at ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function daysBetween(fromISO, toISO) {
    const ms = parseISODate(toISO) - parseISODate(fromISO);
    return Math.round(ms / 86400000);
  }

  function rateFor(currency) {
    const found = D.CURRENCIES.find(function (c) { return c.code === currency; });
    return found ? found.rate : 1;
  }

  function toEUR(amount, currency) {
    return Math.round(Number(amount || 0) * rateFor(currency) * 100) / 100;
  }

  function fileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function categoryIcon(category) {
    const found = D.CATEGORIES.find(function (c) { return c.id === category; });
    return icon(found ? found.icon : 'other');
  }

  function costCentreLabel(id) {
    const found = D.COST_CENTRES.find(function (c) { return c.id === id; });
    return found ? found.id + ' ' + found.name : id;
  }

  function statusChip(status) {
    const key = String(status).toLowerCase();
    return '<span class="chip chip-' + esc(key) + '"><span class="chip-dot"></span>' + esc(status) + '</span>';
  }

  /* ---------- state ---------- */

  function cloneExpense(e) {
    return Object.assign({}, e, { history: Object.assign({}, e.history) });
  }

  function seedState() {
    return {
      version: STATE_VERSION,
      expenses: D.SEED_EXPENSES.map(cloneExpense),
      approvals: D.SEED_APPROVALS.map(function (a) { return Object.assign({}, a); }),
      settings: Object.assign({}, D.SEED_SETTINGS)
    };
  }

  let state = null;
  let loadProblem = null;

  function loadState() {
    let raw = null;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      loadProblem = 'Browser storage is blocked, so changes will not be kept after you close this tab.';
      return seedState();
    }
    if (!raw) return seedState();
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.version !== STATE_VERSION || !Array.isArray(parsed.expenses)) {
        return seedState();
      }
      return parsed;
    } catch (err) {
      loadProblem = 'Saved data could not be read, so the demo data was restored.';
      return seedState();
    }
  }

  function persist(next) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return true;
    } catch (err) {
      const full = err && (err.name === 'QuotaExceededError' || err.code === 22);
      showToast({
        kind: 'error',
        title: 'Could not save your change',
        body: full
          ? 'Browser storage is full. Remove an older receipt and try again.'
          : 'Your browser blocked local storage for this site.'
      });
      return false;
    }
  }

  function getState() {
    if (!state) state = loadState();
    return state;
  }

  function setState(next) {
    state = next;
    return persist(next);
  }

  function resetState() {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (err) {
      loadProblem = 'Browser storage is blocked.';
    }
    state = seedState();
    persist(state);
    return state;
  }

  function takeLoadProblem() {
    const p = loadProblem;
    loadProblem = null;
    return p;
  }

  function nextExpenseId(expenses) {
    const max = expenses.reduce(function (acc, e) {
      const n = parseInt(String(e.id).replace(/\D/g, ''), 10);
      return Number.isFinite(n) && n > acc ? n : acc;
    }, 1000);
    return 'EXP-' + (max + 1);
  }

  function sortedExpenses(expenses) {
    return expenses.slice().sort(function (a, b) {
      const ka = (a.history && a.history.created) || a.date;
      const kb = (b.history && b.history.created) || b.date;
      return ka < kb ? 1 : ka > kb ? -1 : 0;
    });
  }

  /* ---------- toasts ---------- */

  const TOAST_ICONS = { success: 'check', error: 'alertCircle', info: 'info' };

  function showToast(opts) {
    const host = document.getElementById('toasts');
    if (!host) return;
    const kind = opts.kind || 'success';
    const el = document.createElement('div');
    el.className = 'toast toast-' + kind;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const action = opts.action
      ? '<a class="toast-action" href="' + esc(opts.action.href) + '">' + esc(opts.action.label) + '</a>'
      : '';
    el.innerHTML =
      '<span class="toast-icon">' + icon(TOAST_ICONS[kind] || 'info') + '</span>' +
      '<div class="toast-body"><div class="toast-title">' + esc(opts.title) + '</div>' +
      (opts.body ? '<div class="toast-text">' + esc(opts.body) + '</div>' : '') + action + '</div>' +
      '<button type="button" class="toast-close" aria-label="Dismiss notification">' + icon('x') + '</button>';
    host.appendChild(el);
    const remove = function () {
      el.classList.add('is-leaving');
      window.setTimeout(function () { el.remove(); }, 200);
    };
    el.querySelector('.toast-close').addEventListener('click', remove);
    const link = el.querySelector('.toast-action');
    if (link) link.addEventListener('click', remove);
    window.setTimeout(remove, opts.duration || 7000);
  }

  window.BW = {
    D: D,
    icon: icon,
    esc: esc,
    money: money,
    todayISO: todayISO,
    nowStamp: nowStamp,
    toISODate: toISODate,
    parseISODate: parseISODate,
    fmtDate: fmtDate,
    fmtStamp: fmtStamp,
    daysBetween: daysBetween,
    toEUR: toEUR,
    fileSize: fileSize,
    categoryIcon: categoryIcon,
    costCentreLabel: costCentreLabel,
    statusChip: statusChip,
    getState: getState,
    setState: setState,
    resetState: resetState,
    takeLoadProblem: takeLoadProblem,
    nextExpenseId: nextExpenseId,
    sortedExpenses: sortedExpenses,
    showToast: showToast,
    views: {}
  };
})();
