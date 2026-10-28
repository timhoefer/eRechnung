// Load the real browser script with a minimal DOM; no copied application logic.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  const document = {
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener: () => {},
  };
  const context = vm.createContext({
    document,
    window: { addEventListener: () => {} },
    sessionStorage: { getItem: () => null },
    InvoiceCalc: require("../static/calc.js"),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"), context);
  return context;
}

function bankSelect(values) {
  const label = { textContent: "" };
  return {
    options: values.map((value) => ({ value, text: value })),
    selectedIndex: 0,
    get value() { return this.options[this.selectedIndex]?.value || ""; },
    set value(value) { this.selectedIndex = this.options.findIndex((o) => o.value === value); },
    parentElement: { querySelector: () => label },
    closest: () => null,
    label,
  };
}

for (const [name, stored, accounts, expected] of [
  ["international account number", "1234567890", ["DE123", "1234567890"], "1234567890"],
  ["account number before legacy index", "1", ["1", "DE123"], "1"],
  ["leading zeros in account number", "001234", ["DE123", "001234"], "001234"],
  ["IBAN after reordering", "DE456", ["DE456", "DE123"], "DE456"],
  ["legacy string index", "1", ["DE123", "DE456"], "DE456"],
  ["legacy numeric index", 1, ["DE123", "DE456"], "DE456"],
  ["removed account keeps default", "DE999", ["DE123", "DE456"], "DE123"],
]) {
  test(`applyDraft restores bank selection: ${name}`, () => {
    const app = loadApp();
    const select = bankSelect(accounts);
    const form = { querySelector: (s) => s === '[name="bank_account"]' ? select : null };
    app.document.getElementById = (id) => id === "invoice-form" ? form : null;
    app.window.DRAFT = { invoice: { bank_account: stored } };
    app.applyDraft();
    assert.equal(select.value, expected);
    assert.equal(select.label.textContent, expected);
  });
}

test("language restore preserves every line's discount reason, including blank reasons", () => {
  const app = loadApp();
  const fields = {
    description: ["", "", ""].map((value) => ({ value })),
    item_discount_reason: ["", "", ""].map((value) => ({ value })),
  };
  const form = {
    querySelectorAll(selector) {
      if (selector === "#items .item") return fields.description;
      return fields[selector.match(/name="([^"]+)"/)[1]] || [];
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
  };
  app.restoreForm(form, {
    description: ["Beratung", "Design", "Support"],
    item_discount_reason: ["Treuerabatt", "", "Aktionsrabatt"],
  });
  assert.deepEqual(fields.item_discount_reason.map((el) => el.value),
    ["Treuerabatt", "", "Aktionsrabatt"]);
});

test("language drafts are scoped to both the data directory and issuer", () => {
  const app = loadApp();
  app.window.ISSUER_SCOPE = "folder-a";
  app.window.ISSUER_ID = "default";
  const first = app.languageDraftKey();
  app.window.ISSUER_ID = "company";
  assert.notEqual(app.languageDraftKey(), first);
  app.window.ISSUER_ID = "default";
  app.window.ISSUER_SCOPE = "folder-b";
  assert.notEqual(app.languageDraftKey(), first);
});

test("restoring an invoice from another issuer does not change any field", () => {
  const app = loadApp();
  app.window.ISSUER_ID = "company";
  const form = {querySelectorAll() { throw new Error("must not restore another issuer's fields"); }};
  app.restoreForm(form, {issuer: ["default"], buyer_name: ["Private client"]});
});

test("invoice restore never replaces the form's issuer identity", () => {
  const app = loadApp();
  app.window.ISSUER_ID = "company";
  const buyer = {value: ""};
  const form = {
    querySelectorAll: () => [],
    querySelector(selector) {
      assert.notEqual(selector, '[name="issuer"]');
      return selector === '[name="buyer_name"]' ? buyer : null;
    },
  };
  app.restoreForm(form, {issuer: ["company"], buyer_name: ["Company client"]});
  assert.equal(buyer.value, "Company client");
});

test("cancelling a profile switch keeps its issuer and invoice fields", async () => {
  const app = loadApp();
  app.window.ISSUER_ID = "default";
  const select = {value: "company"};
  const buyer = {value: "Existing customer"};
  const invoice = {querySelectorAll: () => [buyer]};
  app.document.getElementById = (id) => id === "issuer-select" ? select : id === "invoice-form" ? invoice : null;
  app.confirmIssuerSwitch = async () => false;
  app.autosaveSeller = () => { throw new Error("cancelled switch must not save or navigate"); };
  await app.switchIssuer({id: "issuer-switch-form", submit() { throw new Error("must stay on current form"); }});
  assert.equal(select.value, "default");
  assert.equal(buyer.value, "Existing customer");
});

test("profile navigation waits for saved master data and stops on save failure", async () => {
  const app = loadApp();
  app.clearTimeout = () => {};
  app.window.ISSUER_ID = "default";
  const select = {value: "company"};
  app.document.getElementById = (id) => id === "issuer-select" ? select : null;
  let finishSave;
  app.autosaveSeller = () => new Promise((resolve) => { finishSave = resolve; });
  let navigated = false;
  const form = {id: "issuer-switch-form", submit() { navigated = true; }};
  const pending = app.switchIssuer(form);
  assert.equal(navigated, false);
  assert.equal(select.value, "default");
  finishSave(false);
  await pending;
  assert.equal(navigated, false);
  select.value = "company";
  const retry = app.switchIssuer(form);
  finishSave(true);
  await retry;
  assert.equal(navigated, true);
  assert.equal(select.value, "company");
});

test("adding the second issuer works while the profile selector is absent", async () => {
  const app = loadApp();
  app.clearTimeout = () => {};
  app.window.ISSUER_ID = "default";
  let finishSave;
  app.autosaveSeller = () => new Promise((resolve) => { finishSave = resolve; });
  let submitted = false;
  const pending = app.switchIssuer({id: "issuer-create-form", submit() { submitted = true; }});
  assert.equal(submitted, false);
  finishSave(true);
  await pending;
  assert.equal(submitted, true);
});

test("adding a profile also asks before discarding a filled invoice", async () => {
  const app = loadApp();
  const buyer = {value: "Existing customer"};
  app.document.getElementById = (id) => id === "invoice-form" ? {querySelectorAll: () => [buyer]} : null;
  app.confirmIssuerSwitch = async () => false;
  app.autosaveSeller = () => { throw new Error("cancelled creation must not save or navigate"); };
  await app.switchIssuer({id: "issuer-create-form", submit() { throw new Error("must not create a profile"); }});
  assert.equal(buyer.value, "Existing customer");
});
