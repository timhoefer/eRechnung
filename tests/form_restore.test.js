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
