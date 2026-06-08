/* Reine Rechenlogik der Live-Vorschau – ohne DOM, damit testbar (Node + Browser).
   MUSS fachlich mit der serverseitigen compute_totals (zugferd.py) übereinstimmen;
   Abweichungen würden in der Vorschau falsche Zahlen zeigen. */
(function (root) {
  "use strict";

  // "1.234,56" / "1234.56" / 1234.56 -> Number (Komma als Dezimaltrennzeichen).
  function num(v) {
    if (v == null) return 0;
    return parseFloat(String(v).replace(",", ".")) || 0;
  }

  // Netto einer Position: Brutto (Menge x Einzelpreis) minus Positionsrabatt.
  // discType "abs" = absoluter Betrag (gedeckelt aufs Brutto), sonst Prozent (0..100).
  function lineNet(qty, price, discVal, discType) {
    var gross = num(qty) * num(price);
    var d = num(discVal);
    var disc = 0;
    if (d > 0) {
      disc = discType === "abs" ? Math.min(d, gross) : (gross * Math.min(d, 100)) / 100;
    }
    return gross - disc;
  }

  // Gesamtsummen. opts: { items:[{qty,price,discVal,discType}], rate,
  //   discount, discountType, prepaid }. Gibt alle Zwischenwerte zurück.
  function totals(opts) {
    opts = opts || {};
    var net = 0;
    var lines = (opts.items || []).map(function (it) {
      var ln = lineNet(it.qty, it.price, it.discVal, it.discType);
      net += ln;
      return ln;
    });

    var discount = num(opts.discount);
    if (discount < 0) discount = 0;
    if (opts.discountType === "pct") discount = (net * Math.min(discount, 100)) / 100;
    else if (discount > net) discount = net;

    var basis = net - discount;
    var tax = (basis * num(opts.rate)) / 100;
    var grand = basis + tax;

    var prepaid = num(opts.prepaid);
    if (prepaid < 0) prepaid = 0;
    if (prepaid > grand) prepaid = grand;
    var due = grand - prepaid;

    return {
      lines: lines, net: net, discount: discount, basis: basis,
      tax: tax, grand: grand, prepaid: prepaid, due: due,
    };
  }

  var api = { num: num, lineNet: lineNet, totals: totals };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.InvoiceCalc = api;
})(typeof self !== "undefined" ? self : this);
