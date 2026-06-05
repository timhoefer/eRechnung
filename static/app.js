function fmt(n) {
  const locale = window.UI_LANG === "en" ? "en-US" : "de-DE";
  return n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function num(v) {
  return parseFloat((v || "0").replace(",", ".")) || 0;
}

function recalc() {
  const rate = num(document.querySelector("#tax_treatment option:checked").dataset.rate);
  let net = 0;
  document.querySelectorAll("#items .item").forEach((row) => {
    const gross = num(row.querySelector(".qty").value) * num(row.querySelector(".price").value);
    const extra = row.nextElementSibling;
    let lineDisc = 0;
    if (extra) {
      const dInp = extra.querySelector(".disc-input");
      const dType = extra.querySelector(".disc-type");
      const dVal = dInp ? num(dInp.value) : 0;
      if (dVal > 0) {
        if (dType && dType.value === "abs") lineDisc = Math.min(dVal, gross);
        else lineDisc = (gross * Math.min(dVal, 100)) / 100;
      }
    }
    const lineNet = gross - lineDisc;
    row.querySelector(".line-sum").textContent = fmt(lineNet);
    net += lineNet;
  });
  const discEl = document.querySelector("#discount");
  let discount = discEl ? num(discEl.value) : 0;
  if (discount < 0) discount = 0;
  if (discount > net) discount = net;
  const basis = net - discount;
  const tax = (basis * rate) / 100;
  const subRow = document.querySelector("#t-sub-row");
  const discRow = document.querySelector("#t-disc-row");
  if (discount > 0) {
    if (subRow) subRow.hidden = false;
    if (discRow) discRow.hidden = false;
    const subEl = document.querySelector("#t-sub");
    const dEl = document.querySelector("#t-disc");
    if (subEl) subEl.textContent = fmt(net);
    if (dEl) dEl.textContent = "− " + fmt(discount);
  } else {
    if (subRow) subRow.hidden = true;
    if (discRow) discRow.hidden = true;
  }
  document.querySelector("#t-net").textContent = fmt(basis);
  document.querySelector("#t-tax").textContent = fmt(tax);
  document.querySelector("#t-grand").textContent = fmt(basis + tax);
  const vatLabel = window.VAT_LABEL || "USt";
  document.querySelector("#t-tax-label").textContent = rate > 0 ? vatLabel + " " + rate + " %" : vatLabel;
}

function showNote() {
  const sel = document.querySelector("#tax_treatment");
  const opt = sel.querySelector("option:checked");
  document.querySelector("#tax-note").textContent = opt.dataset.note || "";
  // Reminder zum Nachweis der Unternehmereigenschaft nur bei Drittland-Fällen.
  const proof = document.querySelector("#proof-hint");
  if (proof) proof.hidden = !(sel.value === "non_eu" || sel.value === "non_eu_g");
}

// EU-Mitgliedstaaten (ISO-3166-1 alpha-2) für die automatische Steuer-Vorauswahl.
const EU_COUNTRIES = new Set([
  "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "GR", "HU",
  "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI",
  "ES", "SE",
]);
// Empfängerland -> passende steuerliche Behandlung (Default, vom Nutzer überschreibbar).
function deriveTreatment(country) {
  country = (country || "DE").toUpperCase();
  if (country === "DE") return "de_19";
  if (EU_COUNTRIES.has(country)) return "eu_reverse";
  return "non_eu";
}
// Steuerliche Behandlung passend zum Kundenland vorauswählen.
// Kleinunternehmer bleibt unangetastet (hängt am Verkäuferstatus, nicht am Land).
function autoSelectTreatment() {
  const sel = document.querySelector("#tax_treatment");
  if (!sel || sel.value === "kleinunternehmer") return;
  const cc = document.querySelector("[name='buyer_country']");
  const want = deriveTreatment(cc ? cc.value : "DE");
  if (sel.value === want) return;
  if (![...sel.options].some((o) => o.value === want)) return;
  sel.value = want;
  showNote();
}


function currentProfile() {
  const el = document.getElementById("profile");
  return el ? el.value : "en16931";
}
// Format-Tabs, Hinweis, Pflichtfelder und Labels an das gewählte Format anpassen.
function applyProfile() {
  const xr = currentProfile() === "xrechnung";
  // Titel-Schalter beschriften (ggf. nach Wiederherstellung).
  const name = document.querySelector("#format-trigger .fmt-name");
  if (name) name.textContent = xr ? "XRechnung" : "ZUGFeRD";
  const hint = document.getElementById("profile-hint");
  if (hint) hint.hidden = !xr;
  // Pflichtfelder (native required) + Markierung
  document.querySelectorAll("[data-xr-required]").forEach((inp) => {
    inp.required = xr;
    const m = inp.closest("label") && inp.closest("label").querySelector(".req-mark");
    if (m) m.hidden = !xr;
  });
  // Nur Markierung (kein native required – z. B. Stammdaten)
  document.querySelectorAll("[data-xr-mark]").forEach((inp) => {
    const m = inp.closest("label") && inp.closest("label").querySelector(".req-mark");
    if (m) m.hidden = !xr;
  });
  // Label-Texte umschalten (z. B. Kundenreferenz <-> Leitweg-ID)
  document.querySelectorAll(".lbl[data-xr]").forEach((s) => {
    s.textContent = xr ? s.dataset.xr : s.dataset.zug;
  });
  // Erzeugen-Button beschriften
  const gen = document.getElementById("generate-btn");
  if (gen && gen.dataset.xr) gen.textContent = xr ? gen.dataset.xr : gen.dataset.zug;
}

// Format-Dropdown im Titel (gestylt wie die Combobox).
function positionFormatMenu() {
  const t = document.getElementById("format-trigger");
  const m = document.getElementById("format-menu");
  if (!t || !m) return;
  const r = t.getBoundingClientRect();
  m.style.left = r.left + "px";
  m.style.top = r.bottom + 6 + "px";
  m.style.width = "240px";
}
function openFormatMenu() {
  const m = document.getElementById("format-menu");
  const t = document.getElementById("format-trigger");
  if (!m || !t) return;
  positionFormatMenu();
  m.querySelectorAll(".combo-opt").forEach((o) =>
    o.classList.toggle("active", o.dataset.profile === currentProfile())
  );
  m.hidden = false;
  t.setAttribute("aria-expanded", "true");
}
function closeFormatMenu() {
  const m = document.getElementById("format-menu");
  const t = document.getElementById("format-trigger");
  if (m) m.hidden = true;
  if (t) t.setAttribute("aria-expanded", "false");
}
function chooseFormat(profile) {
  const el = document.getElementById("profile");
  if (el) el.value = profile;
  closeFormatMenu();
  applyProfile();
  schedulePreview();
}

// Hinweis, wenn USt-IdNr. UND Steuernummer gesetzt sind (Steuernummer dann optional).
function updateTaxnrHint() {
  const form = document.getElementById("settings-form");
  const hint = document.getElementById("taxnr-hint");
  if (!form || !hint) return;
  const vat = form.querySelector("[name='vat_id']");
  const tax = form.querySelector("[name='tax_number']");
  hint.hidden = !(vat && tax && vat.value.trim() && tax.value.trim());
}

// Pflichtangaben der Stammdaten prüfen: grüner Haken vs. Warnung + Feldmarkierung.
// USt-IdNr. ist Pflicht (EN16931 BR-CO-26); Steuernummer ist optional.
const MASTER_REQUIRED = ["name", "address_line", "postcode", "city", "vat_id", "iban"];
function markField(el, bad) {
  const label = el && el.closest("label");
  if (label) label.classList.toggle("field-error", !!bad);
}
function validateMasterData() {
  const form = document.getElementById("settings-form");
  if (!form) return;
  let complete = true;
  MASTER_REQUIRED.forEach((n) => {
    const el = form.querySelector(`[name="${n}"]`);
    const ok = el && el.value.trim();
    markField(el, !ok);
    if (!ok) complete = false;
  });
  const check = document.querySelector(".ok-check");
  const warn = document.querySelector(".warn-badge");
  if (check) check.hidden = !complete;
  if (warn) warn.hidden = complete;
}

// Leistungszeitraum: weiche Pflicht. Warnung zeigen, wenn weder ein Zeitraum
// (gesamt oder je Position) noch "entspricht Rechnungsdatum" gesetzt ist.
function updatePeriodWarning() {
  const warn = document.getElementById("period-warning");
  if (!warn) return;
  const s = document.querySelector('#invoice-form [name="service_start"]');
  const e = document.querySelector('#invoice-form [name="service_end"]');
  const eq = document.getElementById("service-eq-issue");
  const hasOverall = !!(s && e && s.value && e.value && !s.disabled);
  let hasLine = false;
  document.querySelectorAll("#items .period-label").forEach((pl) => {
    if (pl.hidden) return;
    const st = pl.querySelector('[name="item_start"]');
    const en = pl.querySelector('[name="item_end"]');
    if (st && en && st.value && en.value) hasLine = true;
  });
  warn.hidden = hasOverall || hasLine || (eq && eq.checked);
}

// "entspricht Rechnungsdatum": Zeitraumfelder sperren (Werte bleiben erhalten,
// werden aber nicht gesendet -> BT-72 = Rechnungsdatum, PDF zeigt Hinweis).
function syncServicePeriod() {
  const eq = document.getElementById("service-eq-issue");
  const s = document.querySelector('#invoice-form [name="service_start"]');
  const en = document.querySelector('#invoice-form [name="service_end"]');
  if (eq && s && en) {
    s.disabled = eq.checked;
    en.disabled = eq.checked;
  }
  updatePeriodWarning();
}

// Bezugsfelder (Storno/Korrektur) nur bei Belegart != 380 (normale Rechnung) zeigen.
function toggleRefFields() {
  const sel = document.querySelector("#doc_type");
  if (!sel) return;
  const show = sel.value !== "380";
  document.querySelectorAll(".ref-field").forEach((el) => {
    el.hidden = !show;
  });
  const refNo = document.querySelector("[name='ref_number']");
  if (refNo) refNo.required = show;
}

// Bundesländer/Staaten je Land: [Code, Anzeigename]. Code wandert ins XML (BT-54).
const STATES = {
  US: [
    ["AL", "Alabama"], ["AK", "Alaska"], ["AZ", "Arizona"], ["AR", "Arkansas"],
    ["CA", "California"], ["CO", "Colorado"], ["CT", "Connecticut"], ["DE", "Delaware"],
    ["DC", "District of Columbia"], ["FL", "Florida"], ["GA", "Georgia"], ["HI", "Hawaii"],
    ["ID", "Idaho"], ["IL", "Illinois"], ["IN", "Indiana"], ["IA", "Iowa"], ["KS", "Kansas"],
    ["KY", "Kentucky"], ["LA", "Louisiana"], ["ME", "Maine"], ["MD", "Maryland"],
    ["MA", "Massachusetts"], ["MI", "Michigan"], ["MN", "Minnesota"], ["MS", "Mississippi"],
    ["MO", "Missouri"], ["MT", "Montana"], ["NE", "Nebraska"], ["NV", "Nevada"],
    ["NH", "New Hampshire"], ["NJ", "New Jersey"], ["NM", "New Mexico"], ["NY", "New York"],
    ["NC", "North Carolina"], ["ND", "North Dakota"], ["OH", "Ohio"], ["OK", "Oklahoma"],
    ["OR", "Oregon"], ["PA", "Pennsylvania"], ["RI", "Rhode Island"], ["SC", "South Carolina"],
    ["SD", "South Dakota"], ["TN", "Tennessee"], ["TX", "Texas"], ["UT", "Utah"],
    ["VT", "Vermont"], ["VA", "Virginia"], ["WA", "Washington"], ["WV", "West Virginia"],
    ["WI", "Wisconsin"], ["WY", "Wyoming"],
  ],
  CA: [
    ["AB", "Alberta"], ["BC", "British Columbia"], ["MB", "Manitoba"], ["NB", "New Brunswick"],
    ["NL", "Newfoundland and Labrador"], ["NS", "Nova Scotia"], ["NT", "Northwest Territories"],
    ["NU", "Nunavut"], ["ON", "Ontario"], ["PE", "Prince Edward Island"], ["QC", "Québec"],
    ["SK", "Saskatchewan"], ["YT", "Yukon"],
  ],
  AU: [
    ["ACT", "Australian Capital Territory"], ["NSW", "New South Wales"],
    ["NT", "Northern Territory"], ["QLD", "Queensland"], ["SA", "South Australia"],
    ["TAS", "Tasmania"], ["VIC", "Victoria"], ["WA", "Western Australia"],
  ],
};

// Staat-Feld nur bei relevanten Ländern zeigen und passende Auswahl befüllen.
function updateStateField(desired) {
  const country = document.querySelector("#buyer_country");
  const field = document.querySelector("#buyer-state-field");
  const sel = document.querySelector("#buyer_state");
  if (!country || !field || !sel) return;
  const list = STATES[country.value];
  if (!list) {
    field.hidden = true;
    return;
  }
  const keep = desired != null ? desired : sel.value;
  sel.innerHTML =
    '<option value=""></option>' +
    list.map(([code, name]) => `<option value="${code}">${name}</option>`).join("");
  sel.value = keep || "";
  field.hidden = false;
}

function addRow() {
  const container = document.querySelector("#items");
  const firstPos = container.querySelector(".position");
  const clonePos = firstPos.cloneNode(true);
  // Alle Felder der geklonten Position zurücksetzen.
  clonePos.querySelectorAll("input").forEach((i) => {
    if (i.classList.contains("qty")) i.value = "1";
    else if (i.classList.contains("price")) i.value = "0";
    else if (i.classList.contains("disc-input")) i.value = "0";
    else i.value = "";
  });
  const unit = clonePos.querySelector(".unit");
  if (unit) {
    unit.selectedIndex = 0;
    syncUnitDisplay(unit);
  }
  const dType = clonePos.querySelector(".disc-type");
  if (dType) dType.value = "pct";
  clonePos.querySelector(".line-sum").textContent = fmt(0);
  container.appendChild(clonePos);
  const clone = clonePos.querySelector(".item");
  showItemPeriod(clone, false); // neue Position startet ohne Leistungszeitraum
  showItemDiscount(clone, false); // … und ohne Rabatt
  updateDiscTypeLabels();
}

// Leistungszeitraum einer Position ein-/ausblenden; beim Entfernen Datumsfelder leeren.
function showItemPeriod(row, show) {
  const extra = row.nextElementSibling; // .item-extra (immer vorhanden)
  if (!extra) return;
  const addBtn = extra.querySelector(".add-period");
  const periodLabel = extra.querySelector(".period-label");
  if (!addBtn || !periodLabel) return;
  addBtn.hidden = show;
  periodLabel.hidden = !show;
  extra.classList.toggle("show-period", show); // steuert den Abstand zur Trennlinie
  if (!show) periodLabel.querySelectorAll("input").forEach((i) => (i.value = ""));
}

// Beim Laden/Wiederherstellen: Zeitraum nur dort zeigen, wo bereits Daten stehen.
function syncItemPeriods() {
  document.querySelectorAll("#items .item").forEach((row) => {
    const extra = row.nextElementSibling;
    const pl = extra ? extra.querySelector(".period-label") : null;
    const has = pl ? [...pl.querySelectorAll("input")].some((i) => i.value) : false;
    showItemPeriod(row, has);
  });
}

// Positions-Rabatt einer Zeile ein-/ausblenden; beim Entfernen Wert zurücksetzen.
function showItemDiscount(row, show) {
  const extra = row.nextElementSibling;
  if (!extra) return;
  const addBtn = extra.querySelector(".add-discount");
  const label = extra.querySelector(".discount-label");
  if (!addBtn || !label) return;
  addBtn.hidden = show;
  label.hidden = !show;
  if (!show) {
    const inp = label.querySelector(".disc-input");
    if (inp) inp.value = "0";
    const sel = label.querySelector(".disc-type");
    if (sel) { sel.selectedIndex = 0; syncUnitDisplay(sel); }
  }
}

// Beim Laden/Wiederherstellen: Rabatt nur dort zeigen, wo ein Wert > 0 steht.
function syncItemDiscounts() {
  document.querySelectorAll("#items .item").forEach((row) => {
    const extra = row.nextElementSibling;
    const inp = extra ? extra.querySelector(".disc-input") : null;
    showItemDiscount(row, !!(inp && num(inp.value) > 0));
  });
}

// Beschriftung der „Betrag“-Option am Währungssymbol ausrichten.
function currencySymbol(code) {
  return { EUR: "€", USD: "$", GBP: "£", CHF: "CHF", JPY: "¥" }[code] || code || "€";
}
function updateDiscTypeLabels() {
  const curEl = document.querySelector("[name='currency']");
  const sym = currencySymbol((curEl ? curEl.value : "EUR").trim().toUpperCase());
  // €-Option am Währungssymbol ausrichten und Button-Label neu setzen.
  document.querySelectorAll('.disc-type option[value="abs"]').forEach((o) => {
    o.text = sym;
  });
  document.querySelectorAll(".disc-type").forEach(syncUnitDisplay);
}

// Formularzustand sichern/wiederherstellen (z. B. beim Sprachwechsel).
function snapshotForm(form) {
  const data = {};
  new FormData(form).forEach((v, k) => {
    (data[k] = data[k] || []).push(v);
  });
  return data;
}
function restoreForm(form, data) {
  if (!form || !data) return;
  const repeating = ["description", "quantity", "unit", "unit_price", "item_start", "item_end", "item_discount", "item_discount_type"];
  const itemCount = (data.description || []).length;
  let rows = form.querySelectorAll("#items .item").length;
  while (rows < itemCount) {
    addRow();
    rows++;
  }
  repeating.forEach((name) => {
    const els = form.querySelectorAll(`[name="${name}"]`);
    (data[name] || []).forEach((val, i) => {
      if (els[i]) els[i].value = val;
    });
  });
  Object.keys(data).forEach((name) => {
    if (repeating.includes(name)) return;
    const el = form.querySelector(`[name="${name}"]`);
    if (el) el.value = data[name][0];
  });
}

let lastSavedCustomerName = "";

function fillCustomer(idx) {
  const c = (window.CUSTOMERS || [])[idx];
  if (!c) return;
  lastSavedCustomerName = c.name || "";
  const map = {
    buyer_name: c.name,
    buyer_contact: c.contact,
    buyer_address_line: c.address_line,
    buyer_postcode: c.postcode,
    buyer_city: c.city,
    buyer_state: c.state,
    buyer_country: c.country,
    buyer_vat_id: c.vat_id,
    buyer_email: c.email,
    buyer_reference: c.reference,
  };
  Object.entries(map).forEach(([n, v]) => {
    const el = document.querySelector(`[name="${n}"]`);
    if (el) el.value = v || "";
  });
  const cc = document.querySelector('[name="buyer_country"]');
  if (cc && !cc.value) cc.value = "DE";
  updateStateField(c.state);
}

// Archivierte Rechnung als Vorlage laden: Inhalt übernehmen, Nummer/Datum bleiben frisch.
function applyDraft() {
  const d = window.DRAFT;
  if (!d) return;
  const form = document.getElementById("invoice-form");
  if (!form) return;
  const b = d.buyer || {};
  const buyerMap = {
    buyer_name: b.name, buyer_contact: b.contact, buyer_address_line: b.address_line,
    buyer_postcode: b.postcode, buyer_city: b.city, buyer_state: b.state,
    buyer_country: b.country, buyer_vat_id: b.vat_id, buyer_email: b.email,
    buyer_reference: b.reference,
  };
  Object.entries(buyerMap).forEach(([n, v]) => {
    const el = form.querySelector(`[name="${n}"]`);
    if (el) el.value = v || "";
  });
  const cc = form.querySelector('[name="buyer_country"]');
  if (cc && !cc.value) cc.value = "DE";
  updateStateField(b.state);
  lastSavedCustomerName = b.name || ""; // verhindert Kunden-Duplikat beim Autosave

  const inv = d.invoice || {};
  const set = (n, v) => {
    const el = form.querySelector(`[name="${n}"]`);
    if (el && v != null && v !== "") el.value = v;
  };
  set("currency", inv.currency);
  set("note", inv.note);
  set("language", inv.language);
  set("tax_treatment", inv.tax_treatment);
  set("profile", inv.profile);

  const items = d.items || [];
  if (items.length) {
    const tbody = document.querySelector("#items");
    while (tbody.querySelectorAll(".item").length < items.length) addRow();
    const rows = tbody.querySelectorAll(".item");
    items.forEach((it, i) => {
      const row = rows[i];
      row.querySelector('[name="description"]').value = it.description || "";
      row.querySelector(".qty").value = it.quantity || "1";
      const u = row.querySelector(".unit");
      if (u && it.unit) u.value = it.unit;
      syncUnitDisplay(u);
      row.querySelector(".price").value = it.unit_price || "0";
    });
  }
}

function currentCustomer() {
  const el = document.querySelector("[name='buyer_name']");
  const name = el && el.value.trim().toLowerCase();
  if (!name) return null;
  return (window.CUSTOMERS || []).find(
    (c) => (c.name || "").trim().toLowerCase() === name
  ) || null;
}

// Pool gespeicherter Positionen: bei gewähltem Kunden dessen Positionen,
// sonst die aller Kunden (nach Beschreibung dedupliziert).
function savedItemsPool() {
  const c = currentCustomer();
  const customers = window.CUSTOMERS || [];
  let src = [];
  if (c) src = c.items || [];
  else customers.forEach((x) => (x.items || []).forEach((it) => src.push(it)));
  const seen = new Set();
  const pool = [];
  src.forEach((it) => {
    const desc = (it.description || "").trim();
    if (!desc) return;
    const key = desc.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    pool.push(it);
  });
  return pool;
}

// ---- Eigene Positions-Combobox (gestyltes Dropdown statt <datalist>) -------
let comboInput = null; // aktuell aktives Beschreibungsfeld
let comboMenu = null; // gemeinsames Dropdown-Element
let comboIndex = -1; // hervorgehobene Option

function ensureComboMenu() {
  if (comboMenu) return comboMenu;
  comboMenu = document.createElement("div");
  comboMenu.className = "combo-menu";
  comboMenu.hidden = true;
  document.body.appendChild(comboMenu);
  return comboMenu;
}

function closeComboMenu() {
  if (comboMenu) comboMenu.hidden = true;
  if (comboInput) comboInput.setAttribute("aria-expanded", "false");
  comboInput = null;
  comboIndex = -1;
}
// Wird bei Kundenwechsel / nach dem Speichern aufgerufen.
function refreshSavedItems() {
  closeComboMenu();
}

function positionComboMenu(input) {
  const r = input.getBoundingClientRect();
  comboMenu.style.left = r.left + "px";
  comboMenu.style.top = r.bottom + 3 + "px";
  comboMenu.style.width = Math.max(r.width, 220) + "px";
}

function openComboMenu(input) {
  const menu = ensureComboMenu();
  comboInput = input;
  comboIndex = -1;
  const q = input.value.trim().toLowerCase();
  const pool = savedItemsPool().filter(
    (it) => !q || (it.description || "").toLowerCase().includes(q)
  );
  menu.innerHTML = "";
  menu._pool = pool;
  if (pool.length === 0) {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    return;
  }
  pool.forEach((it, i) => {
    const opt = document.createElement("div");
    opt.className = "combo-opt";
    opt.dataset.index = i;
    const d = document.createElement("span");
    d.className = "combo-opt-desc";
    d.textContent = it.description || "";
    opt.appendChild(d);
    if (it.unit_price) {
      const p = document.createElement("span");
      p.className = "combo-opt-price";
      p.textContent = it.unit_price;
      opt.appendChild(p);
    }
    opt.addEventListener("mousedown", (ev) => {
      ev.preventDefault(); // Fokus im Eingabefeld halten
      chooseComboItem(input, it);
    });
    menu.appendChild(opt);
  });
  positionComboMenu(input);
  menu.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function chooseComboItem(input, it) {
  const row = input.closest(".item");
  if (!row) return;
  input.value = it.description || "";
  if (it.quantity) row.querySelector(".qty").value = it.quantity;
  const u = row.querySelector(".unit");
  if (u && it.unit) u.value = it.unit;
  syncUnitDisplay(u);
  if (it.unit_price) row.querySelector(".price").value = it.unit_price;
  closeComboMenu();
  recalc();
  schedulePreview();
}

function highlightCombo(delta) {
  if (!comboMenu || comboMenu.hidden) return;
  const opts = comboMenu.querySelectorAll(".combo-opt");
  if (!opts.length) return;
  comboIndex = (comboIndex + delta + opts.length) % opts.length;
  opts.forEach((o, i) => o.classList.toggle("active", i === comboIndex));
  opts[comboIndex].scrollIntoView({ block: "nearest" });
}

// Bei manueller Eingabe: exakte Übereinstimmung übernimmt die Position.
function applySavedItemToRow(row) {
  if (!row) return;
  const descEl = row.querySelector('[name="description"]');
  const desc = descEl && descEl.value.trim();
  if (!desc) return;
  const it = savedItemsPool().find(
    (x) => (x.description || "").trim().toLowerCase() === desc.toLowerCase()
  );
  if (!it) return;
  if (it.quantity) row.querySelector(".qty").value = it.quantity;
  const u = row.querySelector(".unit");
  if (u && it.unit) u.value = it.unit;
  syncUnitDisplay(u);
  if (it.unit_price) row.querySelector(".price").value = it.unit_price;
  recalc();
}

// ---- Kunden-Combobox: Name/Firma schlägt gespeicherte Kunden vor ----------
let custMenu = null;
let custInput = null;
let custIndex = -1;
function ensureCustMenu() {
  if (custMenu) return custMenu;
  custMenu = document.createElement("div");
  custMenu.className = "combo-menu";
  custMenu.hidden = true;
  document.body.appendChild(custMenu);
  return custMenu;
}
function closeCustMenu() {
  if (custMenu) custMenu.hidden = true;
  if (custInput) custInput.setAttribute("aria-expanded", "false");
  custInput = null;
  custIndex = -1;
}
function positionCustMenu(input) {
  const r = input.getBoundingClientRect();
  custMenu.style.left = r.left + "px";
  custMenu.style.top = r.bottom + 3 + "px";
  custMenu.style.width = Math.max(r.width, 240) + "px";
}
function openCustMenu(input) {
  const menu = ensureCustMenu();
  custInput = input;
  custIndex = -1;
  const q = input.value.trim().toLowerCase();
  const pool = (window.CUSTOMERS || [])
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => !q || (c.name || "").toLowerCase().includes(q));
  menu.innerHTML = "";
  menu._pool = pool;
  if (pool.length === 0) {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    return;
  }
  pool.forEach(({ c, i }, idx) => {
    const opt = document.createElement("div");
    opt.className = "combo-opt";
    opt.dataset.index = idx;
    const d = document.createElement("span");
    d.className = "combo-opt-desc";
    d.textContent = c.name || "";
    opt.appendChild(d);
    const sub = [c.city, c.vat_id].filter(Boolean).join(" · ");
    if (sub) {
      const p = document.createElement("span");
      p.className = "combo-opt-price";
      p.textContent = sub;
      opt.appendChild(p);
    }
    opt.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      chooseCust(i);
    });
    menu.appendChild(opt);
  });
  positionCustMenu(input);
  menu.hidden = false;
  input.setAttribute("aria-expanded", "true");
}
function chooseCust(idx) {
  fillCustomer(idx);
  closeCustMenu();
  autoSelectTreatment();
  refreshSavedItems();
  recalc();
  schedulePreview();
}
function highlightCust(delta) {
  if (!custMenu || custMenu.hidden) return;
  const opts = custMenu.querySelectorAll(".combo-opt");
  if (!opts.length) return;
  custIndex = (custIndex + delta + opts.length) % opts.length;
  opts.forEach((o, i) => o.classList.toggle("active", i === custIndex));
  opts[custIndex].scrollIntoView({ block: "nearest" });
}

