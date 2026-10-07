const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadDialog({ autoOpen = true, seen = false, fetchImpl = async () => ({ ok: true }) } = {}) {
  const handlers = {};
  const dialog = {
    open: false,
    dataset: { autoOpen: String(autoOpen), seen: String(seen), announcementId: "feature-1", seenUrl: "/whats-new/seen" },
    addEventListener: (name, fn) => { handlers[name] = fn; },
    showModal() { this.open = true; },
    async dismiss() { this.open = false; await handlers.close(); },
  };
  let click;
  const requests = [];
  const context = {
    document: { getElementById: () => dialog, addEventListener: (_, fn) => { click = fn; } },
    fetch: (...args) => { requests.push(args); return fetchImpl(...args); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../static/whats_new.js"), "utf8"), context);
  return { dialog, requests, reopen: () => click({ target: { closest: () => ({}) } }) };
}

test("showing news does not acknowledge it; closing acknowledges it once", async () => {
  const { dialog, requests, reopen } = loadDialog();
  assert.equal(dialog.open, true);
  assert.equal(requests.length, 0);
  await dialog.dismiss();
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/whats-new/seen");
  assert.deepEqual(JSON.parse(requests[0][1].body), { id: "feature-1" });
  reopen();
  assert.equal(dialog.open, true);
  await dialog.dismiss();
  assert.equal(requests.length, 1);
});

test("already read news opens only from settings", async () => {
  const { dialog, requests, reopen } = loadDialog({ autoOpen: false, seen: true });
  assert.equal(dialog.open, false);
  reopen();
  assert.equal(dialog.open, true);
  await dialog.dismiss();
  assert.equal(requests.length, 0);
});

for (const failure of [async () => ({ ok: false }), async () => { throw new Error("offline"); }]) {
  test("failed saving never prevents closing or marks news read, and can be retried", async () => {
    let attempts = 0;
    const { dialog, reopen } = loadDialog({ fetchImpl: () => ++attempts === 1 ? failure() : { ok: true } });
    await dialog.dismiss();
    assert.equal(dialog.open, false);
    assert.equal(dialog.dataset.seen, "false");
    reopen();
    await dialog.dismiss();
    assert.equal(dialog.dataset.seen, "true");
  });
}
