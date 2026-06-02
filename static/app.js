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
  document.querySelectorAll("#items tbody .item").forEach((row) => {
    const sum = num(row.querySelector(".qty").value) * num(row.querySelector(".price").value);
    row.querySelector(".line-sum").textContent = fmt(sum);
    net += sum;
  });
  const tax = (net * rate) / 100;
  document.querySelector("#t-net").textContent = fmt(net);
  document.querySelector("#t-tax").textContent = fmt(tax);
  document.querySelector("#t-grand").textContent = fmt(net + tax);
  const vatLabel = window.VAT_LABEL || "USt";
  document.querySelector("#t-tax-label").textContent = rate > 0 ? vatLabel + " " + rate + " %" : vatLabel;
}

function showNote() {
  const opt = document.querySelector("#tax_treatment option:checked");
  document.querySelector("#tax-note").textContent = opt.dataset.note || "";
}

function showProfileHint() {
  const profile = document.querySelector("#profile");
  const hint = document.querySelector("#profile-hint");
  if (profile && hint) hint.hidden = profile.value !== "xrechnung";
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
  const tbody = document.querySelector("#items tbody");
  const first = tbody.querySelector(".item");
  const clone = first.cloneNode(true);
  clone.querySelectorAll("input").forEach((i) => {
    if (i.classList.contains("qty")) i.value = "1";
    else if (i.classList.contains("price")) i.value = "0";
    else i.value = "";
  });
  const unit = clone.querySelector(".unit");
  if (unit) unit.selectedIndex = 0;
  clone.querySelector(".line-sum").textContent = fmt(0);
  const cloneExtra = first.nextElementSibling.cloneNode(true); // zugehörige Zusatz-Zeile
  cloneExtra.querySelectorAll("input").forEach((i) => (i.value = ""));
  tbody.appendChild(clone);
  tbody.appendChild(cloneExtra);
  showItemPeriod(clone, false); // neue Zeile startet ohne Leistungszeitraum
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
  if (!show) periodLabel.querySelectorAll("input").forEach((i) => (i.value = ""));
}

// Beim Laden/Wiederherstellen: Zeitraum nur dort zeigen, wo bereits Daten stehen.
function syncItemPeriods() {
  document.querySelectorAll("#items tbody .item").forEach((row) => {
    const extra = row.nextElementSibling;
    const has = extra ? [...extra.querySelectorAll("input")].some((i) => i.value) : false;
    showItemPeriod(row, has);
  });
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
  const repeating = ["description", "quantity", "unit", "unit_price", "item_start", "item_end"];
  const itemCount = (data.description || []).length;
  let rows = form.querySelectorAll("#items tbody .item").length;
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
    const tbody = document.querySelector("#items tbody");
    while (tbody.querySelectorAll(".item").length < items.length) addRow();
    const rows = tbody.querySelectorAll(".item");
    items.forEach((it, i) => {
      const row = rows[i];
      row.querySelector('[name="description"]').value = it.description || "";
      row.querySelector(".qty").value = it.quantity || "1";
      const u = row.querySelector(".unit");
      if (u && it.unit) u.value = it.unit;
      row.querySelector(".price").value = it.unit_price || "0";
    });
  }
}

function currentCustomer() {
  const sel = document.querySelector("#saved_customer");
  if (!sel || sel.value === "") return null;
  return (window.CUSTOMERS || [])[sel.value] || null;
}

// Gespeicherte Positionen des gewählten Kunden ins Dropdown laden.
function refreshSavedItems() {
  const sel = document.querySelector("#saved_item");
  if (!sel) return;
  const c = currentCustomer();
  const items = (c && c.items) || [];
  sel.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = "";
  ph.textContent = window.MSG_INSERT_ITEM || "–";
  sel.appendChild(ph);
  items.forEach((it, i) => {
    const o = document.createElement("option");
    o.value = i;
    o.textContent = (it.description || "?") + (it.unit_price ? " — " + it.unit_price : "");
    sel.appendChild(o);
  });
  sel.disabled = items.length === 0;
}

function insertSavedItem(i) {
  const c = currentCustomer();
  if (!c || !c.items || !c.items[i]) return;
  const it = c.items[i];
  const tbody = document.querySelector("#items tbody");
  let rows = tbody.querySelectorAll(".item");
  let row = rows[rows.length - 1];
  if (row.querySelector('[name="description"]').value.trim()) {
    addRow();
    rows = tbody.querySelectorAll(".item");
    row = rows[rows.length - 1];
  }
  row.querySelector('[name="description"]').value = it.description || "";
  row.querySelector(".qty").value = it.quantity || "1";
  const u = row.querySelector(".unit");
  if (u && it.unit) u.value = it.unit;
  row.querySelector(".price").value = it.unit_price || "0";
  recalc();
  schedulePreview();
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
  form.querySelectorAll("#items tbody .item").forEach((row) => {
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
function updatePreview() {
  const form = document.getElementById("invoice-form");
  const frame = document.getElementById("preview-frame");
  if (!form || !frame || !window.PREVIEW_URL) return;
  fetch(window.PREVIEW_URL, { method: "POST", body: new FormData(form) })
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

let sellerSaveTimer;
function autosaveSeller() {
  const form = document.getElementById("settings-form");
  if (!form || !window.SELLER_AUTOSAVE_URL) return;
  fetch(window.SELLER_AUTOSAVE_URL, { method: "POST", body: new FormData(form) }).catch(() => {});
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
    return;
  }
  recalc();
  schedulePreview();
  if (e.target.name && e.target.name.startsWith("buyer_")) scheduleCustomerSave();
});
document.addEventListener("change", (e) => {
  if (e.target.id === "tax_treatment") showNote();
  if (e.target.id === "profile") showProfileHint();
  if (e.target.id === "buyer_country") updateStateField();
  if (e.target.id === "saved_customer") {
    if (e.target.value !== "") fillCustomer(e.target.value);
    else lastSavedCustomerName = "";
    refreshSavedItems();
  }
  if (e.target.id === "saved_item") {
    if (e.target.value !== "") insertSavedItem(e.target.value);
    e.target.value = "";
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
  if (e.target.classList.contains("del")) {
    const rows = document.querySelectorAll("#items tbody .item");
    if (rows.length > 1) {
      const item = e.target.closest(".item");
      const extra = item.nextElementSibling;
      item.remove();
      if (extra && extra.classList.contains("item-extra")) extra.remove();
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
  if (treatment && treatment.value === "eu_reverse" && vat && !vat.value.trim()) {
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

showNote();
showProfileHint();
updateStateField();
syncItemPeriods();
refreshSavedItems();
recalc();
updatePreview();