// ---- Eigenes Einheiten-Dropdown (gestylt wie die Beschreibungs-Combobox) ----
// Der native <select class="unit"> bleibt versteckt als Werteträger erhalten,
// damit XML-Erzeugung und Speichern unverändert über .value funktionieren.
let unitMenu = null;
let unitSelectEl = null; // aktuell geöffnetes <select>
let unitIndex = -1;

function ensureUnitMenu() {
  if (unitMenu) return unitMenu;
  unitMenu = document.createElement("div");
  unitMenu.className = "combo-menu";
  unitMenu.hidden = true;
  document.body.appendChild(unitMenu);
  return unitMenu;
}
function closeUnitMenu() {
  if (unitMenu) unitMenu.hidden = true;
  if (unitSelectEl) {
    const btn = unitSelectEl.parentElement.querySelector(".unitsel-btn");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }
  unitSelectEl = null;
  unitIndex = -1;
}
// Sichtbares Label aus der aktuellen Auswahl des versteckten <select> übernehmen.
function syncUnitDisplay(select) {
  if (!select) return;
  const opt = select.options[select.selectedIndex];
  const span = select.parentElement.querySelector(".unitsel-label");
  if (span) span.textContent = opt ? opt.text : "";
}
function syncAllUnitDisplays(scope) {
  (scope || document).querySelectorAll(".unitsel select.unit").forEach(syncUnitDisplay);
}
function positionUnitMenu(btn) {
  const r = btn.getBoundingClientRect();
  unitMenu.style.left = r.left + "px";
  unitMenu.style.top = r.bottom + 3 + "px";
  unitMenu.style.width = Math.max(r.width, 140) + "px";
}
function openUnitMenu(select) {
  const menu = ensureUnitMenu();
  unitSelectEl = select;
  unitIndex = select.selectedIndex;
  const btn = select.parentElement.querySelector(".unitsel-btn");
  menu.innerHTML = "";
  [...select.options].forEach((o, i) => {
    const opt = document.createElement("div");
    opt.className = "combo-opt";
    opt.dataset.index = i;
    const d = document.createElement("span");
    d.className = "combo-opt-desc";
    d.textContent = o.text;
    opt.appendChild(d);
    if (i === select.selectedIndex) opt.classList.add("active");
    opt.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      chooseUnit(select, i);
    });
    menu.appendChild(opt);
  });
  positionUnitMenu(btn);
  menu.hidden = false;
  if (btn) btn.setAttribute("aria-expanded", "true");
}
function chooseUnit(select, i) {
  select.selectedIndex = i;
  syncUnitDisplay(select);
  closeUnitMenu();
  select.dispatchEvent(new Event("change", { bubbles: true })); // löst Vorschau-Update aus
}
function highlightUnit(delta) {
  if (!unitMenu || unitMenu.hidden) return;
  const opts = unitMenu.querySelectorAll(".combo-opt");
  if (!opts.length) return;
  unitIndex = (unitIndex + delta + opts.length) % opts.length;
  opts.forEach((o, i) => o.classList.toggle("active", i === unitIndex));
  opts[unitIndex].scrollIntoView({ block: "nearest" });
}

