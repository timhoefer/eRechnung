const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const listeners = {}, requests = [], initialized = [];
  const error = { hidden: true, textContent: 'Action failed' };
  const disclaimer = { textContent: 'Local data' };
  let focused = false, refreshed = 0;
  const button = { disabled: false, isConnected: false, focus: () => { focused = true; } };
  const dialog = {
    open: false, innerHTML: '', listeners: {}, error: null,
    showModal() { this.open = true; },
    close() { this.open = false; this.listeners.close?.(); },
    replaceChildren() { this.innerHTML = ''; },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    querySelector(selector) { return selector === '[data-agent-error]' ? this.error : { focus() {} }; },
    append(error) { this.error = error; },
    closest: () => true,
  };
  const section = {
    outerHTML: 'Access is off', dataset: { refreshUrl: '/agents/panel' },
    querySelector: () => dialog.open ? dialog : null,
    querySelectorAll(selector) {
      if (selector === 'button') return [button];
      if (selector === '[data-agent-error]') return [error];
      return dialog.open ? [dialog] : [];
    },
  };
  const elements = { 'agent-management': section, 'agent-disable-dialog': dialog, 'disclaimer-text': disclaimer };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_access.js'), 'utf8'), {
    document: { addEventListener: (name, fn) => { listeners[name] = fn; },
      getElementById: id => elements[id], querySelector: selector => selector === '[data-agent-error]' ? error : button,
      createElement: () => ({ dataset: {}, setAttribute() {} }) },
    window: { AgentSettings: { init: () => initialized.push('settings') }, AgentSetup: { init: () => initialized.push('setup') },
      refreshAgentSettings: async () => { refreshed++; } },
    FormData: class { constructor(form) { this.fields = { ...form.fields }; } append(k, v) { this.fields[k] = v; } },
    fetch: (url, options) => new Promise((resolve, reject) => { requests.push({ url, options, resolve, reject }); }),
  });
  const form = { action: { value: 'enable' }, getAttribute: () => '/agents/settings',
    fields: { csrf: 'fictional', return_to: 'settings' }, matches: () => true };
  return { requests, section, dialog, error, disclaimer, button, initialized, focused: () => focused, refreshed: () => refreshed,
    submit: submitter => listeners.submit({ target: form, submitter, preventDefault() {} }),
    escape() { let prevented = false; listeners.cancel({ target: dialog, preventDefault() { prevented = true; } }); return prevented; },
    cancel: () => listeners.click({ target: { closest: () => true } }),
    review() { const link = { href: '/agents/requests/fictional' }; listeners.click({button: 0, target: {
      closest: selector => selector === '[data-agent-cancel]' ? null : link }, preventDefault() {} }); },
    respond(data, status = 200) { requests.at(-1).resolve({ ok: status < 400, status, json: async () => data }); },
  };
}

test('updates only agent settings and disclaimer, suppresses double submission and initializes dialogs', async () => {
  const page = setup();
  const pending = page.submit();
  await page.submit();
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, '/agents/settings');
  assert.equal(page.button.disabled, true);
  assert.equal(page.section.outerHTML, 'Access is off');
  assert.equal(page.requests[0].options.body.fields.csrf, 'fictional');
  assert.equal(page.escape(), true);
  page.respond({ management: 'Access is on, no connection yet', disclaimer: 'Agent data processing' });
  await pending;
  assert.equal(page.section.outerHTML, 'Access is on, no connection yet');
  assert.equal(page.disclaimer.textContent, 'Agent data processing');
  assert.equal(page.button.disabled, false);
  assert.deepEqual(page.initialized, ['settings', 'setup']);
  assert.equal(page.focused(), true);
});

test('destructive and stale warnings require a new submit; cancel sends nothing', async () => {
  const page = setup();
  let pending = page.submit();
  page.respond({ confirmation: 'Connections will be removed' }); await pending;
  assert.equal(page.dialog.open, true);
  page.cancel();
  assert.equal(page.dialog.open, false);
  assert.equal(page.requests.length, 1);
  pending = page.submit();
  page.respond({ confirmation: 'Connections changed: review again' }, 409); await pending;
  assert.equal(page.dialog.innerHTML, 'Connections changed: review again');
  assert.equal(page.section.outerHTML, 'Access is off');
  pending = page.submit();
  page.respond({ management: 'Access is off', disclaimer: 'Local data' }); await pending;
  assert.equal(page.dialog.open, false);
});

test('a failed update preserves the form; a retry is always explicit', async () => {
  const page = setup();
  let pending = page.submit();
  page.respond({}, 403); await pending;
  assert.equal(page.error.hidden, false);
  assert.equal(page.button.disabled, false);
  assert.equal(page.section.outerHTML, 'Access is off');
  const retry = page.submit();
  page.respond({ management: 'Access is on', disclaimer: 'Agent data processing' }); await retry;
  assert.equal(page.error.hidden, true);
  pending = page.submit();
  page.respond({ confirmation: 'Warning' }); await pending;
  pending = page.submit();
  page.respond({}, 403); await pending;
  assert.equal(page.dialog.open, true);
  assert.equal(page.dialog.error.hidden, false);
  assert.equal(page.dialog.innerHTML, 'Warning');
});

test('review is read-only; sends the clicked decision once and refreshes archive only after closing result', async () => {
  const page = setup();
  page.review();
  assert.equal(page.requests[0].options.method, undefined);
  page.respond({ confirmation: 'Review exact change' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.refreshed(), 0);
  const pending = page.submit({ name: 'decision', value: 'deny' });
  assert.equal(page.requests[1].options.body.fields.decision, 'deny');
  page.respond({ confirmation: 'Denied', decided: true }); await pending;
  assert.equal(page.refreshed(), 0);
  page.cancel();
  assert.equal(page.refreshed(), 1);
  assert.equal(page.requests.length, 2);
});
