/* New expense / edit draft form: receipt upload, validation, save and submit. */
(function () {
  'use strict';

  const BW = window.BW;
  const D = BW.D;
  const P = D.POLICY;
  const esc = BW.esc;
  const icon = BW.icon;

  const ACCEPTED = ['image/png', 'image/jpeg', 'image/webp'];
  const MAX_BYTES = 10 * 1024 * 1024;
  const MAX_EDGE = 1600;
  const PURPOSE_MAX = 500;

  const FIELD_ORDER = [
    ['receipt', 'Receipt'], ['merchant', 'Merchant'], ['date', 'Date'], ['amount', 'Amount'],
    ['category', 'Category'], ['costCentre', 'Cost centre'], ['attendees', 'Number of people'],
    ['purpose', 'Business purpose'], ['confirm', 'Policy confirmation']
  ];

  let fs = null;

  /* ---------- state ---------- */

  function blankForm() {
    const settings = BW.getState().settings;
    return {
      key: 'new', id: null, receipt: null, receiptError: null,
      merchant: '', date: BW.todayISO(), amount: '', currency: settings.defaultCurrency || 'EUR',
      category: '', costCentre: settings.defaultCostCentre || 'OPS-210', attendees: '1',
      purpose: '', confirm: false, touched: {}
    };
  }

  function formFromExpense(e) {
    return Object.assign(blankForm(), {
      key: e.id, id: e.id, receipt: e.receipt || null, merchant: e.merchant, date: e.date,
      amount: Number(e.amount).toFixed(2), currency: e.currency, category: e.category,
      costCentre: e.costCentre, attendees: String(e.attendees || 1), purpose: e.purpose || ''
    });
  }

  function update(patch) {
    fs = Object.assign({}, fs, patch);
  }

  function touch(field) {
    fs = Object.assign({}, fs, { touched: Object.assign({}, fs.touched, { [field]: true }) });
  }

  function parseAmount(raw) {
    const cleaned = String(raw || '').trim().replace(/\s/g, '').replace(',', '.');
    if (!/^\d+(\.\d{0,2})?$/.test(cleaned)) return NaN;
    return Number(cleaned);
  }

  /* ---------- validation ---------- */

  function validate(f) {
    const errors = {};
    const warnings = {};
    const today = BW.todayISO();
    const amount = parseAmount(f.amount);
    const amountEUR = Number.isFinite(amount) ? BW.toEUR(amount, f.currency) : 0;

    if (!f.merchant.trim()) errors.merchant = 'Enter the merchant name as it appears on the receipt.';

    if (!f.date) errors.date = 'Enter the date on the receipt.';
    else if (f.date > today) errors.date = 'The date cannot be in the future.';
    else if (BW.daysBetween(f.date, today) > P.submissionWindowDays) {
      warnings.date = 'Older than ' + P.submissionWindowDays + ' days. Explain the late submission in the business purpose.';
    }

    if (!String(f.amount).trim()) errors.amount = 'Enter the total amount paid.';
    else if (!Number.isFinite(amount) || amount <= 0) errors.amount = 'Enter an amount greater than 0, for example 38.40.';
    else if (amountEUR > 10000) errors.amount = 'Amounts over ' + BW.money(10000) + ' need a purchase order instead.';

    if (!f.category) errors.category = 'Choose a category.';
    if (!f.costCentre) errors.costCentre = 'Choose a cost centre.';

    if (f.category === 'Meals') {
      const people = parseInt(f.attendees, 10);
      if (!people || people < 1 || people > 50) errors.attendees = 'Enter how many people the meal was for.';
      else if (amountEUR / people > P.mealLimitPerPerson) warnings.meals = amountEUR / people;
    }

    if (f.category !== 'Mileage' && amountEUR > P.receiptThreshold && !f.receipt) {
      errors.receipt = 'A receipt is required for expenses over ' + BW.money(P.receiptThreshold) + '.';
    }

    const purpose = f.purpose.trim();
    if (!purpose) errors.purpose = 'Enter the business purpose.';
    else if (purpose.length < P.purposeMinLength) errors.purpose = 'Add a little more detail, at least ' + P.purposeMinLength + ' characters.';

    if (!f.confirm) errors.confirm = 'Confirm that this expense follows the expense policy.';

    return { errors: errors, warnings: warnings, amount: amount, amountEUR: amountEUR };
  }

  function visible(field, f) {
    if (f.touched.all) return true;
    if (field === 'receipt') return !!(f.touched.receipt || f.touched.amount);
    return !!f.touched[field];
  }

  /* ---------- markup ---------- */

  function options(list, selected, placeholder) {
    const head = placeholder ? '<option value="" disabled' + (selected ? '' : ' selected') + '>' + esc(placeholder) + '</option>' : '';
    return head + list.map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (o.value === selected ? ' selected' : '') + '>' + esc(o.label) + '</option>';
    }).join('');
  }

  function msg(field) {
    return '<p class="field-msg" id="msg-' + field + '" aria-live="polite"></p>';
  }

  function zoneHtml(f) {
    if (!f.receipt) {
      return '<div class="dz-empty">' +
        '<span class="dz-icon">' + icon('upload') + '</span>' +
        '<div class="dz-title">Drag and drop your receipt here</div>' +
        '<div class="dz-or">or</div>' +
        '<button type="button" class="btn btn-secondary" data-browse>Browse files</button>' +
        '<div class="dz-hint">PNG, JPG or WEBP, up to 10 MB</div></div>';
    }
    return '<div class="dz-filled">' +
      '<div class="dz-preview"><img src="' + f.receipt.dataUrl + '" alt="Uploaded receipt ' + esc(f.receipt.name) + '"></div>' +
      '<div class="dz-file"><span class="dz-file-icon">' + icon('check') + '</span>' +
      '<span class="dz-file-text"><span class="dz-file-name">' + esc(f.receipt.name) + '</span>' +
      '<span class="dz-file-size">' + esc(BW.fileSize(f.receipt.size)) + ', uploaded</span></span>' +
      '<button type="button" class="btn btn-ghost btn-sm btn-icon" data-browse aria-label="Replace receipt" title="Replace receipt">' + icon('upload') + '</button>' +
      '<button type="button" class="btn btn-ghost btn-sm btn-icon" id="dz-remove" aria-label="Remove receipt" title="Remove receipt">' + icon('trash') + '</button></div></div>';
  }

  function formHtml(f) {
    const cats = D.CATEGORIES.map(function (c) { return { value: c.id, label: c.id }; });
    const ccs = D.COST_CENTRES.map(function (c) { return { value: c.id, label: c.id + ' ' + c.name }; });
    const curs = D.CURRENCIES.map(function (c) { return { value: c.code, label: c.code }; });
    const title = f.id ? 'Edit draft ' + esc(f.id) : 'New expense';
    return '<div class="page">' +
      '<div class="page-head">' +
      '<div><a class="back" href="' + (f.id ? '#/expenses/' + esc(f.id) : '#/expenses') + '">' + icon('chevronLeft') + (f.id ? esc(f.id) : 'My expenses') + '</a>' +
      '<h1>' + title + '</h1><p class="sub">Add the receipt and the details. ' + esc(D.USER.manager) + ' approves expenses you submit.</p></div>' +
      '</div>' +
      '<form class="card form-card" id="expense-form" novalidate>' +
      '<div class="form-grid">' +
      '<section class="receipt-col">' +
      '<div class="label-row"><label for="f-receipt" class="label">Receipt</label><span class="label-hint">Required over ' + BW.money(P.receiptThreshold) + '</span></div>' +
      '<input type="file" id="f-receipt" class="sr-only" accept="' + ACCEPTED.join(',') + '" aria-describedby="msg-receipt">' +
      '<div class="dropzone" id="dropzone">' + zoneHtml(f) + '</div>' + msg('receipt') +
      '</section>' +
      '<section class="fields-col">' +
      '<div class="field span-2" data-field="merchant"><label class="label" for="f-merchant">Merchant</label>' +
      '<input class="input" id="f-merchant" name="merchant" type="text" autocomplete="off" placeholder="For example, Harbour Cafe" value="' + esc(f.merchant) + '" aria-describedby="msg-merchant">' + msg('merchant') + '</div>' +
      '<div class="field" data-field="date"><label class="label" for="f-date">Date</label>' +
      '<input class="input" id="f-date" name="date" type="date" max="' + BW.todayISO() + '" value="' + esc(f.date) + '" aria-describedby="msg-date">' + msg('date') + '</div>' +
      '<div class="field" data-field="amount"><label class="label" for="f-amount">Amount</label>' +
      '<div class="input-group"><input class="input" id="f-amount" name="amount" type="text" inputmode="decimal" autocomplete="off" placeholder="0.00" value="' + esc(f.amount) + '" aria-describedby="msg-amount">' +
      '<label class="sr-only" for="f-currency">Currency</label><select class="select select-currency" id="f-currency" name="currency">' + options(curs, f.currency) + '</select></div>' + msg('amount') + '</div>' +
      '<div class="field" data-field="category"><label class="label" for="f-category">Category</label>' +
      '<select class="select" id="f-category" name="category" aria-describedby="msg-category">' + options(cats, f.category, 'Select a category') + '</select>' + msg('category') + '</div>' +
      '<div class="field" data-field="costCentre"><label class="label" for="f-costCentre">Cost centre</label>' +
      '<select class="select" id="f-costCentre" name="costCentre" aria-describedby="msg-costCentre">' + options(ccs, f.costCentre, 'Select a cost centre') + '</select>' + msg('costCentre') + '</div>' +
      '<div class="field" data-field="attendees" id="row-attendees" hidden><label class="label" for="f-attendees">Number of people</label>' +
      '<input class="input" id="f-attendees" name="attendees" type="number" min="1" max="50" step="1" value="' + esc(f.attendees) + '" aria-describedby="msg-attendees">' + msg('attendees') + '</div>' +
      '<div class="field per-person" id="row-perperson" hidden><span class="label">Per person</span><div class="readout" id="perperson">' + BW.money(0) + '</div><p class="field-msg field-msg-muted">Limit ' + BW.money(P.mealLimitPerPerson) + ' per person</p></div>' +
      '<div class="callout callout-warn span-2" id="warn-meals" role="alert" hidden></div>' +
      '<div class="field span-2" data-field="purpose"><div class="label-row"><label class="label" for="f-purpose">Business purpose</label><span class="label-hint" id="purpose-count">0 / ' + PURPOSE_MAX + '</span></div>' +
      '<textarea class="textarea" id="f-purpose" name="purpose" rows="3" maxlength="' + PURPOSE_MAX + '" placeholder="Who was it for and why was it needed? For example, lunch with the Van Dijk Transport account manager to agree winter routes." aria-describedby="msg-purpose">' + esc(f.purpose) + '</textarea>' + msg('purpose') + '</div>' +
      '<div class="field span-2" data-field="confirm"><label class="check" for="f-confirm"><input type="checkbox" id="f-confirm" name="confirm"' + (f.confirm ? ' checked' : '') + ' aria-describedby="msg-confirm">' +
      '<span class="check-box">' + icon('check') + '</span><span class="check-text">I confirm this expense follows the Brightwater expense policy</span></label>' +
      '<a class="policy-link" href="#/policy">Read the policy</a>' + msg('confirm') + '</div>' +
      '</section></div>' +
      '<footer class="form-foot"><div class="foot-status" id="foot-status"></div>' +
      '<div class="foot-actions"><button type="button" class="btn btn-ghost" id="btn-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-secondary" id="btn-draft">Save as draft</button>' +
      '<button type="submit" class="btn btn-primary" id="btn-submit" disabled>' + icon('send') + 'Submit for approval</button></div></footer>' +
      '</form></div>';
  }

  /* ---------- live refresh (no full re-render, keeps focus) ---------- */

  function setMsg(root, field, text, kind) {
    const el = root.querySelector('#msg-' + field);
    if (!el) return;
    el.className = 'field-msg' + (text ? ' field-msg-' + kind : '');
    el.innerHTML = text ? icon(kind === 'error' ? 'alertCircle' : 'alertTriangle') + '<span>' + esc(text) + '</span>' : '';
    const wrap = root.querySelector('[data-field="' + field + '"]');
    if (wrap) wrap.classList.toggle('has-error', kind === 'error' && !!text);
    const input = root.querySelector('#f-' + field);
    if (input) input.setAttribute('aria-invalid', kind === 'error' && text ? 'true' : 'false');
  }

  function refresh(root) {
    const v = validate(fs);
    FIELD_ORDER.forEach(function (pair) {
      const field = pair[0];
      if (field === 'receipt' && fs.receiptError) {
        setMsg(root, 'receipt', fs.receiptError, 'error');
      } else if (v.errors[field] && visible(field, fs)) {
        setMsg(root, field, v.errors[field], 'error');
      } else if (field === 'date' && v.warnings.date) {
        setMsg(root, 'date', v.warnings.date, 'warn');
      } else {
        setMsg(root, field, '', '');
      }
    });
    const zone = root.querySelector('#dropzone');
    zone.classList.toggle('has-error', !!(fs.receiptError || (v.errors.receipt && visible('receipt', fs))));
    zone.classList.toggle('is-filled', !!fs.receipt);

    const meals = fs.category === 'Meals';
    root.querySelector('#row-attendees').hidden = !meals;
    root.querySelector('#row-perperson').hidden = !meals;
    const people = parseInt(fs.attendees, 10) || 1;
    root.querySelector('#perperson').textContent = BW.money(v.amountEUR / people);
    const warn = root.querySelector('#warn-meals');
    warn.hidden = !v.warnings.meals;
    if (v.warnings.meals) {
      warn.innerHTML = icon('alertTriangle') + '<div><strong>Over the meal limit.</strong> This meal is ' + esc(BW.money(v.warnings.meals)) +
        ' per person and the policy limit is ' + esc(BW.money(P.mealLimitPerPerson)) + ' per person. You can still submit it, but explain the reason in the business purpose so ' +
        esc(D.USER.manager) + ' can approve the difference.</div>';
    }
    root.querySelector('#purpose-count').textContent = fs.purpose.length + ' / ' + PURPOSE_MAX;

    const missing = FIELD_ORDER.filter(function (p) { return v.errors[p[0]]; }).map(function (p) { return p[1]; });
    const status = root.querySelector('#foot-status');
    status.className = 'foot-status' + (missing.length ? '' : ' is-ready');
    status.innerHTML = missing.length
      ? icon('info') + '<span><strong>To submit, complete:</strong> ' + esc(missing.join(', ')) + '</span>'
      : icon('check') + '<span>Ready to submit to ' + esc(D.USER.manager) + '</span>';
    root.querySelector('#btn-submit').disabled = missing.length > 0;
    return v;
  }

  /* ---------- receipt upload ---------- */

  function readReceipt(file) {
    return new Promise(function (resolve, reject) {
      if (ACCEPTED.indexOf(file.type) === -1) {
        reject(new Error('That file type is not supported. Upload a PNG, JPG or WEBP image of the receipt.'));
        return;
      }
      if (file.size > MAX_BYTES) {
        reject(new Error('That file is larger than 10 MB. Upload a smaller photo of the receipt.'));
        return;
      }
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = function () {
        const scale = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.naturalWidth * scale);
        canvas.height = Math.round(img.naturalHeight * scale);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        resolve({ dataUrl: canvas.toDataURL('image/jpeg', 0.86), name: file.name, size: file.size, type: file.type });
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error('That image could not be opened. Try taking the photo again.'));
      };
      img.src = url;
    });
  }

  function acceptFile(root, file) {
    if (!file) return;
    readReceipt(file).then(function (receipt) {
      update({ receipt: receipt, receiptError: null });
      touch('receipt');
      renderZone(root);
      refresh(root);
    }).catch(function (err) {
      update({ receiptError: err.message });
      refresh(root);
    });
  }

  function renderZone(root) {
    root.querySelector('#dropzone').innerHTML = zoneHtml(fs);
  }

  function bindDropzone(root) {
    const zone = root.querySelector('#dropzone');
    const input = root.querySelector('#f-receipt');
    input.addEventListener('change', function () {
      acceptFile(root, input.files && input.files[0]);
      input.value = '';
    });
    zone.addEventListener('click', function (ev) {
      if (ev.target.closest('#dz-remove')) {
        update({ receipt: null, receiptError: null });
        touch('receipt');
        renderZone(root);
        refresh(root);
        return;
      }
      if (ev.target.closest('[data-browse]') || !fs.receipt) input.click();
    });
    let depth = 0;
    zone.addEventListener('dragenter', function (ev) { ev.preventDefault(); depth += 1; zone.classList.add('is-drag'); });
    zone.addEventListener('dragover', function (ev) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; });
    zone.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('is-drag'); });
    zone.addEventListener('drop', function (ev) {
      ev.preventDefault();
      depth = 0;
      zone.classList.remove('is-drag');
      acceptFile(root, ev.dataTransfer.files && ev.dataTransfer.files[0]);
    });
  }

  /* ---------- save / submit ---------- */

  function saveExpense(status, v) {
    const s = BW.getState();
    const existing = fs.id ? s.expenses.find(function (e) { return e.id === fs.id; }) : null;
    const id = existing ? existing.id : BW.nextExpenseId(s.expenses);
    const now = BW.nowStamp();
    const created = existing && existing.history.created ? existing.history.created : now;
    const history = status === 'Submitted' ? { created: created, submitted: now } : { created: created };
    const expense = {
      id: id, date: fs.date || BW.todayISO(), merchant: fs.merchant.trim(), category: fs.category || 'Other',
      amount: Math.round(v.amount * 100) / 100, currency: fs.currency, costCentre: fs.costCentre,
      attendees: fs.category === 'Meals' ? parseInt(fs.attendees, 10) || 1 : 1, purpose: fs.purpose.trim(),
      status: status, receipt: fs.receipt, receiptName: fs.receipt ? fs.receipt.name : null, history: history
    };
    const expenses = existing
      ? s.expenses.map(function (e) { return e.id === id ? expense : e; })
      : [expense].concat(s.expenses);
    const ok = BW.setState(Object.assign({}, s, { expenses: expenses }));
    return ok ? expense : null;
  }

  function bindActions(root) {
    const form = root.querySelector('#expense-form');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      touch('all');
      const v = refresh(root);
      if (Object.keys(v.errors).length) return;
      const saved = saveExpense('Submitted', v);
      if (!saved) return;
      fs = null;
      BW.highlightRow(saved.id);
      window.location.hash = '#/expenses';
      BW.showToast({
        kind: 'success',
        title: 'Expense ' + saved.id + ' submitted to your manager, ' + D.USER.manager,
        action: { label: 'View expense', href: '#/expenses/' + saved.id },
        duration: 9000
      });
    });
    root.querySelector('#btn-draft').addEventListener('click', function () {
      const v = validate(fs);
      if (v.errors.merchant || v.errors.amount) {
        touch('merchant');
        touch('amount');
        refresh(root);
        BW.showToast({ kind: 'error', title: 'Add a merchant and an amount to save a draft' });
        return;
      }
      const saved = saveExpense('Draft', v);
      if (!saved) return;
      fs = null;
      BW.highlightRow(saved.id);
      window.location.hash = '#/expenses';
      BW.showToast({ kind: 'info', title: 'Draft ' + saved.id + ' saved', body: 'You can finish and submit it later from My expenses.' });
    });
    root.querySelector('#btn-cancel').addEventListener('click', function () {
      const back = fs && fs.id ? '#/expenses/' + fs.id : '#/expenses';
      fs = null;
      window.location.hash = back;
    });
  }

  function bindFields(root) {
    const text = ['merchant', 'amount', 'purpose', 'attendees', 'date'];
    text.forEach(function (name) {
      const el = root.querySelector('#f-' + name);
      el.addEventListener('input', function () {
        update({ [name]: el.value });
        if (name === 'date' || name === 'attendees') touch(name);
        refresh(root);
      });
      el.addEventListener('blur', function () {
        if (name === 'amount') {
          const n = parseAmount(el.value);
          if (Number.isFinite(n) && n > 0) {
            el.value = n.toFixed(2);
            update({ amount: el.value });
          }
        }
        touch(name);
        refresh(root);
      });
    });
    ['currency', 'category', 'costCentre'].forEach(function (name) {
      const el = root.querySelector('#f-' + name);
      el.addEventListener('change', function () {
        update({ [name]: el.value });
        touch(name);
        refresh(root);
      });
    });
    const confirm = root.querySelector('#f-confirm');
    confirm.addEventListener('change', function () {
      update({ confirm: confirm.checked });
      touch('confirm');
      refresh(root);
    });
  }

  function renderForm(root, params) {
    const key = params.id || 'new';
    if (!fs || fs.key !== key) {
      if (params.id) {
        const e = BW.getState().expenses.find(function (x) { return x.id === params.id; });
        if (!e || e.status !== 'Draft') {
          window.location.replace('#/expenses/' + params.id);
          return { title: 'Expense', nav: 'expenses', crumbs: ['My expenses'] };
        }
        fs = formFromExpense(e);
      } else {
        fs = blankForm();
      }
    }
    root.innerHTML = formHtml(fs);
    bindDropzone(root);
    bindFields(root);
    bindActions(root);
    refresh(root);
    const crumb = fs.id ? 'Edit ' + fs.id : 'New expense';
    return { title: crumb, nav: 'expenses', crumbs: ['My expenses', crumb] };
  }

  BW.views.form = renderForm;
  BW.clearForm = function () { fs = null; };
})();