function saveCustomerItems() {
  const form = document.getElementById("invoice-form");
  const status = document.querySelector("#items-status");
  const name = (form.querySelector('[name="buyer_name"]').value || "").trim();
  if (!name) {
    if (status) status.textContent = window.MSG_NEED_NAME_ITEMS || "";
    return;
  }
  const fd = new FormData();
  // Positionen zeilenweise (ausgerichtet, leere Beschreibungen filtert der Server).
  form.querySelectorAll("#items .item").forEach((row) => {
    fd.append("description", row.querySelector('[name="description"]').value);
    fd.append("quantity", row.querySelector(".qty").value);
    fd.append("unit", row.querySelector(".unit").value);
    fd.append("unit_price", row.querySelector(".price").value);
  });
  // Käuferdaten mitsenden, falls der Kunde neu angelegt werden muss.
  form.querySelectorAll('[name^="buyer_"]').forEach((el) => fd.append(el.name, el.value));
  fetch(window.CUSTOMER_ITEMS_SAVE_URL, { method: "POST", body: fd })
    .then((r) => r.json())
    .then((d) => {
      if (!d || !d.ok) return;
      const list = window.CUSTOMERS || (window.CUSTOMERS = []);
      const entry = list.find((c) => (c.name || "").toLowerCase() === d.name.toLowerCase());
      if (entry) entry.items = d.items;
      refreshSavedItems();
      if (status) status.textContent = (window.MSG_ITEMS_SAVED || "") + " (" + d.items.length + ")";
    })
    .catch(() => {});
}

