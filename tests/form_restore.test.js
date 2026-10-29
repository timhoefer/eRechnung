// Load the real browser script with a minimal DOM; no copied application logic.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  const document = {
    listeners: {},
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document,
    window: {
      listeners: {},
      addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
    },
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

test("deleting an issuer drains pending saves and suppresses later autosaves", async () => {
  const app = loadApp();
  app.clearTimeout = () => {};
  app.FormData = class {};
  const button = {disabled: false};
  app.document.getElementById = (id) => id === "issuer-delete-confirm" ? button : null;
  let finishSave;
  app.delayedSave = new Promise((resolve) => { finishSave = resolve; });
  vm.runInContext("pendingSellerSave = delayedSave", app);
  let requests = 0;
  app.fetch = async () => {
    requests++;
    return {ok: true, json: async () => ({ok: true, next_url: "/?issuer=other"})};
  };
  let destination;
  app.window.location = {assign(url) { destination = url; }};
  const deletion = app.deleteIssuer({action: "/issuers/delete"});
  assert.equal(requests, 0);
  assert.equal(button.disabled, true);
  assert.equal(await app.autosaveSeller(), false);
  finishSave(true);
  assert.equal(await deletion, true);
  assert.equal(requests, 1);
  assert.equal(destination, "/?issuer=other");
  assert.equal(await app.autosaveSeller(), false);
});

test("refused deletion keeps the page and resumes autosaving", async () => {
  const app = loadApp();
  app.clearTimeout = () => {};
  app.FormData = class {};
  const button = {disabled: false};
  let closed = false;
  const dialog = {close() { closed = true; }};
  app.document.getElementById = (id) => id === "issuer-delete-confirm" ? button : dialog;
  app.fetch = async () => ({ok: false, json: async () => ({ok: false, message: "Could not save"})});
  app.window.location = {assign() { throw new Error("must not leave the current invoice"); }};
  let message, resumed = false;
  app.flashError = (text) => { message = text; };
  app.scheduleSellerSave = () => { resumed = true; };
  assert.equal(await app.deleteIssuer({action: "/issuers/delete"}), false);
  assert.equal(message, "Could not save");
  assert.equal(button.disabled, false);
  assert.equal(closed, true);
  assert.equal(resumed, true);
});

test("setting the default keeps the current invoice form and reports persistence", async () => {
  const app = loadApp();
  app.window.ISSUER_ID = "company";
  const submitted = {};
  app.FormData = class { append(key, value) { submitted[key] = value; } };
  const label = {textContent: "Set as default"};
  const check = {hidden: true, removeAttribute() { this.hidden = false; }};
  const button = {disabled: false, querySelector: (selector) => selector === ".issuer-default-label" ? label : check,
    dataset: {url: "/issuers/default?issuer=company", savedLabel: "Default issuer"}};
  let finish;
  app.fetch = (url) => {
    assert.equal(url, button.dataset.url);
    return new Promise((resolve) => { finish = resolve; });
  };
  app.window.location = {assign() { throw new Error("must not navigate or reset the invoice"); }};
  const saving = app.setDefaultIssuer(button);
  assert.equal(button.disabled, true);
  assert.deepEqual(submitted, {issuer: "company"});
  finish({ok: true, json: async () => ({ok: true})});
  assert.equal(await saving, true);
  assert.equal(label.textContent, "Default issuer");
  assert.equal(button.disabled, true);
});

test("failed default save restores the action without showing success", async () => {
  const app = loadApp();
  app.FormData = class { append() {} };
  app.fetch = async () => ({ok: false, json: async () => ({ok: false})});
  let error = false;
  app.flashError = () => { error = true; };
  const button = {disabled: false, textContent: "Set as default", dataset: {url: "/issuers/default", savedLabel: "Default issuer"}};
  assert.equal(await app.setDefaultIssuer(button), false);
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Set as default");
  assert.equal(error, true);
});

test("rapid archive switches ignore an older response and retain the chosen archive on reload", async () => {
  const app = loadApp();
  const pane = {innerHTML: ""};
  app.document.getElementById = (id) => id === "settings-pane" ? pane : null;
  const requests = [];
  app.fetch = (url) => new Promise((resolve) => { requests.push({url, resolve}); });
  const first = app.loadSettingsPanel("/settings/panel?issuer=old");
  const second = app.loadSettingsPanel("/settings/panel?issuer=chosen");
  requests[1].resolve({ok: true, text: async () => "Chosen archive"});
  await second;
  requests[0].resolve({ok: true, text: async () => "Stale archive"});
  await first;
  assert.equal(pane.innerHTML, "Chosen archive");
  const reload = app.loadSettingsPanel();
  assert.equal(requests[2].url, "/settings/panel?issuer=chosen");
  requests[2].resolve({ok: true, text: async () => "Chosen reloaded"});
  await reload;
  assert.equal(pane.innerHTML, "Chosen reloaded");
});

