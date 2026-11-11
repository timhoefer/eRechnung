const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const warning = { de: 'Warnung vor Erneuerung', en: 'Warning before renewal' };
const credential = { de: 'Konfiguration: FICTIONAL-KEY', en: 'Configuration: FICTIONAL-KEY' };
const response = (views, status = 200, updated = false) => ({ ok: status === 200, status, json: async () => ({ views, updated }) });
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup(initialViews, language = 'de') {
  const handlers = {};
  const requests = [];
  const navigation = [];
  const renders = [];
  const close = {
    textContent: '×', setAttribute(name, value) { this[name] = value; },
    closest(selector) { return selector === '[data-close-setup]' ? this : null; },
  };
  const content = {
    innerHTML: '', selectedTab: null,
    querySelector() { return this.selectedTab ? { id: this.selectedTab } : null; },
    replaceChildren() { this.innerHTML = ''; this.selectedTab = null; },
  };
  const dialog = {
    open: false, scrollTop: 0,
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { if (name === 'open') this.open = false; },
    querySelectorAll() { return [close]; },
    addEventListener(name, handler) { handlers[name] = handler; },
    showModal() { this.open = true; },
    close() { this.open = false; handlers.close(); },
  };
  const link = {
    href: '/agents/connections/example/setup', focused: false,
    setAttribute() {}, addEventListener(_, handler) { handlers.open = handler; },
    focus() { this.focused = true; }, closest() { return { id: 'agent-connection-example' }; },
  };
  const elements = {
    'agent-setup-dialog': dialog, 'agent-setup-content': content,
    'agent-setup-error': { hidden: true }, 'agent-setup-title': { textContent: '' },
    'configuration-values-tab': { click() { content.selectedTab = 'configuration-values-tab'; } },
  };
  const initial = initialViews ? { textContent: JSON.stringify(initialViews), removed: false,
    remove() { this.removed = true; delete elements['agent-setup-initial']; } } : null;
  if (initial) elements['agent-setup-initial'] = initial;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_setup.js'), 'utf8'), {
    document: {
      documentElement: { lang: language }, getElementById: id => elements[id],
      querySelectorAll: () => [link],
      querySelector: selector => ({ click: () => navigation.push(selector) }),
      dispatchEvent(event) {
        assert.equal(event.type, 'agent-setup-rendered');
        renders.push(content.innerHTML);
        content.selectedTab = null; // Tab initialization selects the default JSON view.
      },
    },
    Event: class { constructor(type) { this.type = type; } },
    FormData: class { constructor(form) { this.fields = form.fields; } get(name) { return this.fields[name]; } },
    URLSearchParams,
    window: { location: { assign: value => navigation.push(value), reload: () => navigation.push('reload') } },
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
  });
  const event = target => ({ target, prevented: false, preventDefault() { this.prevented = true; } });
  return {
    dialog, content, close, link, elements, initial, requests, navigation, renders,
    open(modifiers = {}) { const e = { ...event(link), button: 0, ...modifiers }; handlers.open(e); return e; },
    click(target) { return handlers.click(event(target)); },
    submit(fields = { csrf: 'csrf-only', revision: 'reviewed-revision', confirm: 'renew' }) {
      handlers.submit(event({ action: fields.action ? { value: fields.action } : link.href,
        getAttribute: name => name === 'action' ? link.href : null, fields }));
    },
    escape() { const e = event(dialog); handlers.cancel(e); if (!e.prevented) dialog.close(); return e; },
  };
}

test('opening and cancelling only reads the warning; modified clicks retain the fallback link', async () => {
  const page = setup();
  assert.equal(page.open({ ctrlKey: true }).prevented, false);
  assert.equal(page.requests.length, 0);
  assert.equal(page.open().prevented, true);
  assert.equal(page.dialog.open, true);
  assert.equal(page.requests[0].url, page.link.href);
  assert.equal(page.requests[0].options.method, undefined);
  assert.equal(page.requests[0].options.cache, 'no-store');
  page.requests[0].resolve(response(warning));
  await settle();
  assert.equal(page.content.innerHTML, warning.de);
  await page.click(page.close);
  assert.equal(page.dialog.open, false);
  assert.equal(page.content.innerHTML, '');
  assert.equal(page.link.focused, true);
  assert.equal(page.requests.length, 1);
});

