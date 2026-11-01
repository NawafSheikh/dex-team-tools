/* Brightwater Expenses: router, navigation and boot. Visit #reset to restore the demo data. */
(function () {
  'use strict';

  const BW = window.BW;
  const esc = BW.esc;
  const icon = BW.icon;

  const NAV = [
    { id: 'expenses', label: 'My expenses', href: '#/expenses', icon: 'receipt' },
    { id: 'approvals', label: 'Approvals', href: '#/approvals', icon: 'approvals' },
    { id: 'reports', label: 'Reports', href: '#/reports', icon: 'reports' },
    { id: 'policy', label: 'Policy', href: '#/policy', icon: 'policy' },
    { id: 'settings', label: 'Settings', href: '#/settings', icon: 'settings' }
  ];

  let activeNav = 'expenses';

  function pendingApprovals() {
    return BW.getState().approvals.filter(function (a) { return a.status === 'Pending'; }).length;
  }

  function renderNav() {
    const pending = pendingApprovals();
    document.getElementById('nav').innerHTML = NAV.map(function (n) {
      const active = n.id === activeNav;
      const badge = n.id === 'approvals' && pending ? '<span class="nav-badge" aria-label="' + pending + ' waiting">' + pending + '</span>' : '';
      return '<a class="nav-item' + (active ? ' is-active' : '') + '" href="' + n.href + '"' + (active ? ' aria-current="page"' : '') + '>' +
        icon(n.icon) + '<span>' + esc(n.label) + '</span>' + badge + '</a>';
    }).join('');
  }

  function renderCrumbs(crumbs) {
    document.getElementById('crumbs').innerHTML = crumbs.map(function (c, i) {
      const last = i === crumbs.length - 1;
      if (last) return '<span class="crumb crumb-current">' + esc(c) + '</span>';
      return '<a class="crumb" href="#/expenses">' + esc(c) + '</a><span class="crumb-sep">' + icon('chevronRight') + '</span>';
    }).join('');
  }

  function nextFriday() {
    const d = new Date();
    const add = (5 - d.getDay() + 7) % 7 || 7;
    d.setDate(d.getDate() + add);
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  }

  function parseRoute() {
    const parts = window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
    const head = parts[0] || 'expenses';
    if (head === 'expenses') {
      if (parts[1] === 'new') return { view: 'form', params: {} };
      if (parts[1] && parts[2] === 'edit') return { view: 'form', params: { id: parts[1] } };
      if (parts[1]) return { view: 'detail', params: { id: parts[1] } };
      return { view: 'list', params: {} };
    }
    if (['approvals', 'reports', 'policy', 'settings'].indexOf(head) !== -1) return { view: head, params: {} };
    return { view: 'list', params: {} };
  }

  function route() {
    if (window.location.hash === '#reset') {
      BW.resetState();
      BW.clearForm();
      window.location.replace('#/expenses');
      return;
    }
    const r = parseRoute();
    if (r.view !== 'form' && r.view !== 'policy') BW.clearForm();
    const root = document.getElementById('view');
    const meta = BW.views[r.view](root, r.params);
    activeNav = meta.nav;
    renderNav();
    renderCrumbs(meta.crumbs);
    document.title = meta.title + ' | Brightwater Expenses';
    window.scrollTo(0, 0);
    root.scrollTop = 0;
  }

  function boot() {
    document.getElementById('payrun-date').textContent = nextFriday();
    window.addEventListener('dragover', function (ev) { ev.preventDefault(); });
    window.addEventListener('drop', function (ev) { ev.preventDefault(); });
    window.addEventListener('hashchange', route);
    BW.refreshNav = renderNav;
    route();
    const problem = BW.takeLoadProblem();
    if (problem) BW.showToast({ kind: 'error', title: 'Storage problem', body: problem });
  }

  boot();
})();
