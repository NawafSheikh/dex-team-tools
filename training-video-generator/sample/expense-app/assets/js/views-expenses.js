/* "My expenses" list and the expense detail view. */
(function () {
  'use strict';

  const BW = window.BW;
  const D = BW.D;
  const esc = BW.esc;
  const icon = BW.icon;

  const listUi = { status: 'All', query: '', highlight: null };

  const TILE_COPY = {
    Draft: 'Not submitted',
    Submitted: 'Awaiting approval',
    Approved: 'In next payment run',
    Reimbursed: 'Paid to you'
  };

  function totals(expenses) {
    return D.STATUSES.reduce(function (acc, s) {
      const rows = expenses.filter(function (e) { return e.status === s; });
      const sum = rows.reduce(function (t, e) { return t + BW.toEUR(e.amount, e.currency); }, 0);
      return Object.assign({}, acc, { [s]: { count: rows.length, sum: sum } });
    }, {});
  }

  function tileHtml(status, t) {
    const active = listUi.status === status ? ' is-active' : '';
    const noun = t.count === 1 ? 'expense' : 'expenses';
    return '<button type="button" class="tile tile-' + status.toLowerCase() + active + '" data-status="' + status + '" aria-pressed="' + (listUi.status === status) + '">' +
      '<span class="tile-label"><span class="tile-dot"></span>' + status + '</span>' +
      '<span class="tile-amount">' + BW.money(t.sum) + '</span>' +
      '<span class="tile-meta">' + t.count + ' ' + noun + '<span class="tile-sep"></span>' + TILE_COPY[status] + '</span>' +
      '</button>';
  }

  function matches(e) {
    if (listUi.status !== 'All' && e.status !== listUi.status) return false;
    const q = listUi.query.trim().toLowerCase();
    if (!q) return true;
    return [e.id, e.merchant, e.category, e.costCentre].join(' ').toLowerCase().indexOf(q) !== -1;
  }

  function rowHtml(e) {
    const isNew = listUi.highlight === e.id ? ' row-new' : '';
    const fx = e.currency !== 'EUR' ? '<span class="cell-sub">' + BW.money(BW.toEUR(e.amount, e.currency)) + '</span>' : '';
    return '<tr class="row' + isNew + '" data-id="' + esc(e.id) + '" tabindex="0" aria-label="Open expense ' + esc(e.id) + ', ' + esc(e.merchant) + '">' +
      '<td class="col-date">' + esc(BW.fmtDate(e.date)) + '</td>' +
      '<td class="col-merchant"><span class="cell-main">' + esc(e.merchant) + '</span><span class="cell-sub">' + esc(e.id) + '</span></td>' +
      '<td class="col-cat"><span class="cat">' + BW.categoryIcon(e.category) + esc(e.category) + '</span></td>' +
      '<td class="col-cc">' + esc(BW.costCentreLabel(e.costCentre)) + '</td>' +
      '<td class="col-amount"><span class="cell-main">' + esc(BW.money(e.amount, e.currency)) + '</span>' + fx + '</td>' +
      '<td class="col-status">' + BW.statusChip(e.status) + '</td>' +
      '<td class="col-go">' + icon('chevronRight') + '</td>' +
      '</tr>';
  }

  function tableBody(expenses) {
    const rows = BW.sortedExpenses(expenses).filter(matches);
    if (!rows.length) {
      return '<tr class="row-empty"><td colspan="7"><div class="empty">' + icon('search') +
        '<div class="empty-title">No expenses match</div><div class="empty-text">Try a different search or status filter.</div></div></td></tr>';
    }
    return rows.map(rowHtml).join('');
  }

  function filterTabs(expenses) {
    const opts = ['All'].concat(D.STATUSES);
    return opts.map(function (s) {
      const n = s === 'All' ? expenses.length : expenses.filter(function (e) { return e.status === s; }).length;
      const active = listUi.status === s;
      return '<button type="button" class="seg' + (active ? ' is-active' : '') + '" data-filter="' + s + '" aria-pressed="' + active + '">' +
        s + '<span class="seg-count">' + n + '</span></button>';
    }).join('');
  }

  function renderList(root) {
    const expenses = BW.getState().expenses;
    const t = totals(expenses);
    root.innerHTML =
      '<div class="page">' +
      '<div class="page-head">' +
      '<div><h1>My expenses</h1><p class="sub">Add receipts, submit claims and follow them through to payment.</p></div>' +
      '<a class="btn btn-primary btn-lg" href="#/expenses/new" id="new-expense">' + icon('plus') + 'New expense</a>' +
      '</div>' +
      '<div class="tiles">' + D.STATUSES.map(function (s) { return tileHtml(s, t[s]); }).join('') + '</div>' +
      '<section class="card table-card" aria-label="Expenses">' +
      '<div class="table-toolbar">' +
      '<div class="segs" role="group" aria-label="Filter by status">' + filterTabs(expenses) + '</div>' +
      '<label class="search"><span class="sr-only">Search expenses</span>' + icon('search') +
      '<input type="search" id="list-search" placeholder="Search expenses" value="' + esc(listUi.query) + '" autocomplete="off"></label>' +
      '</div>' +
      '<table class="table"><thead><tr>' +
      '<th class="col-date">Date</th><th class="col-merchant">Merchant</th><th class="col-cat">Category</th>' +
      '<th class="col-cc">Cost centre</th><th class="col-amount">Amount</th><th class="col-status">Status</th><th class="col-go"><span class="sr-only">Open</span></th>' +
      '</tr></thead><tbody id="list-body">' + tableBody(expenses) + '</tbody></table>' +
      '</section></div>';

    bindList(root);
    window.setTimeout(function () { listUi.highlight = null; }, 0);
    return { title: 'My expenses', nav: 'expenses', crumbs: ['My expenses'] };
  }

  function bindList(root) {
    const rerender = function () { renderList(root); };
    root.querySelectorAll('[data-status]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const s = btn.getAttribute('data-status');
        listUi.status = listUi.status === s ? 'All' : s;
        rerender();
      });
    });
    root.querySelectorAll('[data-filter]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        listUi.status = btn.getAttribute('data-filter');
        rerender();
      });
    });
    const search = root.querySelector('#list-search');
    search.addEventListener('input', function () {
      listUi.query = search.value;
      root.querySelector('#list-body').innerHTML = tableBody(BW.getState().expenses);
    });
    const body = root.querySelector('#list-body');
    const open = function (tr) {
      if (tr && tr.dataset.id) window.location.hash = '#/expenses/' + tr.dataset.id;
    };
    body.addEventListener('click', function (ev) { open(ev.target.closest('tr.row')); });
    body.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        open(ev.target.closest('tr.row'));
      }
    });
  }

  /* ---------- detail ---------- */

  function timelineSteps(e) {
    const h = e.history || {};
    const mgr = D.USER.manager;
    const defs = [
      { key: 'created', label: 'Created', done: 'Created by ' + D.USER.name, wait: '' },
      { key: 'submitted', label: 'Submitted', done: 'Sent to ' + mgr + ' for approval', wait: 'Not submitted yet' },
      { key: 'approved', label: 'Manager approval', done: 'Approved by ' + mgr, wait: 'Waiting for ' + mgr },
      { key: 'financeChecked', label: 'Finance check', done: 'Receipt and VAT checked by Finance', wait: 'Finance checks the receipt and VAT, usually within 2 working days' },
      { key: 'reimbursed', label: 'Reimbursed', done: 'Paid to ' + D.USER.iban, wait: 'Paid in the Friday payment run' }
    ];
    let currentSet = false;
    return defs.map(function (d) {
      if (h[d.key]) return { label: d.label, state: 'done', note: d.done, at: BW.fmtStamp(h[d.key]) };
      const state = currentSet ? 'todo' : 'current';
      currentSet = true;
      return { label: d.label, state: state, note: d.wait, at: '' };
    });
  }

  function timelineHtml(e) {
    return '<ol class="timeline">' + timelineSteps(e).map(function (s) {
      const mark = s.state === 'done' ? icon('check') : s.state === 'current' ? icon('clock') : '';
      return '<li class="tl tl-' + s.state + '"><span class="tl-mark">' + mark + '</span>' +
        '<div class="tl-body"><div class="tl-head"><span class="tl-label">' + esc(s.label) + '</span>' +
        (s.at ? '<span class="tl-at">' + esc(s.at) + '</span>' : '') + '</div>' +
        '<div class="tl-note">' + esc(s.note) + '</div></div></li>';
    }).join('') + '</ol>';
  }

  function mockReceipt(e) {
    const rate = e.category === 'Meals' || e.category === 'Accommodation' ? 9 : 21;
    const net = Math.round((e.amount / (1 + rate / 100)) * 100) / 100;
    const vat = Math.round((e.amount - net) * 100) / 100;
    return '<div class="paper-wrap"><div class="paper" aria-label="Archived receipt">' +
      '<div class="paper-merchant">' + esc(e.merchant.toUpperCase()) + '</div>' +
      '<div class="paper-line"><span>Date</span><span>' + esc(e.date) + '</span></div>' +
      '<div class="paper-line"><span>Ref</span><span>' + esc(e.id.replace('EXP', 'R')) + '</span></div>' +
      '<div class="paper-rule"></div>' +
      '<div class="paper-line"><span>' + esc(e.category) + '</span><span>' + Number(e.amount).toFixed(2) + '</span></div>' +
      '<div class="paper-rule"></div>' +
      '<div class="paper-line"><span>Excl. VAT</span><span>' + net.toFixed(2) + '</span></div>' +
      '<div class="paper-line"><span>VAT ' + rate + '%</span><span>' + vat.toFixed(2) + '</span></div>' +
      '<div class="paper-line paper-total"><span>TOTAL ' + esc(e.currency) + '</span><span>' + Number(e.amount).toFixed(2) + '</span></div>' +
      '<div class="paper-foot">Paid by card</div>' +
      '</div></div>';
  }

  function receiptPanel(e) {
    if (e.receipt && e.receipt.dataUrl) {
      return '<div class="receipt-view"><img src="' + e.receipt.dataUrl + '" alt="Receipt for ' + esc(e.merchant) + '"></div>' +
        '<div class="receipt-file">' + icon('image') + '<span class="receipt-file-name">' + esc(e.receipt.name) + '</span>' +
        '<span class="receipt-file-size">' + esc(BW.fileSize(e.receipt.size)) + '</span>' +
        '<a class="btn btn-ghost btn-sm" download="' + esc(e.receipt.name.replace(/\.\w+$/, '') + '.jpg') + '" href="' + e.receipt.dataUrl + '">' + icon('download') + 'Download</a></div>';
    }
    if (e.category === 'Mileage') {
      return '<div class="receipt-none">' + icon('mileage') + '<div class="empty-title">No receipt needed for mileage</div>' +
        '<div class="empty-text">' + esc(String(e.distanceKm || '')) + ' km at ' + BW.money(D.POLICY.mileageRate) + ' per km. Finance checks the route against your calendar.</div></div>';
    }
    if (e.receiptName) {
      return mockReceipt(e) + '<div class="receipt-file">' + icon('file') + '<span class="receipt-file-name">' + esc(e.receiptName) + '</span>' +
        '<span class="receipt-file-size">Archived</span></div>';
    }
    const hint = e.status === 'Draft' ? 'Edit the draft to add a receipt before you submit it.' : 'This expense was submitted without a receipt.';
    return '<div class="receipt-none">' + icon('image') + '<div class="empty-title">No receipt attached</div><div class="empty-text">' + hint + '</div></div>';
  }

  function detailActions(e) {
    if (e.status === 'Draft') {
      return '<button type="button" class="btn btn-secondary" id="delete-draft">' + icon('trash') + 'Delete draft</button>' +
        '<a class="btn btn-primary" href="#/expenses/' + esc(e.id) + '/edit">' + icon('pencil') + 'Edit draft</a>';
    }
    if (e.status === 'Submitted') {
      return '<button type="button" class="btn btn-secondary" id="withdraw">' + icon('undo') + 'Withdraw</button>';
    }
    return '';
  }

  function factsHtml(e) {
    const rows = [
      ['Merchant', esc(e.merchant)],
      ['Expense date', esc(BW.fmtDate(e.date))],
      ['Category', '<span class="cat">' + BW.categoryIcon(e.category) + esc(e.category) + '</span>'],
      ['Cost centre', esc(BW.costCentreLabel(e.costCentre))],
      ['Approver', esc(D.USER.manager) + ', ' + esc(D.USER.managerTitle)],
      [e.category === 'Meals' ? 'Number of people' : 'Submitted by', e.category === 'Meals' ? esc(String(e.attendees || 1)) : esc(D.USER.name)]
    ];
    return '<dl class="facts">' + rows.map(function (r) {
      return '<div class="fact"><dt>' + r[0] + '</dt><dd>' + r[1] + '</dd></div>';
    }).join('') + '<div class="fact fact-wide"><dt>Business purpose</dt><dd>' + esc(e.purpose || 'Not provided yet') + '</dd></div></dl>';
  }

  function renderDetail(root, params) {
    const e = BW.getState().expenses.find(function (x) { return x.id === params.id; });
    if (!e) {
      root.innerHTML = '<div class="page"><div class="card notfound"><div class="empty-title">Expense not found</div>' +
        '<div class="empty-text">It may have been deleted.</div><a class="btn btn-secondary" href="#/expenses">Back to My expenses</a></div></div>';
      return { title: 'Not found', nav: 'expenses', crumbs: ['My expenses', 'Not found'] };
    }
    const eurLine = e.currency !== 'EUR'
      ? '<div class="amount-fx">About ' + BW.money(BW.toEUR(e.amount, e.currency)) + ' at the Finance reference rate</div>' : '';
    root.innerHTML =
      '<div class="page">' +
      '<div class="page-head">' +
      '<div><a class="back" href="#/expenses">' + icon('chevronLeft') + 'My expenses</a>' +
      '<div class="title-row"><h1>' + esc(e.merchant) + '</h1>' + BW.statusChip(e.status) + '</div>' +
      '<p class="sub">' + esc(e.id) + '<span class="dot-sep"></span>' + esc(e.category) + '<span class="dot-sep"></span>' + esc(BW.fmtDate(e.date)) + '</p></div>' +
      '<div class="head-actions">' + detailActions(e) + '</div>' +
      '</div>' +
      '<div class="detail-grid">' +
      '<div class="detail-main">' +
      '<section class="card pad"><div class="amount-label">Amount</div><div class="amount-big">' + esc(BW.money(e.amount, e.currency)) + '</div>' + eurLine + factsHtml(e) + '</section>' +
      '<section class="card pad"><h2 class="card-title">Status</h2>' + timelineHtml(e) + '</section>' +
      '</div>' +
      '<aside class="card pad receipt-card" aria-label="Receipt"><h2 class="card-title">Receipt</h2>' + receiptPanel(e) + '</aside>' +
      '</div></div>';
    bindDetail(root, e);
    return { title: e.id + ' ' + e.merchant, nav: 'expenses', crumbs: ['My expenses', e.id] };
  }

  function bindDetail(root, e) {
    const withdraw = root.querySelector('#withdraw');
    if (withdraw) {
      withdraw.addEventListener('click', function () {
        const s = BW.getState();
        const history = { created: e.history.created };
        const updated = Object.assign({}, e, { status: 'Draft', history: history });
        BW.setState(Object.assign({}, s, { expenses: s.expenses.map(function (x) { return x.id === e.id ? updated : x; }) }));
        BW.showToast({ kind: 'info', title: e.id + ' withdrawn', body: 'It is back in your drafts. Edit it and submit again when ready.' });
        renderDetail(root, { id: e.id });
      });
    }
    const del = root.querySelector('#delete-draft');
    if (del) {
      let armed = false;
      del.addEventListener('click', function () {
        if (!armed) {
          armed = true;
          del.classList.add('btn-danger');
          del.innerHTML = icon('trash') + 'Click again to delete';
          window.setTimeout(function () {
            if (!del.isConnected) return;
            armed = false;
            del.classList.remove('btn-danger');
            del.innerHTML = icon('trash') + 'Delete draft';
          }, 4000);
          return;
        }
        const s = BW.getState();
        BW.setState(Object.assign({}, s, { expenses: s.expenses.filter(function (x) { return x.id !== e.id; }) }));
        BW.showToast({ kind: 'info', title: 'Draft ' + e.id + ' deleted' });
        window.location.hash = '#/expenses';
      });
    }
  }

  BW.views.list = renderList;
  BW.views.detail = renderDetail;
  BW.highlightRow = function (id) { listUi.highlight = id; listUi.status = 'All'; listUi.query = ''; };
})();
