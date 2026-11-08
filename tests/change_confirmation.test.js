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