let previewTimer;
const A4_W = 794; // 210 mm bei 96 dpi – logische Breite der Mini-Vorschau
const A4_H = 1123; // 297 mm bei 96 dpi – A4-Höhe (eine Seite)
function scaleMiniPreview() {
  const frame = document.getElementById("preview-frame");
  const inner = frame && frame.parentElement;
  const wrap = inner && inner.parentElement;
  if (!frame || !inner || !wrap) return;
  const wrapW = wrap.clientWidth;
  const s = wrapW / A4_W;
  frame.style.width = A4_W + "px";
  frame.style.height = A4_H + "px";
  frame.style.transform = "scale(" + s + ")";
  inner.style.height = A4_H * s + "px";
}
function updatePreview() {
  const form = document.getElementById("invoice-form");
  const frame = document.getElementById("preview-frame");
  if (!form || !frame || !window.PREVIEW_URL) return;
  const data = new FormData(form);
  data.append("_full", "mini");
  fetch(window.PREVIEW_URL, { method: "POST", body: data })
    .then((r) => r.text())
    .then((html) => {
      frame.srcdoc = html;
    })
    .catch(() => {});
  updateDrawerPreview();
}
function updateDrawerPreview() {
  const drawer = document.getElementById("preview-drawer");
  const frame = document.getElementById("drawer-frame");
  const form = document.getElementById("invoice-form");
  if (!drawer || drawer.hidden || !frame || !form || !window.PREVIEW_URL) return;
  const data = new FormData(form);
  data.append("_full", "1");
  fetch(window.PREVIEW_URL, { method: "POST", body: data })
    .then((r) => r.text())
    .then((html) => {
      frame.srcdoc = html;
    })
    .catch(() => {});
}
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(updatePreview, 350);
}

