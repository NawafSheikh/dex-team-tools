/* Secondary pages: Approvals, Reports, Policy, Settings. */
(function () {
  'use strict';

  const BW = window.BW;
  const D = BW.D;
  const P = D.POLICY;
  const esc = BW.esc;
  const icon = BW.icon;

  function pageHead(title, sub, actions) {
    return '<div class="page-head"><div><h1>' + esc(title) + '</h1><p class="sub">' + esc(sub) + '</p></div>' +
      (actions ? '<div class="head-actions">' + actions + '</div>' : '') + '</div>';
  }

  /* ---------- approvals ---------- */

  function approvalRow(a) {
    const decided = a.status !== 'Pending';
    const actions = decided
      ? '<span class="chip chip-' + (a.status === 'Approved' ? 'approved' : 'rejected') + '"><span class="chip-dot"></span>' + esc(a.status) + '</span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-undo="' + esc(a.id) + '">' + icon('undo') + 'Undo</button>'
      : '<button type="button" class="btn btn-secondary btn-sm" data-reject="' + esc(a.id) + '">Reject</button>' +
        '<button type="button" class="btn btn-primary btn-sm" data-approve="' + esc(a.id) + '">' + icon('check') + 'Approve</button>';
    const pp = a.category === 'Meals' && a.attendees
      ? '<span class="cell-sub">' + BW.money(a.amount / a.attendees) + ' per person, ' + a.attendees + ' people</span>' : '<span class="cell-sub">' + esc(a.id) + '</span>';
    return '<tr class="' + (decided ? 'is-decided' : '') + '">' +
      '<td><div class="person"><span class="avatar avatar-sm">' + esc(a.initials) + '</span><span><span class="cell-main">' + esc(a.employee) + '</span><span class="cell-sub">' + esc(a.role) + '</span></span></div></td>' +
      '<td><span class="cell-main">' + esc(a.merchant) + '</span><span class="cell-sub">' + esc(BW.fmtDate(a.date)) + '</span></td>' +
      '<td><span class="cat">' + BW.categoryIcon(a.category) + esc(a.category) + '</span></td>' +
      '<td class="col-purpose">' + esc(a.purpose) + '</td>' +
      '<td class="col-amount"><span class="cell-main">' + esc(BW.money(a.amount, a.currency)) + '</span>' + pp + '</td>' +
      '<td class="col-actions"><div class="row-actions">' + actions + '</div></td></tr>';
  }

  function renderApprovals(root) {
    const list = BW.getState().approvals;
    const pending = list.filter(function (a) { return a.status === 'Pending'; });
    const total = pending.reduce(function (t, a) { return t + a.amount; }, 0);
    const decided = list.length - pending.length;
    root.innerHTML = '<div class="page">' +
      pageHead('Approvals', 'Expenses from your team that are waiting for your decision.') +
      '<div class="tiles tiles-3">' +
      '<div class="tile tile-static"><span class="tile-label">Waiting for you</span><span class="tile-amount">' + pending.length + '</span><span class="tile-meta">' + BW.money(total) + ' in total</span></div>' +
      '<div class="tile tile-static"><span class="tile-label">Approve within</span><span class="tile-amount">3 days</span><span class="tile-meta">Company target for manager approval</span></div>' +
      '<div class="tile tile-static"><span class="tile-label">Decided</span><span class="tile-amount">' + decided + '</span><span class="tile-meta">Approved or rejected by you this week</span></div>' +
      '</div>' +
      '<section class="card table-card"><table class="table table-approvals"><thead><tr><th>Employee</th><th>Merchant</th><th>Category</th><th>Business purpose</th><th class="col-amount">Amount</th><th class="col-actions"><span class="sr-only">Decision</span></th></tr></thead>' +
      '<tbody>' + list.map(approvalRow).join('') + '</tbody></table></section></div>';

    root.querySelectorAll('[data-approve],[data-reject],[data-undo]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const id = btn.dataset.approve || btn.dataset.reject || btn.dataset.undo;
        const next = btn.dataset.approve ? 'Approved' : btn.dataset.reject ? 'Rejected' : 'Pending';
        const s = BW.getState();
        const item = s.approvals.find(function (a) { return a.id === id; });
        BW.setState(Object.assign({}, s, {
          approvals: s.approvals.map(function (a) { return a.id === id ? Object.assign({}, a, { status: next }) : a; })
        }));
        if (next !== 'Pending') {
          BW.showToast({ kind: next === 'Approved' ? 'success' : 'info', title: id + ' ' + next.toLowerCase(), body: item.employee + ' has been notified.' });
        }
        BW.refreshNav();
        renderApprovals(root);
      });
    });
    return { title: 'Approvals', nav: 'approvals', crumbs: ['Approvals'] };
  }

  /* ---------- reports ---------- */

  function groupSum(expenses, keyFn) {
    return expenses.reduce(function (acc, e) {
      const k = keyFn(e);
      return Object.assign({}, acc, { [k]: (acc[k] || 0) + BW.toEUR(e.amount, e.currency) });
    }, {});
  }

  function barsHtml(map, labelFn) {
    const entries = Object.keys(map).map(function (k) { return [k, map[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    const max = entries.length ? entries[0][1] : 1;
    return '<div class="bars">' + entries.map(function (en) {
      const w = Math.max(2, Math.round((en[1] / max) * 100));
      return '<div class="bar-row"><span class="bar-label">' + esc(labelFn(en[0])) + '</span>' +
        '<span class="bar-track"><span class="bar-fill" style="width:' + w + '%"></span></span>' +
        '<span class="bar-value">' + esc(BW.money(en[1])) + '</span></div>';
    }).join('') + '</div>';
  }

  function avgPayDays(expenses) {
    const paid = expenses.filter(function (e) { return e.history && e.history.reimbursed && e.history.submitted; });
    if (!paid.length) return null;
    const days = paid.reduce(function (t, e) {
      return t + (new Date(e.history.reimbursed) - new Date(e.history.submitted)) / 86400000;
    }, 0);
    return days / paid.length;
  }

  function csv(expenses) {
    const head = ['ID', 'Date', 'Merchant', 'Category', 'Cost centre', 'Amount', 'Currency', 'Amount EUR', 'Status', 'Business purpose'];
    const cell = function (v) { return '"' + String(v === null || v === undefined ? '' : v).replace(/"/g, '""') + '"'; };
    const rows = BW.sortedExpenses(expenses).map(function (e) {
      return [e.id, e.date, e.merchant, e.category, e.costCentre, Number(e.amount).toFixed(2), e.currency,
        BW.toEUR(e.amount, e.currency).toFixed(2), e.status, e.purpose].map(cell).join(',');
    });
    return [head.map(cell).join(',')].concat(rows).join('\r\n');
  }

  function renderReports(root) {
    const all = BW.getState().expenses;
    const claimed = all.filter(function (e) { return e.status !== 'Draft'; });
    const sum = function (list) { return list.reduce(function (t, e) { return t + BW.toEUR(e.amount, e.currency); }, 0); };
    const paid = claimed.filter(function (e) { return e.status === 'Reimbursed'; });
    const avg = avgPayDays(claimed);
    root.innerHTML = '<div class="page">' +
      pageHead('Reports', 'Your submitted expenses for 2026, excluding drafts.', '<button type="button" class="btn btn-secondary" id="export-csv">' + icon('download') + 'Export CSV</button>') +
      '<div class="tiles tiles-3">' +
      '<div class="tile tile-static"><span class="tile-label">Claimed in 2026</span><span class="tile-amount">' + BW.money(sum(claimed)) + '</span><span class="tile-meta">' + claimed.length + ' expenses submitted</span></div>' +
      '<div class="tile tile-static"><span class="tile-label">Reimbursed</span><span class="tile-amount">' + BW.money(sum(paid)) + '</span><span class="tile-meta">' + paid.length + ' expenses paid</span></div>' +
      '<div class="tile tile-static"><span class="tile-label">Average time to payment</span><span class="tile-amount">' + (avg === null ? 'No data' : avg.toFixed(1) + ' days') + '</span><span class="tile-meta">From submission to payment</span></div>' +
      '</div>' +
      '<div class="report-grid">' +
      '<section class="card pad"><h2 class="card-title">Spend by category</h2>' + barsHtml(groupSum(claimed, function (e) { return e.category; }), function (k) { return k; }) + '</section>' +
      '<section class="card pad"><h2 class="card-title">Spend by cost centre</h2>' + barsHtml(groupSum(claimed, function (e) { return e.costCentre; }), BW.costCentreLabel) + '</section>' +
      '</div></div>';
    root.querySelector('#export-csv').addEventListener('click', function () {
      const blob = new Blob(['﻿' + csv(all)], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'brightwater-expenses-maya-patel.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      BW.showToast({ kind: 'success', title: 'Export ready', body: all.length + ' expenses exported to CSV.' });
    });
    return { title: 'Reports', nav: 'reports', crumbs: ['Reports'] };
  }

  /* ---------- policy ---------- */

  const LIMITS = [
    ['Travel', 'Standard class rail, economy flights. Taxis only when public transport is not reasonable.'],
    ['Meals', BW.money(P.mealLimitPerPerson) + ' per person per meal, including tip'],
    ['Accommodation', BW.money(180) + ' per night, ' + BW.money(220) + ' in capital cities'],
    ['Office supplies', BW.money(150) + ' per order without pre-approval'],
    ['Mileage', BW.money(P.mileageRate) + ' per km in a private car'],
    ['Other', 'Manager pre-approval above ' + BW.money(100)]
  ];

  function renderPolicy(root) {
    const limits = LIMITS.map(function (l) {
      return '<tr><td><span class="cat">' + BW.categoryIcon(l[0]) + esc(l[0]) + '</span></td><td>' + esc(l[1]) + '</td></tr>';
    }).join('');
    root.innerHTML = '<div class="page">' +
      pageHead('Expense policy', 'Policy FIN-POL-07, version 3.2, effective 1 September 2026. Owner: Finance.') +
      '<div class="policy-grid">' +
      '<article class="card pad policy">' +
      '<div class="policy-rules">' +
      '<div class="rule"><span class="rule-num">1</span><div><h3>Receipts</h3><p>Attach an itemised receipt for every expense over ' + BW.money(P.receiptThreshold) + '. A photo is fine if the merchant, date, items, VAT and total are readable. Card slips on their own are not accepted.</p></div></div>' +
      '<div class="rule"><span class="rule-num">2</span><div><h3>Submit within ' + P.submissionWindowDays + ' days</h3><p>Submit each expense within ' + P.submissionWindowDays + ' days of the date on the receipt. Late expenses need a short explanation in the business purpose and may be refused.</p></div></div>' +
      '<div class="rule"><span class="rule-num">3</span><div><h3>Explain the business purpose</h3><p>Say who the expense was for and why it was needed. For meals, enter the number of people so the per person amount can be checked.</p></div></div>' +
      '<div class="rule"><span class="rule-num">4</span><div><h3>Approval and payment</h3><p>Your manager approves the expense, then Finance checks the receipt and VAT. Approved expenses are paid to your bank account in the Friday payment run.</p></div></div>' +
      '<div class="rule"><span class="rule-num">5</span><div><h3>Not reimbursed</h3><p>Personal items, fines and penalties, travel upgrades, alcohol without a client present, and anything already paid with a company card.</p></div></div>' +
      '</div></article>' +
      '<section class="card table-card"><div class="card-head"><h2 class="card-title">Limits by category</h2></div>' +
      '<table class="table table-limits"><tbody>' + limits + '</tbody></table>' +
      '<div class="card-foot">' + icon('info') + '<span>Questions? Contact Finance at <strong>expenses@brightwater.example</strong></span></div></section>' +
      '</div></div>';
    return { title: 'Policy', nav: 'policy', crumbs: ['Policy'] };
  }

  /* ---------- settings ---------- */

  function toggle(id, label, desc, on) {
    return '<div class="toggle-row"><div><label class="toggle-label" for="' + id + '">' + esc(label) + '</label><div class="toggle-desc">' + esc(desc) + '</div></div>' +
      '<label class="switch"><input type="checkbox" role="switch" id="' + id + '"' + (on ? ' checked' : '') + '><span class="switch-track"><span class="switch-thumb"></span></span></label></div>';
  }

  function renderSettings(root) {
    const s = BW.getState().settings;
    const U = D.USER;
    const ccs = D.COST_CENTRES.map(function (c) {
      return '<option value="' + esc(c.id) + '"' + (c.id === s.defaultCostCentre ? ' selected' : '') + '>' + esc(c.id + ' ' + c.name) + '</option>';
    }).join('');
    const curs = D.CURRENCIES.map(function (c) {
      return '<option value="' + c.code + '"' + (c.code === s.defaultCurrency ? ' selected' : '') + '>' + c.code + '</option>';
    }).join('');
    const ro = function (label, value) { return '<div class="fact"><dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd></div>'; };
    root.innerHTML = '<div class="page">' +
      pageHead('Settings', 'Your profile, defaults for new expenses and notifications.', '<button type="button" class="btn btn-primary" id="save-settings">' + icon('check') + 'Save changes</button>') +
      '<div class="settings-grid">' +
      '<section class="card pad"><h2 class="card-title">Profile</h2><div class="profile"><span class="avatar avatar-lg">' + esc(U.initials) + '</span><div><div class="profile-name">' + esc(U.name) + '</div><div class="profile-role">' + esc(U.title) + ', ' + esc(U.department) + '</div></div></div>' +
      '<dl class="facts facts-2">' + ro('Email', U.email) + ro('Employee ID', U.employeeId) + ro('Office', U.office) + ro('Manager', U.manager) + '</dl>' +
      '<p class="muted-note">Profile details come from HR. Ask People Services to change them.</p></section>' +
      '<section class="card pad"><h2 class="card-title">Defaults for new expenses</h2>' +
      '<div class="field"><label class="label" for="s-cc">Default cost centre</label><select class="select" id="s-cc">' + ccs + '</select></div>' +
      '<div class="field"><label class="label" for="s-cur">Default currency</label><select class="select" id="s-cur">' + curs + '</select></div>' +
      '<div class="bank">' + icon('bank') + '<div><div class="bank-label">Reimbursement account</div><div class="bank-value">' + esc(U.iban) + '</div></div></div></section>' +
      '<section class="card pad"><h2 class="card-title">Notifications</h2>' +
      toggle('s-email', 'Email updates', 'When an expense is approved, returned or paid', s.notifyEmail) +
      toggle('s-teams', 'Microsoft Teams messages', 'Approval updates in the Brightwater Expenses app in Teams', s.notifyTeams) +
      toggle('s-weekly', 'Weekly summary', 'Monday overview of drafts and open expenses', s.notifyWeekly) +
      '</section></div></div>';
    root.querySelector('#save-settings').addEventListener('click', function () {
      const st = BW.getState();
      const settings = Object.assign({}, st.settings, {
        defaultCostCentre: root.querySelector('#s-cc').value,
        defaultCurrency: root.querySelector('#s-cur').value,
        notifyEmail: root.querySelector('#s-email').checked,
        notifyTeams: root.querySelector('#s-teams').checked,
        notifyWeekly: root.querySelector('#s-weekly').checked
      });
      if (BW.setState(Object.assign({}, st, { settings: settings }))) {
        BW.showToast({ kind: 'success', title: 'Settings saved', body: 'New expenses will use ' + BW.costCentreLabel(settings.defaultCostCentre) + ' and ' + settings.defaultCurrency + '.' });
      }
    });
    return { title: 'Settings', nav: 'settings', crumbs: ['Settings'] };
  }

  BW.views.approvals = renderApprovals;
  BW.views.reports = renderReports;
  BW.views.policy = renderPolicy;
  BW.views.settings = renderSettings;
})();