function settingsView() {
  const app = loadApp();
  const pane = {innerHTML: "Current archive", hidden: true, focus() {}};
  const content = {hidden: false};
  const button = {dataset: {open: "Open", close: "Close"}, classList: {add() {}, remove() {}}, setAttribute() {}, focus() {}};
  const elements = {"settings-pane": pane, "form-content": content, "settings-toggle": button};
  app.document.getElementById = (id) => elements[id] || null;
  app.window.SETTINGS_PANEL_URL = "/settings/panel?issuer=current";
  app.window.scrollTo = () => {};
  app.checkMiniPages = app.restoreLivePreview = app.flashError = () => {};
  return {app, pane, content, button};
}

test("closing settings during loading keeps the invoice visible", async () => {
  const {app, pane, content} = settingsView();
  let finish;
  app.fetch = () => new Promise((resolve) => { finish = resolve; });
  const opening = app.openSettings();
  app.closeSettings();
  finish({ok: true, text: async () => "Late archive"});
  await opening;
  await new Promise(setImmediate);
  assert.equal(content.hidden, false);
  assert.equal(pane.hidden, true);
  assert.equal(pane.innerHTML, "Current archive");
});

test("a failed settings load restores the invoice and open button", async () => {
  const {app, pane, content, button} = settingsView();
  app.fetch = async () => ({ok: false});
  await app.openSettings();
  assert.equal(content.hidden, false);
  assert.equal(pane.hidden, true);
  assert.equal(button.textContent, "Open");
});

test("an old load failure cannot close settings after reopening", async () => {
  const {app, pane, content} = settingsView();
  const requests = [];
  app.fetch = () => new Promise((resolve) => { requests.push(resolve); });
  const first = app.openSettings();
  app.closeSettings();
  const second = app.openSettings();
  requests[0]({ok: false});
  await first;
  requests[1]({ok: true, text: async () => "Latest archive"});
  await second;
  assert.equal(content.hidden, true);
  assert.equal(pane.hidden, false);
  assert.equal(pane.innerHTML, "Latest archive");
});

test("archive selection stays with visible invoices while loading and after a failure", async () => {
  const {app, pane} = settingsView();
  app.URL = URL;
  app.URLSearchParams = URLSearchParams;
  app.window.location = {href: "http://localhost/"};
  const select = {value: "other", options: [{value: "current", defaultSelected: true}, {value: "other"}]};
  const form = {action: "/settings/panel", querySelector: () => select};
  app.FormData = class { constructor() { return new URLSearchParams({issuer: select.value}); } };
  let finish;
  app.fetch = (url) => {
    assert.equal(new URL(url).searchParams.get("issuer"), "other");
    return new Promise((resolve) => { finish = resolve; });
  };
  const switching = app.switchArchive(form);
  assert.equal(select.value, "current");
  finish({ok: false});
  await switching;
  assert.equal(select.value, "current");
  assert.equal(pane.innerHTML, "Current archive");
});

test("data folder conflicts are shown without reloading the archive or changing draft scope", async () => {
  const {app, pane} = settingsView();
  app.window.ISSUER_SCOPE = "old";
  app.FormData = class {};
  let message;
  app.flashError = (text) => { message = text; };
  app.fetch = async (url, options) => {
    assert.equal(url, "/data-dir?issuer=current");
    assert.equal(options.headers["X-Requested-With"], "fetch");
    return {ok: true, json: async () => ({ok: false, message: "Conflicting archive"})};
  };
  await app.saveDataDirectory({action: "/data-dir?issuer=current"});
  assert.equal(message, "Conflicting archive");
  assert.equal(pane.innerHTML, "Current archive");
  assert.equal(app.window.ISSUER_SCOPE, "old");
});

