const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadApp() {
  const elements = {};
  const document = {
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => elements[id] || null,
    addEventListener: () => {},
    body: { classList: { add() {}, remove() {} } },
  };
  const context = vm.createContext({
    document,
    window: { addEventListener() {}, MSG_LIVE_PREVIEW: "Live preview" },
    sessionStorage: { getItem: () => null },
    InvoiceCalc: require("../static/calc.js"),
    AbortController,
    FormData: class { append() {} },
    setTimeout: () => 1,
    clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8"), context);
  const frame = () => ({
    dataset: {}, style: {}, srcdoc: "Live invoice HTML",
    parentElement: { style: {}, parentElement: { clientWidth: 400 } },
    removeAttribute(name) { delete this[name]; },
  });
  elements["preview-frame"] = frame();
  elements["drawer-frame"] = frame();
  elements["preview-drawer"] = { hidden: true };
  elements["preview-label"] = { textContent: "Live preview" };
  elements["preview-pages-hint"] = { hidden: false, textContent: "Multiple pages" };
  return { app: context, elements };
}

function row(number) {
  return {
    dataset: { previewUrl: `/archive/preview/${number}.pdf`, viewUrl: `/view/${number}.pdf` },
    querySelector: () => ({ textContent: number }),
  };
}

test("archive selection and expanded preview use the selected original PDF", () => {
  const { app, elements } = loadApp();
  vm.runInContext("settingsOpen = true", app);
  const frame = elements["preview-frame"];
  app.previewRow(row("OLD-1"));
  assert.equal(frame.src, "/archive/preview/OLD-1.pdf#toolbar=0&navpanes=0&view=FitH");
  assert.equal(frame.srcdoc, undefined); // srcdoc would override the PDF navigation.
  assert.equal(elements["preview-pages-hint"].hidden, true);
  app.previewRow(row("OLD-2"));
  assert.match(frame.src, /OLD-2\.pdf#/);
  assert.equal(elements["preview-label"].textContent, "OLD-2");
  app.openPreviewDrawer();
  assert.equal(elements["drawer-frame"].src, "/archive/preview/OLD-2.pdf");
  assert.equal(elements["drawer-frame"].srcdoc, undefined);
});

test("returning to live preview restores HTML sizing even at the same width", () => {
  const { app, elements } = loadApp();
  const frame = elements["preview-frame"];
  app.scaleMiniPreview();
  const liveWidth = frame.style.width;
  const liveTransform = frame.style.transform;
  app.previewRow(row("OLD-1"));
  assert.equal(frame.style.width, "400px");
  assert.equal(frame.style.transform, "none");
  app.restoreLivePreview();
  assert.equal(frame.src, undefined);
  assert.equal(frame.srcdoc, "");
  assert.equal(frame.style.width, liveWidth);
  assert.equal(frame.style.transform, liveTransform);
  assert.equal(elements["preview-label"].textContent, "Live preview");
});

test("a pending live response cannot replace an archived PDF", async () => {
  const { app, elements } = loadApp();
  elements["invoice-form"] = {};
  app.window.PREVIEW_URL = "/preview-html";
  let resolve;
  app.fetch = () => new Promise((done) => { resolve = done; });
  app.updatePreview(true);
  vm.runInContext("settingsOpen = true", app);
  app.previewRow(row("OLD-1"));
  resolve({ text: () => Promise.resolve("Stale live HTML") });
  await new Promise((done) => setImmediate(done));
  assert.equal(elements["preview-frame"].srcdoc, undefined);
  assert.match(elements["preview-frame"].src, /OLD-1\.pdf#/);
});