function openPreviewDrawer() {
  const drawer = document.getElementById("preview-drawer");
  if (!drawer) return;
  drawer.hidden = false;
  document.body.classList.add("drawer-open");
  updateDrawerPreview();
}
function closePreviewDrawer() {
  const drawer = document.getElementById("preview-drawer");
  if (!drawer) return;
  drawer.hidden = true;
  document.body.classList.remove("drawer-open");
}

let sellerSaveTimer;
function autosaveSeller() {
  const form = document.getElementById("settings-form");
  if (!form || !window.SELLER_AUTOSAVE_URL) return;
  // Nach dem Speichern Vorschau auffrischen (Stammdaten fließen ins PDF ein).
  fetch(window.SELLER_AUTOSAVE_URL, { method: "POST", body: new FormData(form) })
    .then(() => updatePreview())
    .catch(() => {});
}
function scheduleSellerSave() {
  clearTimeout(sellerSaveTimer);
  sellerSaveTimer = setTimeout(autosaveSeller, 700);
}

let customerSaveTimer;
function autosaveCustomer() {
  const form = document.getElementById("invoice-form");
  if (!form || !window.CUSTOMER_AUTOSAVE_URL) return;
  const nameEl = form.querySelector('[name="buyer_name"]');
  if (!nameEl || !nameEl.value.trim()) return;
  const fd = new FormData();
  form.querySelectorAll('[name^="buyer_"]').forEach((el) => fd.append(el.name, el.value));
  fd.append("prev_name", lastSavedCustomerName);
  fetch(window.CUSTOMER_AUTOSAVE_URL, { method: "POST", body: fd })
    .then((r) => r.json())
    .then((d) => {
      if (d && d.name) lastSavedCustomerName = d.name;
    })
    .catch(() => {});
}
function scheduleCustomerSave() {
  clearTimeout(customerSaveTimer);
  customerSaveTimer = setTimeout(autosaveCustomer, 700);
}