test("moving data updates language draft storage without resetting the invoice", async () => {
  const {app, content} = settingsView();
  app.window.ISSUER_SCOPE = "old";
  app.window.ISSUER_ID = "company";
  const oldKey = app.languageDraftKey();
  app.FormData = class {};
  app.flashOk = () => {};
  app.fetch = async () => ({ok: true, json: async () => ({ok: true, issuer_scope: "new"})});
  app.loadSettingsPanel = async () => true;
  await app.saveDataDirectory({action: "/data-dir?issuer=company"});
  assert.equal(app.window.ISSUER_SCOPE, "new");
  assert.notEqual(app.languageDraftKey(), oldKey);
  assert.equal(app.window.ISSUER_ID, "company");
  assert.equal(content.hidden, false);
});

function masterForm() {
  const app = loadApp();
  const revision = {value: "initial"};
  const fields = {name: "First edit"};
  const notice = {hidden: true, scrollIntoView() {}};
  const details = {open: false};
  const form = {querySelector: () => revision};
  const elements = {"settings-form": form, "master-conflict": notice, "master-data": details};
  app.document.getElementById = (id) => elements[id] || null;
  app.window.SELLER_AUTOSAVE_URL = "/settings/autosave?issuer=default";
  app.FormData = class extends Map { constructor() { super([["name", fields.name], ["seller_revision", revision.value]]); } };
  app.updatePreview = app.flashError = () => {};
  return {app, revision, fields, notice, details};
}

test("queued master edits use the previous save's revision without losing the newer edit", async () => {
  const {app, revision, fields} = masterForm();
  const requests = [];
  app.fetch = (url, options) => new Promise((resolve) => requests.push({body: options.body, resolve}));
  const first = app.autosaveSeller();
  fields.name = "Second edit";
  const second = app.autosaveSeller();
  await Promise.resolve();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.get("seller_revision"), "initial");
  requests[0].resolve({ok: true, headers: {get: () => "after-first"}});
  assert.equal(await first, true);
  await Promise.resolve();
  assert.equal(requests[1].body.get("seller_revision"), "after-first");
  assert.equal(requests[1].body.get("name"), "Second edit");
  requests[1].resolve({ok: true, headers: {get: () => "after-second"}});
  assert.equal(await second, true);
  assert.equal(revision.value, "after-second");
});

test("a master-data conflict preserves local fields and stops queued saves and profile navigation", async () => {
  const {app, revision, fields, notice, details} = masterForm();
  app.clearTimeout = () => {};
  let requests = 0;
  app.fetch = async () => {
    requests++;
    return {status: 409, ok: false, json: async () => ({message: "Changed elsewhere"})};
  };
  const first = app.autosaveSeller();
  const queued = app.autosaveSeller();
  assert.equal(await first, false);
  assert.equal(await queued, false);
  assert.equal(requests, 1);
  assert.equal(notice.hidden, false);
  assert.equal(details.open, true);
  assert.equal(fields.name, "First edit");
  assert.equal(revision.value, "initial");
  await app.switchIssuer({id: "issuer-create-form", submit() { throw new Error("must not navigate"); }});
  assert.equal(requests, 1);
});

test("loading current master data preserves the invoice draft before reloading", () => {
  const app = loadApp();
  app.window.ISSUER_ID = "company";
  app.FormData = class extends Map { constructor() { super([["buyer_name", "Client"], ["description", "Work"]]); } };
  let saved;
  app.sessionStorage.setItem = (key, value) => { saved = JSON.parse(value); };
  app.window.location = {reload() { assert.deepEqual(saved, {buyer_name: ["Client"], description: ["Work"]}); }};
  app.reloadMasterData();
});