test('renewal requires an explicit submit; double clicks and Escape cannot discard an in-flight credential', async () => {
  const page = setup();
  page.open(); page.requests[0].resolve(response(warning)); await settle();
  page.submit(); page.submit();
  assert.equal(page.requests.length, 2);
  assert.equal(page.requests[1].options.method, 'POST');
  assert.equal(page.requests[1].options.body.fields.confirm, 'renew');
  assert.equal(page.requests[1].options.body.fields.revision, 'reviewed-revision');
  assert.equal(page.escape().prevented, true);
  assert.equal(page.dialog.open, true);
  page.requests[1].resolve(response(credential)); await settle();
  assert.equal(page.content.innerHTML, credential.de);
  assert.equal(page.dialog['aria-busy'], 'false');
  page.escape();
  assert.equal(page.content.innerHTML, '');
  page.open(); page.requests[2].resolve(response(warning)); await settle();
  assert.equal(page.content.innerHTML, warning.de);
  assert.equal(page.requests[2].options.method, undefined);
});

for (const language of ['de', 'en']) {
  test(`initial configuration opens in ${language} without another request and clears on close`, async () => {
    const page = setup(credential, language);
    assert.equal(page.initial.removed, true);
    assert.equal(page.dialog.open, true);
    assert.equal(page.requests.length, 0);
    assert.equal(page.dialog.lang, language);
    assert.equal(page.content.innerHTML, credential[language]);
    assert.equal(page.renders.length, 1);
    await page.click(page.close);
    assert.equal(page.dialog.open, false);
    assert.equal(page.content.innerHTML, '');
    assert.deepEqual(page.navigation, []);
    assert.equal(page.requests.length, 0);
  });
}

test('stale renewal displays the new warning and network errors never retry the destructive POST', async () => {
  const page = setup();
  page.open(); page.requests[0].resolve(response(warning)); await settle();
  page.submit(); page.requests[1].resolve(response({ de: 'Geändert: erneut prüfen', en: 'Changed: review again' }, 409)); await settle();
  assert.equal(page.content.innerHTML, 'Geändert: erneut prüfen');
  page.submit(); page.requests[2].reject(new Error('Response lost')); await settle();
  assert.equal(page.requests.length, 3);
  assert.equal(page.elements['agent-setup-error'].hidden, false);
  assert.match(page.elements['agent-setup-error'].textContent, /bisherige bereits ungültig/);
  assert.equal(page.escape().prevented, false);
});

for (const action of ['rename', 'permissions']) {
  test(`${action} changes wait for submit; closing an unsaved editor does not post`, async () => {
    const page = setup();
    page.open(); page.requests[0].resolve(response(warning)); await settle();
    page.content.innerHTML = 'Unsaved input';
    page.escape();
    assert.equal(page.requests.length, 1);
    assert.deepEqual(page.navigation, []);
    page.open(); page.requests[1].resolve(response(warning)); await settle();
    assert.equal(page.content.innerHTML, warning.de);
    page.submit({ action, revision: 'current', csrf: 'csrf-only' });
    assert.equal(page.requests[2].url, page.link.href);
    assert.equal(page.requests[2].options.body.fields.action, action);
    assert.equal(page.requests[2].options.body.fields.confirm, undefined);
    page.requests[2].resolve(response({ de: 'Gespeichert', en: 'Saved' }, 200, true)); await settle();
    assert.equal(page.dialog.open, true);
    assert.deepEqual(page.navigation, []);
    // A later deliberate key renewal is not lost through a premature refresh.
    page.submit(); page.requests[3].resolve(response(credential)); await settle();
    assert.equal(page.content.innerHTML, credential.de);
    assert.deepEqual(page.navigation, []);
    page.escape();
    assert.deepEqual(page.navigation, ['reload']);
  });
}

test('uncertain permission save is never retried automatically and refreshes on close', async () => {
  const page = setup();
  page.open(); page.requests[0].resolve(response(warning)); await settle();
  page.submit({ action: 'permissions', revision: 'current' });
  page.requests[1].reject(new Error('Response lost')); await settle();
  assert.equal(page.requests.length, 2);
  assert.equal(page.elements['agent-setup-error'].hidden, false);
  assert.match(page.elements['agent-setup-error'].textContent, /aktuellen Stand/);
  page.escape();
  assert.deepEqual(page.navigation, ['reload']);
});
