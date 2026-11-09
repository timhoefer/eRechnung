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
function memoryStorage() {
  const values = new Map();
  return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)};
}
function fixture({restore, scope = 'folder-a:all:2026', storage = memoryStorage(), href = 'http://localhost/validate', order = [0, 1, 2], pairs} = {}) {
  let entries = [element({quarter: '2026-Q1'}), element({quarter: '2026-Q2'}), element({quarter: '2026-Q1'})];
  entries.forEach((entry, i) => { entry.value = JSON.stringify([i === 0 ? 'default' : 'company', `Rechnung_${Math.max(0, i - 1)}.pdf`]); });
  entries = order.map(i => entries[i]);
  if (pairs) entries = pairs.map(pair => ({...element({quarter: '2026-Q1'}), value: JSON.stringify(pair)}));
  const quarters = [element({archiveQuarter: '2026-Q1'}), element({archiveQuarter: '2026-Q2'}), element({archiveQuarter: '2026-Q3'})];
  const toggle = element(), all = element(), count = element(), status = element(), submit = element();
  const toggleText = element();
  toggle.querySelector = selector => selector === '[data-archive-select-text]' ? toggleText : null;
  const form = element();
  form.action = '/export/csv?issuer=all';
  form.querySelector = () => submit;
  const card = element({archiveScope: scope, archiveSelectLabel: 'Select', archiveDoneLabel: 'Done', archiveCountLabel: '{n} selected', exportFailed: 'Failed', desktop: 'true'});
  card.querySelector = selector => ({'[data-archive-select]': toggle, '#archive-selection': form,
    '[data-archive-all]': all, '[data-archive-count]': count, '[data-archive-export-status]': status}[selector]);
  card.querySelectorAll = selector => ({'[data-archive-entry]:not(:disabled)': entries, '[data-archive-quarter]': quarters}[selector]);
  const calls = [];
  const context = {window: {location: {href}}, document: {querySelector: () => card, querySelectorAll: () => restore === undefined ? [card] : []},
    sessionStorage: storage, URL, URLSearchParams,
    FormData: class {constructor(form) { if (form.fields) return new URLSearchParams(form.fields); this.entries = entries.filter(e => e.checked).map(e => e.value); }},
    fetch: async (url, options) => { calls.push({url, options}); return {ok: true, json: async () => ({ok: true})}; }};
  vm.runInNewContext(source, context);
  if (restore !== undefined) {
    context.document.querySelectorAll = () => [card];
    context.window.ArchiveSelection.init(context.document, restore);
  }
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

test('sorting restores selection by issuer and file even when rows move and numbers overlap', () => {
  const before = fixture();
  before.toggle.listeners.click();
  before.entries[0].checked = true;
  const saved = before.context.window.ArchiveSelection.capture();
  const after = fixture({restore: saved, order: [1, 2, 0]});
  assert.equal(after.form.hidden, false);
  assert.equal(after.toggleText.textContent, 'Done');
  assert.deepEqual(after.entries.map(e => e.checked), [false, false, true]);
  assert.equal(after.count.textContent, '1 selected');
  assert.equal(after.quarters[0].indeterminate, true);
});

test('sorting keeps an empty selection mode open and excludes unavailable entries', () => {
  const before = fixture();
  before.toggle.listeners.click();
  const empty = fixture({restore: before.context.window.ArchiveSelection.capture()});
  assert.equal(empty.form.hidden, false);
  assert.equal(empty.count.textContent, '0 selected');
  before.entries[0].checked = true;
  const removed = fixture({restore: before.context.window.ArchiveSelection.capture(), order: [1, 2]});
  assert.equal(removed.count.textContent, '0 selected');
  assert.equal(removed.submit.disabled, true);
});

for (const scope of ['folder-b:all:2026', 'folder-a:company:2026', 'folder-a:all:2025']) {
  test(`selection is not restored in a different archive scope: ${scope}`, () => {
    const before = fixture();
    before.toggle.listeners.click();
    before.all.checked = true;
    before.all.listeners.change();
    const after = fixture({scope, restore: before.context.window.ArchiveSelection.capture()});
    assert.equal(after.form.hidden, true);
    assert.ok(after.entries.every(e => !e.checked));
  });
}

function filters(changes = {sort: 'number'}) {
  const defaults = {issuer: 'all', year: '2026', sort: 'created'};
  const fields = {...defaults, ...changes};
  return {action: '/validate', fields, querySelectorAll: () => Object.entries(fields).map(([name, value]) =>
    ({name, value, options: [{value: defaults[name], defaultSelected: true}]}))};
}

test('only a sorting change carries selection, never year or issuer changes', () => {
  const api = fixture().context.window.ArchiveSelection;
  assert.equal(api.isSortChange(filters()), true);
  for (const change of [{}, {year: '2025'}, {issuer: 'company'}, {sort: 'number', year: '2025'}]) {
    assert.equal(api.isSortChange(filters(change)), false);
  }
});

test('standalone sorting carries the selection to its exact destination once', () => {
  const storage = memoryStorage();
  const before = fixture({storage});
  before.toggle.listeners.click();
  before.entries[0].checked = true;
  before.context.window.ArchiveSelection.rememberSort(filters());
  const href = 'http://localhost/validate?issuer=all&year=2026&sort=number';
  const after = fixture({storage, href, order: [1, 2, 0]});
  assert.equal(after.form.hidden, false);
  assert.deepEqual(after.entries.map(e => e.checked), [false, false, true]);
  assert.equal(fixture({storage, href}).form.hidden, true);
});

test('standalone navigation cannot replay a selection on another page or after a filter change', () => {
  const storage = memoryStorage();
  const before = fixture({storage});
  before.toggle.listeners.click();
  before.context.window.ArchiveSelection.rememberSort(filters());
  assert.equal(fixture({storage, href: 'http://localhost/validate?issuer=company'}).form.hidden, true);
  before.context.window.ArchiveSelection.rememberSort(filters());
  before.context.window.ArchiveSelection.rememberSort(filters({year: '2025'}));
  assert.equal(storage.getItem('erechnung:archive-sort-selection'), null);
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

function rowEvent(entry, {interactive = false, type = 'click', key, cell = false} = {}) {
  const row = {querySelector: () => entry};
  const target = cell ? {} : row;
  target.closest = selector => selector === '.arch-row' ? row : interactive ? {} : null;
  return {type, key, target, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }};
}

test('clicking a row selects and deselects it without opening its PDF', () => {
  const f = fixture();
  f.toggle.listeners.click();
  const event = rowEvent(f.entries[0], {cell: true});
  f.card.listeners.click(event);
  assert.equal(f.entries[0].checked, true);
  assert.equal(f.count.textContent, '1 selected');
  assert.equal(f.quarters[0].indeterminate, true);
  assert.equal(event.stopped, true);
  f.card.listeners.click(event);
  assert.equal(f.entries[0].checked, false);
  assert.equal(f.count.textContent, '0 selected');
});

test('row selection preserves buttons, menus, links, and checkbox behavior', () => {
  const f = fixture();
  f.toggle.listeners.click();
  const event = rowEvent(f.entries[0], {interactive: true});
  f.card.listeners.click(event);
  assert.equal(f.entries[0].checked, false);
  assert.equal(event.prevented, false);
  assert.equal(event.stopped, false);
});

test('row shortcuts apply only in selection mode; unavailable rows do not open PDFs', () => {
  const f = fixture();
  const normal = rowEvent(f.entries[0]);
  f.card.listeners.click(normal);
  assert.equal(normal.stopped, false);
  f.toggle.listeners.click();
  for (const key of ['Enter', ' ']) {
    const event = rowEvent(f.entries[0], {type: 'keydown', key});
    const before = f.entries[0].checked;
    f.card.listeners.keydown(event);
    assert.equal(f.entries[0].checked, !before);
    assert.equal(event.stopped, true);
  }
  const otherKey = rowEvent(f.entries[0], {type: 'keydown', key: 'ArrowDown'});
  f.card.listeners.keydown(otherKey);
  assert.equal(otherKey.stopped, false);
  f.entries[0].disabled = true;
  const unavailable = rowEvent(f.entries[0]);
  f.card.listeners.click(unavailable);
  assert.equal(f.entries[0].checked, false);
  assert.equal(unavailable.stopped, true);
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
  assert.equal(f.calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(f.calls[0].options.body).entries, [JSON.parse(f.entries[1].value)]);
  assert.equal(f.submit.disabled, true);
  finish({ok: true, json: async () => ({ok: true})});
  await first;
  assert.equal(f.submit.disabled, false);
});

test('large selections use a single JSON request and retain all issuer/file pairs', async () => {
  const pairs = Array.from({length: 1001}, (_, i) => [i % 2 ? 'company' : 'default', `Rechnung_${i}.pdf`]);
  const f = fixture({pairs});
  f.all.checked = true;
  f.all.listeners.change();
  await f.form.listeners.submit({preventDefault() {}, stopPropagation() {}});
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(f.calls[0].options.body), {entries: pairs});
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
