/* Reine Rechenlogik der Live-Vorschau – ohne DOM, damit testbar (Node + Browser).
   MUSS fachlich mit der serverseitigen compute_totals (zugferd.py) übereinstimmen.
   Daher: auf JEDER Stufe runden (wie q() im Server) und Zahlen identisch parsen
   wie _num_str() in app.py. */
(function (root) {
  "use strict";

  // Zahleneingabe -> Number. Deutsche Schreibweise: Komma = Dezimaltrenner, Punkte
  // = Tausender. Ohne Komma gilt der Punkt (falls vorhanden) als Dezimaltrenner.
  // MUSS mit _num_str() in app.py übereinstimmen, sonst weichen Vorschau und PDF ab.
  function num(v) {
    if (v == null) return 0;
    var s = String(v).trim();
    if (!s) return 0;
    if (s.indexOf(",") !== -1) s = s.replace(/\./g, "").replace(",", ".");
    else if ((s.match(/\./g) || []).length >= 2) s = s.replace(/\./g, ""); // "1.234.567" = Tausender
    return parseFloat(s) || 0;
  }

  // 2 Dezimalen, kaufmännisch (HALF_UP) – Gegenstück zu q() in zugferd.py. Reine
  // Float-Arithmetik kann Decimal nicht 100 % treffen; der kleine Epsilon-Schubs
  // fängt die üblichen x,xx5-Fälle (z. B. 1.005 -> 1.01) wie ROUND_HALF_UP.
  function q(x) {
    return Math.round((x + 1e-9) * 100) / 100;
  }

  // Netto einer Position (gerundet wie compute_totals): Brutto = q(Menge x Preis),
  // minus Positionsrabatt (Prozent oder fester Betrag, gedeckelt aufs Brutto).
  function lineNet(qty, price, discVal, discType) {
    var gross = q(num(qty) * num(price));
    var d = num(discVal);
    if (d < 0) d = 0;
    var disc;
    if (discType === "abs") {
      disc = q(d);
      if (disc > gross) disc = gross;
    } else {
      if (d > 100) d = 100;
      disc = q((gross * d) / 100);
    }
    return q(gross - disc);
  }

  // Gesamtsummen, Stufe für Stufe gerundet wie compute_totals + die Anzahlungs-
  // Logik aus render_invoice_preview. opts: { items:[{qty,price,discVal,discType}],
  // rate, discount, discountType, prepaid }.
  function totals(opts) {
    opts = opts || {};
    var lineTotal = 0;
    var lines = (opts.items || []).map(function (it) {
      var ln = lineNet(it.qty, it.price, it.discVal, it.discType);
      lineTotal += ln;
      return ln;
    });
    lineTotal = q(lineTotal);

    var d = num(opts.discount);
    if (d < 0) d = 0;
    var discount;
    if (opts.discountType === "pct") {
      if (d > 100) d = 100;
      discount = q((lineTotal * d) / 100);
    } else {
      discount = q(d);
      if (discount > lineTotal) discount = lineTotal;
    }

    var basis = q(lineTotal - discount);
    var tax = q((basis * num(opts.rate)) / 100);
    var grand = q(basis + tax);

    var prepaid = num(opts.prepaid);
    if (prepaid < 0) prepaid = 0;
    prepaid = q(prepaid);
    if (prepaid > grand) prepaid = grand;
    var due = q(grand - prepaid);

    return {
      lines: lines, net: lineTotal, discount: discount, basis: basis,
      tax: tax, grand: grand, prepaid: prepaid, due: due,
    };
  }

  var api = { num: num, q: q, lineNet: lineNet, totals: totals };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.InvoiceCalc = api;
})(typeof self !== "undefined" ? self : this);
