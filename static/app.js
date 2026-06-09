function fmt(n) {
  const locale = window.UI_LANG === "en" ? "en-US" : "de-DE";
  return n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function num(v) {
  return parseFloat((v || "0").replace(",", ".")) || 0;
}

// .item-extra einer Position robust finden (liegt außerhalb von .position-head,
// daher NICHT über nextElementSibling – das wäre der Löschbutton).
function itemExtraOf(row) {
  const pos = row.closest(".position");
  return pos ? pos.querySelector(".item-extra") : null;
}

// Feste Formular-/Totals-Elemente einmalig auflösen (recalc läuft pro Tastendruck).
// Diese Knoten sind statisch in form.html und werden nie neu gerendert; nur die
// Positionszeilen (#items .item) sind dynamisch und werden weiter pro Aufruf gelesen.
let _recalcEls = null;
function recalcEls() {
  if (_recalcEls) return _recalcEls;
  const q = (s) => document.querySelector(s);
  _recalcEls = {
    taxSel: q("#tax_treatment"), discount: q("#discount"),
    discountType: q('[name="discount_type"]'), prepaid: q("#prepaid"),
    subRow: q("#t-sub-row"), discRow: q("#t-disc-row"),
    tSub: q("#t-sub"), tDisc: q("#t-disc"),
    tNet: q("#t-net"), tTax: q("#t-tax"), tGrand: q("#t-grand"),
    prepaidRow: q("#t-prepaid-row"), dueRow: q("#t-due-row"),
    tPrepaid: q("#t-prepaid"), tDue: q("#t-due"), taxLabel: q("#t-tax-label"),
  };
  return _recalcEls;
}

function recalc() {
  const el = recalcEls();
  const opt = el.taxSel && el.taxSel.options[el.taxSel.selectedIndex];
  const rate = num(opt ? opt.dataset.rate : 0);
  const rows = document.querySelectorAll("#items .item");
  const items = [];
  rows.forEach((row) => {
    const extra = itemExtraOf(row);
    const dInp = extra && extra.querySelector(".disc-input");
    const dType = extra && extra.querySelector(".disc-type");
    items.push({
      qty: row.querySelector(".qty").value,
      price: row.querySelector(".price").value,
      discVal: dInp ? dInp.value : 0,
      discType: dType ? dType.value : "pct",
    });
  });
  const t = InvoiceCalc.totals({
    items: items,
    rate: rate,
    discount: el.discount ? el.discount.value : 0,
    discountType: el.discountType ? el.discountType.value : "pct",
    prepaid: el.prepaid ? el.prepaid.value : 0,
  });
  rows.forEach((row, i) => { row.querySelector(".line-sum").textContent = fmt(t.lines[i]); });

  if (t.discount > 0) {
    if (el.subRow) el.subRow.hidden = false;
    if (el.discRow) el.discRow.hidden = false;
    if (el.tSub) el.tSub.textContent = fmt(t.net);
    if (el.tDisc) el.tDisc.textContent = "− " + fmt(t.discount);
  } else {
    if (el.subRow) el.subRow.hidden = true;
    if (el.discRow) el.discRow.hidden = true;
  }
  if (el.tNet) el.tNet.textContent = fmt(t.basis);
  if (el.tTax) el.tTax.textContent = fmt(t.tax);
  if (el.tGrand) el.tGrand.textContent = fmt(t.grand);
  // Anzahlung abziehen -> Zahlbetrag (nur wenn > 0).
  if (t.prepaid > 0) {
    if (el.prepaidRow) { el.prepaidRow.hidden = false; if (el.tPrepaid) el.tPrepaid.textContent = "− " + fmt(t.prepaid); }
    if (el.dueRow) { el.dueRow.hidden = false; if (el.tDue) el.tDue.textContent = fmt(t.due); }
  } else {
    if (el.prepaidRow) el.prepaidRow.hidden = true;
    if (el.dueRow) el.dueRow.hidden = true;
  }
  const vatLabel = window.VAT_LABEL || "USt";
  if (el.taxLabel) el.taxLabel.textContent = rate > 0 ? vatLabel + " " + rate + " %" : vatLabel;
}

// Passt die gewählte Behandlung zum Land des Rechnungsempfängers?
// Kleinunternehmer hängt am Verkäuferstatus und ist immer zulässig.
function isTreatmentCompatible(treatment, country) {
  if (treatment === "kleinunternehmer") return true;
  // Einzige Quelle für die Land→Behandlung-Regel ist deriveTreatment.
  const want = deriveTreatment(country);
  if (treatment === want) return true;
  // Zulässige Alternativen zum Standardvorschlag:
  if (want === "de_19") return treatment === "de_7"; // ermäßigter Inlandssatz
  if (want === "non_eu") return treatment === "non_eu_g"; // Drittland ohne USt-IdNr
  return false;
}
// Erklärungs-/Warnbox unter dem Dropdown aktualisieren.
function showNote() {
  const sel = document.querySelector("#tax_treatment");
  if (!sel) return;
  const opt = sel.querySelector("option:checked");
  const explain = document.querySelector("#tax-explain");
  const warn = document.querySelector("#tax-warn");
  const cc = document.querySelector("[name='buyer_country']");
  const country = cc ? cc.value : "DE";
  const ok = isTreatmentCompatible(sel.value, country);
  // Erklärung der GEWÄHLTEN Behandlung immer zeigen (auch bei Mismatch);
  // die Warnung erscheint zusätzlich darüber.
  if (explain) {
    explain.textContent = opt.dataset.explain || "";
    explain.hidden = !opt.dataset.explain;
  }
  if (warn) {
    if (ok) {
      warn.hidden = true;
    } else {
      const wantOpt = sel.querySelector('option[value="' + deriveTreatment(country) + '"]');
      const wantLabel = wantOpt ? wantOpt.textContent.trim() : "";
      const tmpl = window.MSG_TAX_MISMATCH || "{suggested}";
      warn.textContent = tmpl.replace("{suggested}", wantLabel);
      warn.hidden = false;
    }
  }
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
function autoSelectTreatment() {
  const sel = document.querySelector("#tax_treatment");
  if (!sel) return;
  // Kleinunternehmer bleibt unangetastet; alle anderen ggf. an das Land anpassen.
  if (sel.value !== "kleinunternehmer") {
    const cc = document.querySelector("[name='buyer_country']");
    const want = deriveTreatment(cc ? cc.value : "DE");
    if (sel.value !== want && [...sel.options].some((o) => o.value === want)) {
      sel.value = want;
    }
  }
  // Immer aktualisieren – auch wenn die Behandlung gleich bleibt, kann sich
  // die Mismatch-Warnung durch ein geändertes Kundenland ändern.
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
  // Hinweis unter der Vorschau: XRechnung = XML + PDF (kein eingebettetes XML).
  const note = document.querySelector(".preview-note");
  if (note && note.dataset.xr) note.textContent = xr ? note.dataset.xr : note.dataset.zug;
}

// Format-Dropdown im Titel (gestylt wie die Combobox).
function positionFormatMenu() {
  const t = document.getElementById("format-trigger");
  const m = document.getElementById("format-menu");
  if (!t || !m) return;
  const r = t.getBoundingClientRect();
  m.style.left = r.left + "px";
  m.style.top = r.bottom + 6 + "px";
  // Breite an den Inhalt anpassen (sprachunabhängig), min. Triggerbreite.
  // Die Obergrenze (max-width) kommt aus dem CSS (vw), damit nichts abschneidet.
  m.style.width = "max-content";
  m.style.minWidth = r.width + "px";
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

// "entspricht Rechnungsdatum": Zeitraumfelder sperren (Werte bleiben erhalten,
// werden aber nicht gesendet -> BT-72 = Rechnungsdatum, PDF zeigt Hinweis).

// Den Pflicht-Hinweis nur zeigen, solange die Angabe noch fehlt. Sobald ein
// Zeitraum eingetragen ODER "entspricht Rechnungsdatum" gewählt ist, ausblenden.
function updatePeriodHint() {
  const hint = document.getElementById("period-hint");
  if (!hint) return;
  const docType = (document.querySelector("#doc_type") || {}).value;
  if (docType === "386") {
    // Vorausrechnung: Leistung noch nicht erbracht -> eigener Hinweis, immer sichtbar.
    if (window.MSG_PERIOD_HINT_PREPAY) hint.textContent = window.MSG_PERIOD_HINT_PREPAY;
    hint.hidden = false;
    return;
  }
  if (window.MSG_PERIOD_HINT) hint.textContent = window.MSG_PERIOD_HINT;
  const s = document.querySelector('#invoice-form [name="service_start"]');
  const en = document.querySelector('#invoice-form [name="service_end"]');
  const filled = !!(s && en && s.value && en.value);
  hint.hidden = filled;  // informativ: nur ausblenden, wenn ein Zeitraum eingetragen ist
}

// Bezugsfelder (Storno/Korrektur) nur bei Belegart != 380 (normale Rechnung) zeigen.
function toggleRefFields() {
  const sel = document.querySelector("#doc_type");
  if (!sel) return;
  const show = sel.value === "381" || sel.value === "384";  // Bezug nur bei Storno/Korrektur
  document.querySelectorAll(".ref-field").forEach((el) => {
    el.hidden = !show;
  });
  const refNo = document.querySelector("[name='ref_number']");
  if (refNo) refNo.required = show;
}

// Bezugs-Datum automatisch füllen, wenn die gewählte/getippte Nummer zu einer
// im Tool erzeugten Rechnung gehört. Externe Nummern (nicht in der Liste) lassen
// das Datum unangetastet -> manuell ausfüllbar.
const REF_DATES = Object.fromEntries(
  (Array.isArray(window.REF_INVOICES) ? window.REF_INVOICES : []).map((r) => [r.number, r.date])
);
function fillRefDate(input) {
  const d = REF_DATES[input.value.trim()];
  if (!d) return;
  const dateEl = document.querySelector("[name='ref_date']");
  if (dateEl) dateEl.value = d;
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
  const firstRow = container.querySelector(".position-row");
  const cloneRow = firstRow.cloneNode(true);
  // Alle Felder der geklonten Position zurücksetzen.
  cloneRow.querySelectorAll("input").forEach((i) => {
    if (i.classList.contains("qty")) i.value = "1";
    else if (i.classList.contains("price")) i.value = "0";
    else if (i.classList.contains("disc-input")) i.value = "0";
    else i.value = "";
  });
  const unit = cloneRow.querySelector(".unit");
  if (unit) {
    unit.selectedIndex = 0;
    syncUnitDisplay(unit);
  }
  const dType = cloneRow.querySelector(".disc-type");
  if (dType) dType.value = "pct";
  cloneRow.querySelector(".line-sum").textContent = fmt(0);
  container.appendChild(cloneRow);
  const clone = cloneRow.querySelector(".item");
  showExtras(clone, false); // neue Position startet ohne Zusatzfelder
  updateDiscTypeLabels();
}

// Inhalt einer Position leeren (für die letzte/einzige Position statt Entfernen).
function clearPosition(positionRow) {
  const item = positionRow.querySelector(".item");
  if (!item) return;
  const desc = item.querySelector('[name="description"]');
  if (desc) desc.value = "";
  const qty = item.querySelector(".qty");
  if (qty) qty.value = "1";
  const unit = item.querySelector(".unit");
  if (unit) { unit.selectedIndex = 0; syncUnitDisplay(unit); }
  const price = item.querySelector(".price");
  if (price) price.value = "0";
  const sum = item.querySelector(".line-sum");
  if (sum) sum.textContent = fmt(0);
  showExtras(item, false); // Zusatzfelder einklappen + leeren
}

// Leistungszeitraum einer Position ein-/ausblenden; beim Entfernen Datumsfelder leeren.
// Optionale Zusatzfelder (Leistungszeitraum + Rabatt + Rabattgrund) einer Zeile
// gemeinsam ein-/ausblenden; beim Entfernen alle Werte zurücksetzen.
function showExtras(el, show) {
  // .item-extra robust über die Positionszeile finden (liegt außerhalb der Box).
  const row = el.closest(".position-row");
  const extra = row && row.querySelector(".item-extra");
  if (!extra) return;
  const addBtn = extra.querySelector(".add-extras");
  const fields = extra.querySelector(".extra-row");
  if (!addBtn || !fields) return;
  addBtn.hidden = show;
  fields.hidden = !show;
  if (!show) {
    fields.querySelectorAll('input[type="date"]').forEach((i) => (i.value = ""));
    const inp = fields.querySelector(".disc-input");
    if (inp) inp.value = "0";
    const sel = fields.querySelector(".disc-type");
    if (sel) { sel.selectedIndex = 0; syncUnitDisplay(sel); }
    const reason = fields.querySelector(".disc-reason");
    if (reason) reason.value = "";
  }
}

// Beim Laden/Wiederherstellen: Zusatzfelder zeigen, wenn irgendein Wert gesetzt ist.
function syncItemExtras() {
  document.querySelectorAll("#items .item").forEach((row) => {
    const extra = itemExtraOf(row);
    if (!extra) return;
    const hasPeriod = [...extra.querySelectorAll('input[type="date"]')].some((i) => i.value);
    const dInp = extra.querySelector(".disc-input");
    const hasDisc = dInp && num(dInp.value) > 0;
    const reason = extra.querySelector(".disc-reason");
    const hasReason = reason && reason.value.trim();
    showExtras(row, !!(hasPeriod || hasDisc || hasReason));
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
  // Gesamtrabatt wiederherstellen und ggf. ausklappen.
  set("discount", inv.discount);
  set("discount_reason", inv.discount_reason);
  const dt = form.querySelector('[name="discount_type"]');
  if (dt && inv.discount_type) { dt.value = inv.discount_type; syncUnitDisplay(dt); }
  if (num(inv.discount) > 0 || (inv.discount_reason || "").trim()) {
    const add = document.getElementById("add-discount");
    const row = document.getElementById("discount-row");
    if (add && row) { row.hidden = false; add.hidden = true; }
  }
  // Anzahlung wiederherstellen und ggf. ausklappen.
  set("prepaid", inv.prepaid);
  set("prepaid_ref", inv.prepaid_ref);
  if (num(inv.prepaid) > 0 || (inv.prepaid_ref || "").trim()) {
    const add = document.getElementById("add-prepaid");
    const row = document.getElementById("prepaid-row");
    if (add && row) { row.hidden = false; add.hidden = true; }
  }

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

// ---- Bezugs-Combobox (Storno/Korrektur) – gleiche Optik wie die Kunden-Combobox.
// Tippen ODER aus den im Tool erzeugten Rechnungen wählen (Auswahl füllt Datum).
let refMenu = null;
let refInput = null;
let refIndex = -1;
function ensureRefMenu() {
  if (refMenu) return refMenu;
  refMenu = document.createElement("div");
  refMenu.className = "combo-menu";
  refMenu.hidden = true;
  document.body.appendChild(refMenu);
  return refMenu;
}
function closeRefMenu() {
  if (refMenu) refMenu.hidden = true;
  if (refInput) refInput.setAttribute("aria-expanded", "false");
  refInput = null;
  refIndex = -1;
}
function positionRefMenu(input) {
  const r = input.getBoundingClientRect();
  refMenu.style.left = r.left + "px";
  refMenu.style.top = r.bottom + 3 + "px";
  refMenu.style.width = Math.max(r.width, 240) + "px";
}
function openRefMenu(input) {
  const menu = ensureRefMenu();
  refInput = input;
  refIndex = -1;
  const q = input.value.trim().toLowerCase();
  const pool = (window.REF_INVOICES || []).filter(
    (r) => !q || (r.number || "").toLowerCase().includes(q)
  );
  menu.innerHTML = "";
  menu._pool = pool;
  if (!pool.length) {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    return;
  }
  pool.forEach((r) => {
    const opt = document.createElement("div");
    opt.className = "combo-opt";
    const d = document.createElement("span");
    d.className = "combo-opt-desc";
    d.textContent = r.number || "";
    opt.appendChild(d);
    if (r.date) {
      const p = document.createElement("span");
      p.className = "combo-opt-price";
      p.textContent = r.date;
      opt.appendChild(p);
    }
    opt.addEventListener("mousedown", (ev) => { ev.preventDefault(); chooseRef(r); });
    menu.appendChild(opt);
  });
  positionRefMenu(input);
  menu.hidden = false;
  input.setAttribute("aria-expanded", "true");
}
function chooseRef(r) {
  if (refInput) refInput.value = r.number || "";
  const dateEl = document.querySelector("[name='ref_date']");
  if (dateEl && r.date) dateEl.value = r.date;
  closeRefMenu();
}
function highlightRef(delta) {
  if (!refMenu || refMenu.hidden) return;
  const opts = refMenu.querySelectorAll(".combo-opt");
  if (!opts.length) return;
  refIndex = (refIndex + delta + opts.length) % opts.length;
  opts.forEach((o, i) => o.classList.toggle("active", i === refIndex));
  opts[refIndex].scrollIntoView({ block: "nearest" });
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
  if (!span || !opt) return;
  let text = opt.text;
  // Plural anzeigen, wenn es eine Mengen-Einheit ist und die Menge > 1 ist.
  const qtyunit = select.closest(".qtyunit");
  if (qtyunit && opt.dataset.plural) {
    const qty = qtyunit.querySelector(".qty");
    if (qty && num(qty.value) > 1) text = opt.dataset.plural;
  }
  span.textContent = text;
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
let settingsOpen = false; // true, solange das Einstellungen-Panel offen ist
// Vorschau-Anfragen: laufende abbrechen (neueste gewinnt, Server rendert Veraltetes
// nicht zu Ende) + identische Eingaben nicht erneut rendern.
let _previewAbort = null;
let _previewLastKey = null;
let _drawerAbort = null;
const A4_W = 794; // 210 mm bei 96 dpi – logische Breite der Mini-Vorschau
const A4_H = 1123; // 297 mm bei 96 dpi – A4-Höhe (eine Seite)
function scaleMiniPreview() {
  const frame = document.getElementById("preview-frame");
  const inner = frame && frame.parentElement;
  const wrap = inner && inner.parentElement;
  if (!frame || !inner || !wrap) return;
  const wrapW = wrap.clientWidth;
  // Nur bei tatsächlicher Breitenänderung neu skalieren -> verhindert eine
  // ResizeObserver-Rückkopplung (Zittern beim Öffnen, bevor das Layout steht).
  if (wrapW <= 0 || wrapW === scaleMiniPreview._lastW) return;
  scaleMiniPreview._lastW = wrapW;
  const s = wrapW / A4_W;
  frame.style.width = A4_W + "px";
  frame.style.height = A4_H + "px";
  frame.style.transform = "scale(" + s + ")";
  inner.style.height = A4_H * s + "px";
}
// force=true erzwingt ein Rendern trotz unveränderter Eingabe (z. B. nachdem sich
// die Stammdaten geändert haben – die stecken nicht im invoice-form-FormData).
function updatePreview(force) {
  if (settingsOpen) return; // im Einstellungen-Modus zeigt die Vorschau Archiv-PDFs
  const form = document.getElementById("invoice-form");
  const frame = document.getElementById("preview-frame");
  if (!form || !frame || !window.PREVIEW_URL) return;
  const data = new FormData(form);
  data.append("_full", "mini");
  // Dedup: identische Eingabe nicht erneut rendern (spart Server-Renders).
  let key = null;
  try { key = new URLSearchParams(data).toString(); } catch (e) { key = null; }
  if (!force && key !== null && key === _previewLastKey) return;
  // Veraltete, noch laufende Anfrage abbrechen -> ihre (späte) Antwort wird verworfen
  // und kann die neuere nicht out-of-order überschreiben; Verbindung wird frei.
  if (_previewAbort) _previewAbort.abort();
  const ctrl = new AbortController();
  _previewAbort = ctrl;
  fetch(window.PREVIEW_URL, { method: "POST", body: data, signal: ctrl.signal })
    .then((r) => r.text())
    .then((html) => {
      _previewLastKey = key; // erst nach Erfolg merken
      frame.srcdoc = html;
    })
    .catch(() => {}); // abgebrochene/fehlgeschlagene ignorieren
  // Der ausgeklappte Drawer zeigt das echte PDF und wird NICHT live aktualisiert
  // (PDF-Rendern ist zu langsam für jede Eingabe) -> nur beim Öffnen, s. openPreviewDrawer.
}
// Mehrseitig? Wenn der Inhalt das eine Mini-A4-Blatt überläuft, kleinen Hinweis zeigen.
// Heuristik (HTML-Überlauf ≈ PDF-Pagination); für die exakte Seitenzahl gibt es nur
// das echte PDF im ausgeklappten Drawer.
function checkMiniPages() {
  const frame = document.getElementById("preview-frame");
  const hint = document.getElementById("preview-pages-hint");
  if (!frame || !hint) return;
  const measure = () => {
    try {
      const b = frame.contentDocument && frame.contentDocument.body;
      if (!b) return;
      const multi = b.scrollHeight > b.clientHeight + 4;
      hint.textContent = multi ? " " + (window.MSG_PREVIEW_MULTIPAGE || "") : "";
      hint.hidden = !multi;
    } catch (e) {}
  };
  measure();
  // #R6: nach dem Laden der Schriften IM iframe erneut messen – vorher kann der Text
  // noch umfließen und die Überlauf-Messung verfälschen.
  try {
    const doc = frame.contentDocument;
    if (doc && doc.fonts && doc.fonts.ready) doc.fonts.ready.then(measure).catch(() => {});
  } catch (e) {}
}
// Ausgeklappte Ansicht: echtes (visuelles) PDF mit korrekten Seitenumbrüchen.
function updateDrawerPreview() {
  const drawer = document.getElementById("preview-drawer");
  const frame = document.getElementById("drawer-frame");
  const form = document.getElementById("invoice-form");
  if (!drawer || drawer.hidden || !frame || !form || !window.PREVIEW_PDF_URL) return;
  const data = new FormData(form);
  // #R4: laufende Drawer-Anfrage abbrechen, sonst kann eine langsamere ältere Antwort
  // nach einer neueren landen und ein veraltetes PDF zeigen.
  if (_drawerAbort) _drawerAbort.abort();
  const ctrl = new AbortController();
  _drawerAbort = ctrl;
  fetch(window.PREVIEW_PDF_URL, { method: "POST", body: data, signal: ctrl.signal })
    .then((r) => (r.ok ? r.blob() : Promise.reject(r)))
    .then((blob) => {
      if (ctrl.signal.aborted || drawer.hidden) return; // überholt oder inzwischen zu
      if (frame._objUrl) URL.revokeObjectURL(frame._objUrl);
      frame._objUrl = URL.createObjectURL(blob);
      frame.removeAttribute("srcdoc");
      frame.src = frame._objUrl;
    })
    .catch((err) => {
      if (err && err.name === "AbortError") return; // bewusst abgebrochen, kein Fehler
      frame.removeAttribute("src");
      frame.srcdoc =
        "<!doctype html><meta charset='utf-8'><body style='font:14px sans-serif;padding:40px;color:#888'>" +
        (window.MSG_NO_PREVIEW || "") + "</body>";
    });
}
function schedulePreview(force) {
  clearTimeout(previewTimer);
  // 250 ms: spürbar schneller als 350; überholte Anfragen werden ohnehin abgebrochen.
  previewTimer = setTimeout(() => updatePreview(force), 250);
}

function openPreviewDrawer() {
  const drawer = document.getElementById("preview-drawer");
  if (!drawer) return;
  drawer.hidden = false;
  document.body.classList.add("drawer-open");
  const frame = document.getElementById("drawer-frame");
  if (frame) {
    frame.removeAttribute("src");
    frame.srcdoc =
      "<!doctype html><meta charset='utf-8'><body style='font:14px sans-serif;padding:40px;color:#888'>" +
      (window.MSG_PREVIEW_LOADING || "") + "</body>";
  }
  updateDrawerPreview();
}
function closePreviewDrawer() {
  const drawer = document.getElementById("preview-drawer");
  if (!drawer) return;
  drawer.hidden = true;
  document.body.classList.remove("drawer-open");
  if (_drawerAbort) { _drawerAbort.abort(); _drawerAbort = null; } // laufenden PDF-Fetch stoppen
  // Blob-URL des PDFs freigeben (sonst bleibt es bis zum nächsten Öffnen im Speicher).
  const frame = document.getElementById("drawer-frame");
  if (frame && frame._objUrl) {
    frame.removeAttribute("src");
    URL.revokeObjectURL(frame._objUrl);
    frame._objUrl = null;
  }
}

let sellerSaveTimer;
function autosaveSeller() {
  const form = document.getElementById("settings-form");
  if (!form || !window.SELLER_AUTOSAVE_URL) return;
  // Nach dem Speichern Vorschau auffrischen (Stammdaten fließen ins PDF ein, stehen
  // aber nicht im invoice-form -> force, sonst greift die Dedup-Sperre).
  fetch(window.SELLER_AUTOSAVE_URL, { method: "POST", body: new FormData(form) })
    .then(() => updatePreview(true))
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
  if (e.target.classList.contains("qty")) {
    const qu = e.target.closest(".qtyunit");
    if (qu) syncUnitDisplay(qu.querySelector(".unit")); // Plural/Singular nachziehen
  }
  if (e.target.name && e.target.name.startsWith("buyer_")) scheduleCustomerSave();
  if (e.target.name === "service_start" || e.target.name === "service_end") updatePeriodHint();
  if (e.target.classList.contains("ref-name")) { fillRefDate(e.target); openRefMenu(e.target); }
  if (e.target.matches('#items [name="description"]')) openComboMenu(e.target);
  if (e.target.classList.contains("cust-name")) openCustMenu(e.target);
});
document.addEventListener("change", (e) => {
  if (e.target.name === "service_start" || e.target.name === "service_end") updatePeriodHint();
});
document.addEventListener("focusin", (e) => {
  if (e.target.matches('#items [name="description"]')) openComboMenu(e.target);
  if (e.target.classList.contains("cust-name")) openCustMenu(e.target);
  if (e.target.classList.contains("ref-name")) openRefMenu(e.target);
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
// Tastaturbedienung der Bezugs-Combobox.
document.addEventListener("keydown", (e) => {
  if (!e.target.classList || !e.target.classList.contains("ref-name")) return;
  if (!refMenu || refMenu.hidden) {
    if (e.key === "ArrowDown") {
      openRefMenu(e.target);
      e.preventDefault();
    }
    return;
  }
  if (e.key === "ArrowDown") {
    highlightRef(1);
    e.preventDefault();
  } else if (e.key === "ArrowUp") {
    highlightRef(-1);
    e.preventDefault();
  } else if (e.key === "Enter") {
    const pool = refMenu._pool;
    if (refIndex >= 0 && pool && pool[refIndex]) {
      chooseRef(pool[refIndex]);
      e.preventDefault();
    }
  } else if (e.key === "Escape") {
    closeRefMenu();
  }
});
document.addEventListener("mousedown", (e) => {
  const inMenu = e.target.closest(".combo-menu");
  const combo = e.target.closest(".combo");
  if (!combo && !inMenu) closeComboMenu();
  if (!e.target.closest(".unitsel") && !inMenu) closeUnitMenu();
  const inCustCombo = combo && combo.querySelector(".cust-name");
  if (!inCustCombo && !inMenu) closeCustMenu();
  const inRefCombo = combo && combo.querySelector(".ref-name");
  if (!inRefCombo && !inMenu) closeRefMenu();
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
  if (refInput && refMenu && !refMenu.hidden) positionRefMenu(refInput);
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
  if (e.target.id === "doc_type") { toggleRefFields(); updatePeriodHint(); }
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
  // Erststart: Datenordner per nativem Dialog wählen.
  if (e.target.id === "onboard-browse") {
    const input = document.getElementById("onboard-dir-input");
    e.target.disabled = true;
    fetch(window.DATA_DIR_BROWSE_URL, { method: "POST" })
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.path && input) input.value = d.path; })
      .catch(() => flashError())
      .finally(() => { e.target.disabled = false; });
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
    } else if (input && input.classList.contains("ref-name")) {
      if (refInput === input && refMenu && !refMenu.hidden) closeRefMenu();
      else {
        input.focus();
        openRefMenu(input);
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
  const addX = e.target.closest(".add-extras");
  if (addX) {
    const extra = addX.closest(".item-extra");
    if (extra) showExtras(extra.previousElementSibling, true);
    schedulePreview();
  }
  const delX = e.target.closest(".del-extras");
  if (delX) {
    const extra = delX.closest(".item-extra");
    if (extra) showExtras(extra.previousElementSibling, false);
    recalc();
    schedulePreview();
  }
  if (e.target.closest(".del")) {
    const rows = document.querySelectorAll("#items .position-row");
    const row = e.target.closest(".position-row");
    if (rows.length > 1 && row) {
      // Mehrere Positionen: entfernen – mit Undo (Node behält Werte/Extras und
      // wird beim Rückgängig an alter Stelle wieder eingesetzt).
      const parent = row.parentNode;
      const nextSibling = row.nextElementSibling;
      row.remove();
      recalc();
      schedulePreview();
      announce(window.MSG_ITEM_DELETED || "");
      flashUndo(window.MSG_ITEM_DELETED, () => {
        // Falls #items zwischenzeitlich umgebaut wurde (z. B. Kunde geladen),
        // sind parent/nextSibling evtl. veraltet -> robust wieder einsetzen.
        const container = parent && parent.isConnected ? parent : document.getElementById("items");
        if (!container) return;
        if (nextSibling && nextSibling.parentNode === container) container.insertBefore(row, nextSibling);
        else container.appendChild(row);
        recalc();
        schedulePreview();
      });
    } else if (row) {
      clearPosition(row); // einzige Position: nur Inhalt leeren
      recalc();
      schedulePreview();
    }
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
if (previewFrameEl) previewFrameEl.addEventListener("load", function () { scaleMiniPreview(); checkMiniPages(); });
window.addEventListener("resize", scaleMiniPreview);
// Spaltenbreite beobachten: neu skalieren, wenn sich die Layout-Breite ändert
// (Settle nach (Sprach-)Reload, Fonts) – nicht nur bei window.resize.
// WICHTIG: die STABILE Spalte (.preview-col) beobachten, nicht .preview-frame-wrap –
// deren Größe wird von der Skalierung beeinflusst (Rückkopplung -> Zittern).
// Zusätzlich per rAF drosseln, damit kein ResizeObserver-Loop entsteht.
const previewColEl = previewFrameEl && previewFrameEl.closest(".preview-col");
if (previewColEl && window.ResizeObserver) {
  let roPending = false;
  new ResizeObserver(() => {
    if (roPending) return;
    roPending = true;
    requestAnimationFrame(() => { roPending = false; scaleMiniPreview(); });
  }).observe(previewColEl);
}
// Nach dem Laden der Schriften erneut skalieren (Layout kann sich noch verschieben).
if (document.fonts && document.fonts.ready) document.fonts.ready.then(scaleMiniPreview);

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
updatePeriodHint();
syncItemExtras();
syncAllUnitDisplays();
updateDiscTypeLabels();
refreshSavedItems();
recalc();
updatePreview();

// === Einstellungen-/Archiv-Panel (In-Place auf der Startseite) ==============
let lastPreviewUrl = null;

// Screenreader-Ansage (Live-Region).
function announce(msg) {
  const el = document.getElementById("a11y-live");
  if (el && msg) el.textContent = msg;
}

// Kurz sichtbare Fehlermeldung (macht still scheiternde AJAX-Aktionen sichtbar).
let _toastTimer;
// Toast-Element (einmalig) anlegen oder wiederverwenden – Basis für beide Toasts.
function makeToast(id, className, role) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("div");
    el.id = id;
    el.className = className;
    el.setAttribute("role", role);
    document.body.appendChild(el);
  }
  return el;
}

function flashError(msg) {
  const el = makeToast("toast", "toast", "alert");
  el.textContent = msg || window.MSG_ACTION_FAILED || "Fehler";
  el.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

// Toast mit „Rückgängig"-Aktion (z. B. nach dem Löschen einer Position).
let _undoTimer;
function flashUndo(msg, onUndo) {
  const el = makeToast("undo-toast", "toast toast-undo", "status");
  el.textContent = "";
  const span = document.createElement("span");
  span.textContent = msg || "";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "toast-undo-btn";
  btn.textContent = window.MSG_UNDO || "Rückgängig";
  el.append(span, btn);
  el.hidden = false;
  const dismiss = () => { el.hidden = true; };
  clearTimeout(_undoTimer);
  _undoTimer = setTimeout(dismiss, 6000);
  btn.onclick = () => { clearTimeout(_undoTimer); dismiss(); if (onUndo) onUndo(); };
}

function setPreviewHead(label) {
  const head = document.querySelector(".preview-head span");
  if (head && label) head.textContent = label;
}

// Archiv-Vorschau = dasselbe HTML wie die Live-Vorschau (aus der Sidecar),
// daher exakt derselbe Look, kein PDF-Viewer, kein dunkler Rand.
function showInvoicePreview(url, label) {
  fetch(url)
    .then((r) => (r.ok ? r.text() : Promise.reject()))
    .then((html) => {
      const frame = document.getElementById("preview-frame");
      if (!frame) return;
      frame.removeAttribute("src");
      frame.srcdoc = html;
      scaleMiniPreview();
      setPreviewHead(label);
    })
    .catch(() => { flashError(); showNoPreview(label); });
}

// Eine Archiv-Zeile in der Vorschau zeigen (für Hover UND Fokus).
function previewRow(row) {
  const key = row.dataset.previewUrl || row.dataset.viewUrl;
  if (!key || key === lastPreviewUrl) return;
  lastPreviewUrl = key;
  const fileCell = row.querySelector("td");
  const label = fileCell ? fileCell.textContent.trim() : "";
  if (row.dataset.previewUrl) showInvoicePreview(row.dataset.previewUrl, label);
  else showNoPreview(label);
}

// Platzhalter für Dateien ohne Sidecar (Fremd-/Altdateien): per Klick noch
// öffenbar, aber keine Inline-Vorschau.
function showNoPreview(label) {
  const frame = document.getElementById("preview-frame");
  if (!frame) return;
  const msg = (window.MSG_NO_PREVIEW || "Keine Vorschau vorhanden").replace(/[<>&]/g, "");
  frame.removeAttribute("src");
  frame.srcdoc =
    '<!doctype html><meta charset="utf-8">' +
    '<body style="margin:0;height:100vh;display:flex;align-items:center;' +
    'justify-content:center;font:14px -apple-system,BlinkMacSystemFont,sans-serif;' +
    'color:#9aa0a6;background:#fff">' + msg + "</body>";
  scaleMiniPreview();
  setPreviewHead(label);
}

// Zurück in die Live-HTML-Vorschau.
function restoreLivePreview() {
  setPreviewHead(window.MSG_LIVE_PREVIEW);
  scaleMiniPreview();
  schedulePreview(true); // Stammdaten könnten sich geändert haben -> Dedup umgehen
}

function loadDepsAsync() {
  const slot = document.getElementById("deps-card");
  if (!slot || !window.SETTINGS_DEPINFO_URL) return;
  fetch(window.SETTINGS_DEPINFO_URL)
    .then((r) => r.text())
    .then((html) => { slot.innerHTML = html; })
    .catch(() => {});
}

function loadSettingsPanel() {
  const pane = document.getElementById("settings-pane");
  if (!pane || !window.SETTINGS_PANEL_URL) return Promise.resolve();
  return fetch(window.SETTINGS_PANEL_URL)
    .then((r) => r.text())
    .then((html) => { pane.innerHTML = html; loadDepsAsync(); })
    .catch(() => flashError());
}

function openSettings() {
  const pane = document.getElementById("settings-pane");
  const content = document.getElementById("form-content");
  const btn = document.getElementById("settings-toggle");
  if (!pane || !content) return;
  settingsOpen = true;
  loadSettingsPanel().then(() => {
    pane.hidden = false;
    content.hidden = true;
    pane.focus(); // Fokus ins Panel ziehen (Tastatur/Screenreader behalten den Kontext)
    announce(window.MSG_SETTINGS_OPENED);
  });
  if (btn) {
    btn.textContent = btn.dataset.close;
    btn.classList.add("active");
    btn.setAttribute("aria-expanded", "true");
  }
}

function closeSettings() {
  const pane = document.getElementById("settings-pane");
  const content = document.getElementById("form-content");
  const btn = document.getElementById("settings-toggle");
  settingsOpen = false;
  lastPreviewUrl = null;
  if (pane) pane.hidden = true;
  if (content) content.hidden = false;
  if (btn) {
    btn.textContent = btn.dataset.open;
    btn.classList.remove("active");
    btn.setAttribute("aria-expanded", "false");
    btn.focus(); // Fokus zurück auf den Auslöser
  }
  announce(window.MSG_SETTINGS_CLOSED);
  restoreLivePreview();
}

(function wireSettingsPane() {
  const pane = document.getElementById("settings-pane");
  const toggle = document.getElementById("settings-toggle");
  if (!pane || !toggle) return;
  toggle.addEventListener("click", () => (settingsOpen ? closeSettings() : openSettings()));

  // Archiv-Zeile in der Vorschau zeigen – bei Hover UND bei Tastaturfokus.
  pane.addEventListener("mouseover", (e) => {
    const row = e.target.closest(".arch-row");
    if (row) previewRow(row);
  });
  pane.addEventListener("focusin", (e) => {
    const row = e.target.closest(".arch-row");
    if (row) previewRow(row);
  });
  // Enter/Leertaste auf einer fokussierten Zeile öffnet das PDF.
  pane.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".arch-row");
    if (row && e.target === row && row.dataset.viewUrl) {
      e.preventDefault();
      window.open(row.dataset.viewUrl, "_blank");
    }
  });

  pane.addEventListener("click", (e) => {
    // Löschen (mit Bestätigung) -> danach Panel neu laden.
    const del = e.target.closest(".js-delete");
    if (del) {
      e.preventDefault();
      const fn = del.dataset.filename;
      if (!confirm(fn + "\n\n" + (window.MSG_CONFIRM_DELETE || ""))) return;
      const fd = new FormData();
      fd.append("filename", fn);
      fetch(window.ARCHIVE_DELETE_URL, { method: "POST", body: fd })
        .then(() => loadSettingsPanel())
        .catch(() => flashError());
      return;
    }
    // Im Finder zeigen (Desktop-App): die Datei liegt schon im output/-Ordner.
    const reveal = e.target.closest(".reveal-btn");
    if (reveal) {
      e.preventDefault();
      fetch("/reveal/" + encodeURIComponent(reveal.dataset.file), { method: "POST" })
        .catch(() => flashError());
      return;
    }
    // CSV einer Einzelrechnung (Desktop): Server schreibt sie + zeigt sie im Finder.
    const csvBtn = e.target.closest(".csv-export-btn");
    if (csvBtn) {
      e.preventDefault();
      fetch(csvBtn.dataset.url).catch(() => flashError());
      return;
    }
    // Datenordner durchsuchen (nativer Dialog).
    const browse = e.target.closest("#dd-browse");
    if (browse) {
      const input = pane.querySelector("#data-dir-input");
      browse.disabled = true;
      fetch(window.DATA_DIR_BROWSE_URL, { method: "POST" })
        .then((r) => r.json())
        .then((d) => { if (d.ok && d.path && input) input.value = d.path; })
        .catch(() => flashError())
        .finally(() => { browse.disabled = false; });
      return;
    }
    // Export-Preset (Jahr/Quartal) -> Datumsfelder füllen.
    const preset = e.target.closest("[data-preset]");
    if (preset) {
      const from = pane.querySelector("#export-from");
      const to = pane.querySelector("#export-to");
      if (from && to) {
        const y = new Date().getFullYear();
        const iso = (yy, m, d) => `${yy}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
        const ranges = {
          thisyear: [iso(y, 1, 1), iso(y, 12, 31)],
          lastyear: [iso(y - 1, 1, 1), iso(y - 1, 12, 31)],
          q1: [iso(y, 1, 1), iso(y, 3, 31)],
          q2: [iso(y, 4, 1), iso(y, 6, 30)],
          q3: [iso(y, 7, 1), iso(y, 9, 30)],
          q4: [iso(y, 10, 1), iso(y, 12, 31)],
        };
        const r = ranges[preset.dataset.preset];
        if (r) { from.value = r[0]; to.value = r[1]; }
      }
      return;
    }
    // CSV-Export (Bulk, gefiltert über Datumsbereich).
    if (e.target.closest("#export-csv")) {
      const from = (pane.querySelector("#export-from") || {}).value || "";
      const to = (pane.querySelector("#export-to") || {}).value || "";
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const q = qs.toString();
      const url = window.EXPORT_CSV_URL + (q ? "?" + q : "");
      // Desktop: Server schreibt die CSV + zeigt sie im Finder (kein Download).
      if (window.IS_DESKTOP) fetch(url).catch(() => flashError());
      else window.location = url;
      return;
    }
    // Klick auf die Zeile (nicht auf Links/Buttons) -> PDF im Tab öffnen.
    if (e.target.closest("a, button")) return;
    const row = e.target.closest(".arch-row");
    if (row && row.dataset.viewUrl) window.open(row.dataset.viewUrl, "_blank");
  });

  // Formulare im Panel ohne Seitenwechsel abschicken.
  pane.addEventListener("submit", (e) => {
    const form = e.target;
    e.preventDefault();
    if (form.classList.contains("datadir-form")) {
      fetch(window.DATA_DIR_SET_URL, { method: "POST", body: new FormData(form) })
        .then(() => loadSettingsPanel())
        .catch(() => flashError());
    } else { // Datei prüfen / Archiv-Rechnung prüfen -> Panel mit Ergebnis ersetzen
      fetch(window.SETTINGS_PANEL_URL, { method: "POST", body: new FormData(form) })
        .then((r) => r.text())
        .then((html) => { pane.innerHTML = html; loadDepsAsync(); })
        .catch(() => flashError());
    }
  });
})();

// === Hinweis bei bereits vergebener Rechnungsnummer (blockiert NICHT) ========
// Doppelte Nummern bleiben erlaubt (z. B. Korrekturrechnungen) – wir weisen nur hin.
function checkInvoiceNumber() {
  const input = document.getElementById("invoice-number");
  const warn = document.getElementById("number-warning");
  if (!input || !warn) return;
  const val = input.value.trim();
  const used = Array.isArray(window.USED_NUMBERS) ? window.USED_NUMBERS : [];
  if (used.includes(val)) {  // bereits vergeben (Duplikat)
    warn.textContent = window.MSG_NUMBER_IN_USE || "";
    warn.hidden = false;
    return;
  }
  // Lücke im Nummernkreis (Format YYYY-NNN): höhere Sequenz als bisher + 1.
  const m = val.match(/^(\d{4})-(\d+)$/);
  if (m) {
    const year = m[1];
    const seq = parseInt(m[2], 10);
    let maxSeq = 0;
    used.forEach((u) => {
      const mm = u.match(/^(\d{4})-(\d+)$/);
      if (mm && mm[1] === year) maxSeq = Math.max(maxSeq, parseInt(mm[2], 10));
    });
    if (maxSeq > 0 && seq > maxSeq + 1) {
      const last = year + "-" + String(maxSeq).padStart(3, "0");
      warn.textContent = (window.MSG_NUMBER_GAP || "").replace("%s", last);
      warn.hidden = false;
      return;
    }
  }
  warn.hidden = true;
}
(function initInvoiceNumberCheck() {
  const input = document.getElementById("invoice-number");
  if (!input) return;
  input.addEventListener("input", checkInvoiceNumber);
  checkInvoiceNumber();
})();

// === Gesamtrabatt ein-/ausklappen (analog zu den Positions-Zusatzfeldern) ====
(function initOverallDiscount() {
  const add = document.getElementById("add-discount");
  const row = document.getElementById("discount-row");
  const del = document.getElementById("del-discount");
  if (!add || !row) return;
  add.addEventListener("click", () => {
    row.hidden = false;
    add.hidden = true;
    const inp = document.getElementById("discount");
    if (inp) inp.focus();
  });
  if (del) {
    del.addEventListener("click", () => {
      row.hidden = true;
      add.hidden = false;
      const inp = document.getElementById("discount");
      if (inp) inp.value = "0";
      const reason = row.querySelector('[name="discount_reason"]');
      if (reason) reason.value = "";
      const dt = row.querySelector('[name="discount_type"]');
      if (dt) { dt.selectedIndex = 0; syncUnitDisplay(dt); }
      recalc();
      schedulePreview();
    });
  }
})();

// === Anzahlung ein-/ausklappen (analog Gesamtrabatt) =========================
(function initOverallPrepaid() {
  const add = document.getElementById("add-prepaid");
  const row = document.getElementById("prepaid-row");
  const del = document.getElementById("del-prepaid");
  if (!add || !row) return;
  add.addEventListener("click", () => {
    row.hidden = false;
    add.hidden = true;
    const inp = document.getElementById("prepaid");
    if (inp) inp.focus();
  });
  if (del) {
    del.addEventListener("click", () => {
      row.hidden = true;
      add.hidden = false;
      const inp = document.getElementById("prepaid");
      if (inp) inp.value = "0";
      const ref = row.querySelector('[name="prepaid_ref"]');
      if (ref) ref.value = "";
      recalc();
      schedulePreview();
    });
  }
})();