document.addEventListener("input", (e) => {
  if (e.target.closest("#settings-form")) {
    scheduleSellerSave();
    if (e.target.name === "vat_id" || e.target.name === "tax_number") updateTaxnrHint();
    validateMasterData();
    return;
  }
  recalc();
  schedulePreview();
  if (["service_start", "service_end", "item_start", "item_end"].includes(e.target.name)) updatePeriodWarning();
  if (e.target.name && e.target.name.startsWith("buyer_")) scheduleCustomerSave();
  if (e.target.matches('#items [name="description"]')) openComboMenu(e.target);
  if (e.target.classList.contains("cust-name")) openCustMenu(e.target);
});
document.addEventListener("change", (e) => {
  if (e.target.id === "service-eq-issue") {
    syncServicePeriod();
    schedulePreview();
  }
});
document.addEventListener("focusin", (e) => {
  if (e.target.matches('#items [name="description"]')) openComboMenu(e.target);
  if (e.target.classList.contains("cust-name")) openCustMenu(e.target);
});
document.addEventListener("keydown", (e) => {
  if (!e.target.matches('#items [name="description"]')) return;
  if (!comboMenu || comboMenu.hidden) {
    if (e.key === "ArrowDown") {
      openComboMenu(e.target);
      e.preventDefault();
    }
    return;
  }
  if (e.key === "ArrowDown") {
    highlightCombo(1);
    e.preventDefault();
  } else if (e.key === "ArrowUp") {
    highlightCombo(-1);
    e.preventDefault();
  } else if (e.key === "Enter") {
    if (comboIndex >= 0 && comboMenu._pool && comboMenu._pool[comboIndex]) {
      chooseComboItem(e.target, comboMenu._pool[comboIndex]);
      e.preventDefault();
    }
  } else if (e.key === "Escape") {
    closeComboMenu();
  }
});
// Tastaturbedienung der Kunden-Combobox.
document.addEventListener("keydown", (e) => {
  if (!e.target.classList || !e.target.classList.contains("cust-name")) return;
  if (!custMenu || custMenu.hidden) {
    if (e.key === "ArrowDown") {
      openCustMenu(e.target);
      e.preventDefault();
    }
    return;
  }
  if (e.key === "ArrowDown") {
    highlightCust(1);
    e.preventDefault();
  } else if (e.key === "ArrowUp") {
    highlightCust(-1);
    e.preventDefault();
  } else if (e.key === "Enter") {
    const pool = custMenu._pool;
    if (custIndex >= 0 && pool && pool[custIndex]) {
      chooseCust(pool[custIndex].i);
      e.preventDefault();
    }
  } else if (e.key === "Escape") {
    closeCustMenu();
  }
});
document.addEventListener("mousedown", (e) => {
  const inMenu = e.target.closest(".combo-menu");
  const combo = e.target.closest(".combo");
  if (!combo && !inMenu) closeComboMenu();
  if (!e.target.closest(".unitsel") && !inMenu) closeUnitMenu();
  const inCustCombo = combo && combo.querySelector(".cust-name");
  if (!inCustCombo && !inMenu) closeCustMenu();
  if (!e.target.closest("#format-trigger") && !e.target.closest("#format-menu")) closeFormatMenu();
});
// Tastaturbedienung des Einheiten-Dropdowns.
document.addEventListener("keydown", (e) => {
  if (!e.target.closest(".unitsel-btn")) return;
  const sel = e.target.closest(".unitsel").querySelector("select.unit");
  if (!sel) return;
  if (!unitMenu || unitMenu.hidden) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      openUnitMenu(sel);
      e.preventDefault();
    }
    return;
  }
  if (e.key === "ArrowDown") {
    highlightUnit(1);
    e.preventDefault();
  } else if (e.key === "ArrowUp") {
    highlightUnit(-1);
    e.preventDefault();
  } else if (e.key === "Enter" || e.key === " ") {
    if (unitIndex >= 0) chooseUnit(sel, unitIndex);
    e.preventDefault();
  } else if (e.key === "Escape") {
    closeUnitMenu();
  }
});
function repositionMenus() {
  if (comboInput && comboMenu && !comboMenu.hidden) positionComboMenu(comboInput);
  if (custInput && custMenu && !custMenu.hidden) positionCustMenu(custInput);
  const fm = document.getElementById("format-menu");
  if (fm && !fm.hidden) positionFormatMenu();
  if (unitSelectEl && unitMenu && !unitMenu.hidden) {
    const btn = unitSelectEl.parentElement.querySelector(".unitsel-btn");
    if (btn) positionUnitMenu(btn);
  }
}
window.addEventListener("scroll", repositionMenus, true);
window.addEventListener("resize", repositionMenus);
document.addEventListener("change", (e) => {
  if (e.target.id === "tax_treatment") showNote();
  if (e.target.id === "doc_type") toggleRefFields();
  if (e.target.classList.contains("disc-type")) recalc();
  if (e.target.name === "currency") updateDiscTypeLabels();
  if (e.target.id === "buyer_country") {
    updateStateField();
    autoSelectTreatment();
  }
  if (e.target.matches('#items [name="description"]')) {
    applySavedItemToRow(e.target.closest(".item"));
  }
  schedulePreview();
});
document.addEventListener("click", (e) => {
  const langLink = e.target.closest(".langswitch a");
  if (langLink) {
    const form = document.getElementById("invoice-form");
    if (form) sessionStorage.setItem("erechnung:lang", JSON.stringify(snapshotForm(form)));
    return; // Navigation zum Sprachwechsel zulassen
  }
  if (e.target.closest("#format-trigger")) {
    const m = document.getElementById("format-menu");
    if (m && m.hidden) openFormatMenu();
    else closeFormatMenu();
    return;
  }
  const fmtOpt = e.target.closest("#format-menu .combo-opt");
  if (fmtOpt) {
    chooseFormat(fmtOpt.dataset.profile);
    return;
  }
  if (e.target.id === "cust-delete-btn") {
    const nameEl = document.querySelector("[name='buyer_name']");
    const name = nameEl ? nameEl.value.trim() : "";
    if (!name) return;
    const m = document.getElementById("cust-delete-modal");
    const n = document.getElementById("cust-del-name");
    if (n) n.textContent = name;
    if (m) m.hidden = false;
    return;
  }
  if (e.target.id === "cust-delete-cancel" || e.target.id === "cust-delete-modal") {
    const m = document.getElementById("cust-delete-modal");
    if (m) m.hidden = true;
    return;
  }
  const unitTrigger = e.target.closest(".unitsel-btn, .unitsel .combo-caret");
  if (unitTrigger) {
    const sel = unitTrigger.closest(".unitsel").querySelector("select.unit");
    if (sel) {
      if (unitSelectEl === sel && unitMenu && !unitMenu.hidden) closeUnitMenu();
      else openUnitMenu(sel);
    }
    return;
  }
  const caret = e.target.closest(".combo-caret");
  if (caret) {
    const input = caret.parentElement.querySelector(".combo-input");
    if (input && input.classList.contains("cust-name")) {
      if (custInput === input && custMenu && !custMenu.hidden) closeCustMenu();
      else {
        input.focus();
        openCustMenu(input);
      }
    } else if (input) {
      if (comboInput === input && comboMenu && !comboMenu.hidden) closeComboMenu();
      else {
        input.focus();
        openComboMenu(input);
      }
    }
    return;
  }
  if (e.target.id === "add-row") {
    addRow();
    schedulePreview();
  }
  if (e.target.id === "save-items") saveCustomerItems();
  const addP = e.target.closest(".add-period");
  if (addP) {
    const extra = addP.closest(".item-extra");
    if (extra) showItemPeriod(extra.previousElementSibling, true);
    schedulePreview();
  }
  const delP = e.target.closest(".del-period");
  if (delP) {
    const extra = delP.closest(".item-extra");
    if (extra) showItemPeriod(extra.previousElementSibling, false);
    schedulePreview();
  }
  const addD = e.target.closest(".add-discount");
  if (addD) {
    const extra = addD.closest(".item-extra");
    if (extra) showItemDiscount(extra.previousElementSibling, true);
    schedulePreview();
  }
  const delD = e.target.closest(".del-discount");
  if (delD) {
    const extra = delD.closest(".item-extra");
    if (extra) showItemDiscount(extra.previousElementSibling, false);
    recalc();
    schedulePreview();
  }
  if (e.target.closest(".del")) {
    const positions = document.querySelectorAll("#items .position");
    if (positions.length > 1) {
      const pos = e.target.closest(".position");
      if (pos) pos.remove();
    }
    recalc();
    schedulePreview();
  }
});

