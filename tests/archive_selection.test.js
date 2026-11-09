const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/archive_selection.js'), 'utf8');

function element(data = {}) {
  return {dataset: data, checked: false, disabled: false, hidden: true, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(name, value) { this[name] = value; }};
}
function fixture() {
  const entries = [element({quarter: '2026-Q1'}), element({quarter: '2026-Q2'}), element({quarter: '2026-Q1'})];
  entries.forEach((entry, i) => { entry.value = JSON.stringify([i === 0 ? 'default' : 'company', `Rechnung_${i}.pdf`]); });
  const quarters = [element({archiveQuarter: '2026-Q1'}), element({archiveQuarter: '2026-Q2'}), element({archiveQuarter: '2026-Q3'})];
  const toggle = element(), all = element(), count = element(), status = element(), submit = element();
  const toggleText = element();
  toggle.querySelector = selector => selector === '[data-archive-select-text]' ? toggleText : null;
  const form = element();
  form.action = '/export/csv?issuer=all';
  form.querySelector = () => submit;
  const card = element({archiveSelectLabel: 'Select', archiveDoneLabel: 'Done', archiveCountLabel: '{n} selected', exportFailed: 'Failed', desktop: 'true'});
  card.querySelector = selector => ({'[data-archive-select]': toggle, '#archive-selection': form,
    '[data-archive-all]': all, '[data-archive-count]': count, '[data-archive-export-status]': status}[selector]);
  card.querySelectorAll = selector => ({'[data-archive-entry]:not(:disabled)': entries, '[data-archive-quarter]': quarters}[selector]);
  const calls = [];
  const context = {window: {}, document: {querySelectorAll: () => [card]},
    FormData: class {constructor() { this.entries = entries.filter(e => e.checked).map(e => e.value); }},
    fetch: async (url, options) => { calls.push({url, options}); return {ok: true, json: async () => ({ok: true})}; }};
  vm.runInNewContext(source, context);
  return {context, card, entries, quarters, toggle, toggleText, all, count, status, submit, form, calls};
}

test('select mode reveals controls; Done clears selection and restores the table', () => {
  const f = fixture();
  assert.equal(f.toggle.hidden, false);
  f.toggle.listeners.click();
  assert.equal(f.form.hidden, false);
  assert.equal(f.card.dataset.selecting, 'true');
  assert.equal(f.toggleText.textContent, 'Done');
  f.all.checked = true;
  f.all.listeners.change();
  assert.ok(f.entries.every(e => e.checked));
  assert.equal(f.count.textContent, '3 selected');
  f.toggle.listeners.click();
  assert.ok(f.entries.every(e => !e.checked));
  assert.equal(f.form.hidden, true);
  assert.equal(f.card.dataset.selecting, 'false');
  assert.equal(f.toggleText.textContent, 'Select');
});

test('quarter selection finds non-adjacent invoices and preserves partial states', () => {
  const f = fixture();
  f.toggle.listeners.click();
  f.quarters[0].checked = true;
  f.quarters[0].listeners.change();
  assert.deepEqual(f.entries.map(e => e.checked), [true, false, true]);
  assert.equal(f.all.indeterminate, true);
  assert.equal(f.quarters[2].disabled, true);
  f.entries[0].checked = false;
  f.entries[0].listeners.change();
  assert.equal(f.quarters[0].indeterminate, true);
  assert.equal(f.count.textContent, '1 selected');
});

test('export submits only checked identities and blocks double submissions', async () => {
  const f = fixture();
  let finish;
  f.context.fetch = (url, options) => { f.calls.push({url, options}); return new Promise(resolve => { finish = resolve; }); };
  f.entries[1].checked = true;
  f.entries[1].listeners.change();
  const event = {preventDefault() {}, stopPropagation() {}};
  const first = f.form.listeners.submit(event);
  await f.form.listeners.submit(event);
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.calls[0].options.body.entries, [f.entries[1].value]);
  assert.equal(f.submit.disabled, true);
  finish({ok: true, json: async () => ({ok: true})});
  await first;
  assert.equal(f.submit.disabled, false);
});

test('failed export retains selection and announces an error', async () => {
  const f = fixture();
  f.context.fetch = async () => ({ok: false});
  f.entries[0].checked = true;
  await f.form.listeners.submit({preventDefault() {}, stopPropagation() {}});
  assert.equal(f.status.textContent, 'Failed');
  assert.equal(f.entries[0].checked, true);
  assert.equal(f.submit.disabled, false);
});
