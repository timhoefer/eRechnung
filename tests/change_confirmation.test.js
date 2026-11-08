const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function harness(responses, answers = ['confirm']) {
  const calls = [], prompts = [];
  const nodes = {
    'change-title': {}, 'change-message': {},
    'change-rows': {children: [], replaceChildren() { this.children = []; }, appendChild(row) { this.children.push(row); }},
  };
  let close;
  nodes['change-confirmation'] = {
    returnValue: '',
    addEventListener(event, callback) { assert.equal(event, 'close'); close = callback; },
    showModal() {
      prompts.push(nodes['change-title'].textContent);
      this.returnValue = answers.shift() || 'cancel';
      close();
    },
  };
  const context = vm.createContext({
    window: {}, Headers, URLSearchParams,
    document: {
      getElementById: id => nodes[id],
      createElement(tag) { return {tag, children: [], appendChild(cell) { this.children.push(cell); }}; },
    },
    async fetch(url, options) {
      calls.push({url, body: options.body, headers: new Headers(options.headers)});
      const response = responses.shift();
      assert.ok(response, 'unexpected request');
      return response;
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/change_confirmation.js'), 'utf8'), context);
  return {api: context.window.ChangeConfirmation, nodes, calls, prompts};
}
function challenge(token = 'once', title = 'Delete invoice') {
  return {status: 428, json: async () => ({confirmation: {
    token, title, message: 'Cannot be undone', cancel_url: '/changes/cancel',
    details: [{label: '<script>unsafe</script>', before: 'Invoice 1', after: 'Deleted'}],
  }})};
}
const success = {status: 200, ok: true};

test('confirmation retries the captured operation with the issued token', async () => {
  const h = harness([challenge(), success]);
  const body = new URLSearchParams({filename: 'Invoice.pdf'});
  assert.equal(await h.api.fetch('/archive/delete', {method: 'POST', body}), success);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].headers.has('X-Change-Confirmation'), false);
  assert.equal(h.calls[1].headers.get('X-Change-Confirmation'), 'once');
  assert.equal(h.calls[1].body, body);
  assert.equal(h.calls[1].url, '/archive/delete');
  assert.deepEqual(h.prompts, ['Delete invoice']);
  assert.equal(h.nodes['change-rows'].children[0].children[0].textContent, '<script>unsafe</script>');
  assert.equal(h.nodes['change-rows'].children[0].children[0].innerHTML, undefined);
});

test('cancel revokes the pending token and does not retry the destructive operation', async () => {
  const h = harness([challenge(), {status: 204}], ['cancel']);
  await assert.rejects(h.api.fetch('/archive/delete', {method: 'POST'}), {name: 'AbortError'});
  assert.deepEqual(h.calls.map(c => c.url), ['/archive/delete', '/changes/cancel']);
  assert.equal(h.calls[1].body.get('token'), 'once');
});

test('a changed server state requires another visible confirmation', async () => {
  const h = harness([challenge('old'), challenge('new', 'Newer invoice'), success], ['confirm', 'confirm']);
  assert.equal(await h.api.fetch('/archive/delete', {method: 'POST'}), success);
  assert.deepEqual(h.prompts, ['Delete invoice', 'Newer invoice']);
  assert.equal(h.calls[2].headers.get('X-Change-Confirmation'), 'new');
});

test('cancelling a revised proposal never sends the new token to the write endpoint', async () => {
  const h = harness([challenge('old'), challenge('new'), {status: 204}], ['confirm', 'cancel']);
  await assert.rejects(h.api.fetch('/archive/delete', {method: 'POST'}), {name: 'AbortError'});
  assert.equal(h.calls.filter(c => c.url === '/archive/delete').length, 2);
  assert.equal(h.calls[2].url, '/changes/cancel');
});

test('autosave returns a pending result without opening or approving a dialog', async () => {
  const response = challenge();
  const h = harness([response]);
  assert.equal(await h.api.fetch('/settings/autosave', {method: 'POST'}, false), response);
  assert.equal(h.calls.length, 1);
  assert.equal(h.prompts.length, 0);
});

test('unchanged data and new records do not prompt', async () => {
  const h = harness([success]);
  assert.equal(await h.api.fetch('/customers/save', {method: 'POST'}), success);
  assert.equal(h.prompts.length, 0);
});

test('an unrelated HTTP error is never treated as an approval request', async () => {
  const response = {status: 409};
  const h = harness([response]);
  assert.equal(await h.api.fetch('/settings/autosave', {method: 'POST'}), response);
  assert.equal(h.calls.length, 1);
});

function cancellationPage(exportDraft = false) {
  const button = {disabled: false}, error = {hidden: true};
  let submit, finish, navigated = false;
  const form = {action: '/changes/cancel', dataset: {draftKey: exportDraft ? 'erechnung:lang:scope:issuer' : ''},
    addEventListener(type, handler) { submit = handler; }};
  const original = {};
  let stored, destination;
  const context = vm.createContext({
    window: {location: {assign(url) { destination = url; }}},
    document: {getElementById: id => id === 'change-cancel-form' ? form : id === 'change-submit-form' ? original : error},
    FormData: class extends URLSearchParams { constructor(source) { super(source === original
      ? [['buyer_name', 'Customer'], ['description', 'First line'], ['description', 'Second line'], ['_change_confirmation', 'old-token']]
      : [['token', 'pending-token'], ['back', '/?issuer=default']]); } },
    sessionStorage: {setItem(key, value) { stored = {key, fields: JSON.parse(value)}; }},
    history: {back() { navigated = true; }},
    fetch: (url, options) => {
      assert.equal(url, '/changes/cancel');
      assert.equal(options.method, 'POST');
      assert.equal(options.body.get('token'), 'pending-token');
      assert.equal(options.headers['X-Requested-With'], 'fetch');
      return new Promise(resolve => { finish = resolve; });
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/change_confirmation.js'), 'utf8'), context);
  return {button, error, submit: () => submit({submitter: button, preventDefault() {}}),
    finish: response => finish(response), navigated: () => navigated,
    stored: () => stored, destination: () => destination};
}

test('fallback cancellation waits for server revocation before restoring the draft', async () => {
  const h = cancellationPage();
  const pending = h.submit();
  assert.equal(h.button.disabled, true);
  assert.equal(h.navigated(), false);
  h.finish({ok: true});
  await pending;
  assert.equal(h.navigated(), true);
  assert.equal(h.error.hidden, true);
});

test('failed fallback cancellation stays on the page and allows retry', async () => {
  const h = cancellationPage();
  const pending = h.submit();
  h.finish({ok: false});
  await pending;
  assert.equal(h.navigated(), false);
  assert.equal(h.button.disabled, false);
  assert.equal(h.error.hidden, false);
  const retry = h.submit();
  h.finish({ok: true});
  await retry;
  assert.equal(h.navigated(), true);
});

test('cancelled export restores customer and every invoice line without retaining the approval token', async () => {
  const h = cancellationPage(true);
  const pending = h.submit();
  assert.equal(h.stored(), undefined);
  h.finish({ok: true});
  await pending;
  assert.deepEqual(h.stored(), {key: 'erechnung:lang:scope:issuer', fields: {
    buyer_name: ['Customer'], description: ['First line', 'Second line'],
  }});
  assert.equal(h.destination(), '/?issuer=default');
  assert.equal(h.navigated(), false);
});
