// Tests der Client-Rechenlogik (static/calc.js). Ausführen: node --test tests/calc.test.js
// Werte spiegeln bewusst die serverseitigen Erwartungen (z. B. 2x100 @19% = 238),
// damit Client- und Server-Berechnung nicht auseinanderlaufen.
const test = require("node:test");
const assert = require("node:assert/strict");
const calc = require("../static/calc.js");

test("num: Komma und Punkt als Dezimaltrenner, robuste Defaults", () => {
  assert.equal(calc.num("1234,56"), 1234.56);
  assert.equal(calc.num("1234.56"), 1234.56);
  assert.equal(calc.num(""), 0);
  assert.equal(calc.num(null), 0);
  assert.equal(calc.num("abc"), 0);
  assert.equal(calc.num(5), 5);
});

test("lineNet: ohne Rabatt = Menge x Preis", () => {
  assert.equal(calc.lineNet(2, 100), 200);
});

test("lineNet: Prozent-Rabatt", () => {
  assert.equal(calc.lineNet(1, 200, 10, "pct"), 180);
});

test("lineNet: absoluter Rabatt, gedeckelt aufs Brutto", () => {
  assert.equal(calc.lineNet(1, 100, 30, "abs"), 70);
  assert.equal(calc.lineNet(1, 100, 150, "abs"), 0);
});

test("totals: Netto/Steuer/Brutto (2x100 @19% = 238)", () => {
  const t = calc.totals({ items: [{ qty: 2, price: 100 }], rate: 19 });
  assert.equal(t.net, 200);
  assert.equal(t.basis, 200);
  assert.equal(t.tax, 38);
  assert.equal(t.grand, 238);
});

test("totals: Gesamtrabatt prozentual", () => {
  const t = calc.totals({ items: [{ qty: 1, price: 1000 }], rate: 19, discount: 10, discountType: "pct" });
  assert.equal(t.discount, 100);
  assert.equal(t.basis, 900);
  assert.equal(t.tax, 171);
  assert.equal(t.grand, 1071);
});

test("totals: Gesamtrabatt absolut, gedeckelt auf Netto", () => {
  const t = calc.totals({ items: [{ qty: 1, price: 100 }], rate: 0, discount: 500, discountType: "abs" });
  assert.equal(t.discount, 100);
  assert.equal(t.basis, 0);
  assert.equal(t.grand, 0);
});

test("totals: Anzahlung gedeckelt + Zahlbetrag", () => {
  const t = calc.totals({ items: [{ qty: 1, price: 100 }], rate: 19, prepaid: 50 });
  assert.equal(t.grand, 119);
  assert.equal(t.prepaid, 50);
  assert.equal(t.due, 69);
  const t2 = calc.totals({ items: [{ qty: 1, price: 100 }], rate: 19, prepaid: 9999 });
  assert.equal(t2.prepaid, 119); // auf Brutto gedeckelt
  assert.equal(t2.due, 0);
});

test("totals: Positions- UND Gesamtrabatt kombiniert (mit Rundung wie Server)", () => {
  // 2x100 -10% = 180; +1x50 = 230 Netto; -5% gesamt = 218,50; 19% USt
  const t = calc.totals({
    items: [
      { qty: 2, price: 100, discVal: 10, discType: "pct" },
      { qty: 1, price: 50 },
    ],
    rate: 19,
    discount: 5,
    discountType: "pct",
  });
  assert.equal(t.net, 230);
  assert.equal(t.discount, 11.5);
  assert.equal(t.basis, 218.5);
  assert.equal(t.tax, 41.52); // q(41.515) HALF_UP -> 41,52 (wie compute_totals)
  assert.equal(t.grand, 260.02);
});

test("q: kaufmännische Rundung HALF_UP inkl. Float-Fallen", () => {
  assert.equal(calc.q(1.005), 1.01);
  assert.equal(calc.q(2.675), 2.68);
  assert.equal(calc.q(0.375), 0.38);
  assert.equal(calc.q(100), 100);
});

test("num: deutsche Tausendertrennung korrekt parsen", () => {
  assert.equal(calc.num("1.234,56"), 1234.56);
  assert.equal(calc.num("2.500,00"), 2500);
  assert.equal(calc.num("1234,56"), 1234.56);
  assert.equal(calc.num("1234.56"), 1234.56);
});

// Diese Fälle MÜSSEN mit _num_str() in app.py übereinstimmen (Server-Parität).
// Spiegel-Test: tests/test_routes.py::test_num_str_matches_calc_js_num.
const NUM_PARITY = [
  ["1234,56", 1234.56], ["1.234,56", 1234.56], ["2.500,00", 2500],
  ["1234.56", 1234.56], ["1.234.567", 1234567], ["1.234", 1.234],
  ["1234", 1234], ["", 0], ["abc", 0], ["12,", 12], ["1e9", 1000000000],
];
test("num: Parität-Fälle (müssen Server _num_str spiegeln)", () => {
  for (const [inp, exp] of NUM_PARITY) assert.equal(calc.num(inp), exp);
});

test("totals: Sub-Cent-Werte werden pro Zeile gerundet (round-then-sum)", () => {
  // 3 Zeilen 1x0,125: Server rundet jede Zeile q(0,125)=0,13 -> Netto 0,39 (nicht 0,375)
  const t = calc.totals({ items: [
    { qty: 1, price: 0.125 }, { qty: 1, price: 0.125 }, { qty: 1, price: 0.125 },
  ], rate: 0 });
  assert.equal(t.net, 0.39);
});

test("totals: negative Eingaben werden auf 0 geklemmt", () => {
  const t = calc.totals({ items: [{ qty: 1, price: 100 }], rate: 19, discount: -50, discountType: "pct", prepaid: -10 });
  assert.equal(t.discount, 0);
  assert.equal(t.prepaid, 0);
  assert.equal(t.grand, 119);
});