// Reverse-Charge-Absicherung: ohne Kunden-USt-IdNr. kein Erzeugen (kein Datenverlust).
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (form.id !== "invoice-form") return;
  if (e.submitter && e.submitter.hasAttribute("formaction")) return; // nur der Erzeugen-Button
  const treatment = document.querySelector("#tax_treatment");
  const vat = form.querySelector('[name="buyer_vat_id"]');
  if (treatment && (treatment.value === "eu_reverse" || treatment.value === "non_eu") && vat && !vat.value.trim()) {
    e.preventDefault();
    vat.setCustomValidity(window.MSG_NEED_BUYER_VAT || "VAT ID required");
    vat.reportValidity();
    vat.focus();
  }
});
document.addEventListener("input", (e) => {
  if (e.target.name === "buyer_vat_id") e.target.setCustomValidity("");
});

let restoredFromLang = false;
(function restoreAfterLangSwitch() {
  const raw = sessionStorage.getItem("erechnung:lang");
  if (!raw) return;
  sessionStorage.removeItem("erechnung:lang");
  try {
    const parsed = JSON.parse(raw);
    restoreForm(document.getElementById("invoice-form"), parsed);
    updateStateField((parsed.buyer_state || [])[0]); // Staat-Auswahl nach Sprachwechsel wiederherstellen
    restoredFromLang = true;
  } catch (e) {
    /* ignorieren */
  }
})();

if (!restoredFromLang) applyDraft();

const previewFrameEl = document.getElementById("preview-frame");
if (previewFrameEl) previewFrameEl.addEventListener("load", scaleMiniPreview);
window.addEventListener("resize", scaleMiniPreview);

const previewExpandBtn = document.getElementById("preview-expand");
if (previewExpandBtn) previewExpandBtn.addEventListener("click", openPreviewDrawer);
const drawerCloseBtn = document.getElementById("drawer-close");
if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", closePreviewDrawer);
const previewDrawer = document.getElementById("preview-drawer");
if (previewDrawer)
  previewDrawer.addEventListener("click", (e) => {
    if (e.target === previewDrawer) closePreviewDrawer();
  });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const d = document.getElementById("preview-drawer");
    if (d && !d.hidden) closePreviewDrawer();
    const m = document.getElementById("cust-delete-modal");
    if (m && !m.hidden) m.hidden = true;
    closeFormatMenu();
  }
});

showNote();
applyProfile();
updateTaxnrHint();
validateMasterData();
toggleRefFields();
updateStateField();
syncServicePeriod();
syncItemPeriods();
syncItemDiscounts();
syncAllUnitDisplays();
updateDiscTypeLabels();
refreshSavedItems();
recalc();
updatePreview();