test("retired issuer details are never autosaved and restored drafts cannot replace their original reference", async () => {
  const {app} = masterForm();
  app.window.ISSUER_RETIRED = true;
  app.fetch = () => { throw new Error("retired master data must stay unchanged"); };
  assert.equal(await app.autosaveSeller(), true);
  const fields = {doc_type: {value: "381"}, ref_number: {value: "2026-011"}, ref_date: {value: "2026-10-01"}, correction_source: {value: "original.pdf"}};
  const form = {querySelectorAll: () => [], querySelector: (selector) => fields[selector.match(/name="([^"]+)"/)[1]]};
  app.restoreForm(form, {doc_type: ["380"], ref_number: ["Wrong"], ref_date: ["2000-01-01"], correction_source: ["other.pdf"]});
  assert.equal(fields.doc_type.value, "381");
  assert.equal(fields.ref_number.value, "2026-011");
  assert.equal(fields.ref_date.value, "2026-10-01");
  assert.equal(fields.correction_source.value, "original.pdf");
});

for (const retired of [false, true]) {
  test(`archived invoice restores discounts and ${retired ? "original" : "fresh"} service dates`, () => {
    const app = loadApp();
    app.window.ISSUER_RETIRED = retired;
    app.syncUnitDisplay = () => {};
    const items = [
      {description: "Design", quantity: "2", unit: "DAY", unit_price: "100", item_discount: "10", item_discount_type: "pct", item_discount_reason: "Discount", item_start: "2026-09-01", item_end: "2026-09-02"},
      {description: "Review", quantity: "0", unit: "HUR", unit_price: "25", item_discount: "0", item_discount_type: "abs", item_discount_reason: "", item_start: null, item_end: null},
    ];
    const fields = {};
    Object.keys(items[0]).forEach((name) => { fields[name] = items.map(() => ({value: ""})); });
    for (const [name, value] of Object.entries({number: "2026-020", issue_date: "2026-10-29", due_date: "2026-11-12", doc_type: retired ? "381" : "380", ref_number: "2026-019", service_start: "", service_end: "", discount: "0", prepaid: "0"})) {
      fields[name] = [{value}];
    }
    const rows = items.map((_, i) => ({querySelector(selector) {
      const name = {".qty": "quantity", ".price": "unit_price", ".unit": "unit"}[selector] || selector.match(/name="([^"]+)"/)[1];
      return fields[name][i];
    }}));
    const form = {
      querySelectorAll(selector) { return selector === "#items .item" ? rows : fields[selector.match(/name="([^"]+)"/)[1]] || []; },
      querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    };
    app.document.getElementById = (id) => id === "invoice-form" ? form : null;
    app.document.querySelector = (selector) => selector === "#items" ? {querySelectorAll: () => rows} : null;
    app.window.DRAFT = {items, invoice: {number: "2026-019", issue_date: "2026-09-03", due_date: "2026-09-17", doc_type: "380", service_start: "2026-09-01", service_end: "2026-09-02"}};
    app.applyDraft();
    for (const [name, value] of Object.entries(items[0])) {
      assert.equal(fields[name][0].value, !retired && ["item_start", "item_end"].includes(name) ? "" : value, name);
    }
    assert.equal(fields.quantity[1].value, "0");
    assert.equal(fields.item_discount_reason[1].value, "");
    assert.equal(fields.service_start[0].value, retired ? "2026-09-01" : "");
    assert.equal(fields.service_end[0].value, retired ? "2026-09-02" : "");
    assert.equal(fields.number[0].value, "2026-020");
    assert.equal(fields.issue_date[0].value, "2026-10-29");
    assert.equal(fields.due_date[0].value, "2026-11-12");
    assert.equal(fields.doc_type[0].value, retired ? "381" : "380");
    assert.equal(fields.ref_number[0].value, "2026-019");
    const totals = app.InvoiceCalc.totals({items: items.map((_, i) => ({qty: fields.quantity[i].value, price: fields.unit_price[i].value, discVal: fields.item_discount[i].value, discType: fields.item_discount_type[i].value})), rate: 19});
    assert.equal(totals.grand, 214.2);
  });
}

test("invoice export waits for master data, blocks on failure and prevents double submission", async () => {
  const app = loadApp();
  app.clearTimeout = () => {};
  let finishSave, saves = 0, exports = 0;
  app.autosaveSeller = () => { saves++; return new Promise((resolve) => { finishSave = resolve; }); };
  const form = {id: "invoice-form", querySelector: () => null, reportValidity: () => true, submit() { exports++; }};
  const button = {disabled: false, hasAttribute: () => false};
  app.document.getElementById = (id) => id === "generate-btn" ? button : null;
  let prevented = 0;
  const event = {target: form, submitter: button, preventDefault() { prevented++; }};
  const submit = () => Promise.all(app.document.listeners.submit.map((handler) => handler(event)));
  const first = submit();
  assert.equal(prevented, 1);
  assert.equal(exports, 0);
  assert.equal(button.disabled, true);
  await submit();
  assert.equal(saves, 1);
  finishSave(false);
  await first;
  assert.equal(exports, 0);
  assert.equal(button.disabled, false);
  const retry = submit();
  finishSave(true);
  await retry;
  assert.equal(exports, 1);
  await submit();
  assert.equal(exports, 1);
  // Browsers may restore this page without executing the script again.
  app.window.listeners.pageshow.forEach((handler) => handler({persisted: true}));
  assert.equal(button.disabled, false);
  const afterBack = submit();
  finishSave(true);
  await afterBack;
  assert.equal(exports, 2);
});
