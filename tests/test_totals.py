"""Tests für die Geldmathematik – das Herz eines Rechnungstools.
Schützt Rundung, Rabatte (Position + gesamt) und Steuerberechnung vor Regressionen."""
from decimal import Decimal

from zugferd import _dec, compute_totals, q


def item(qty, price, disc="0", dtype="pct"):
    return {
        "description": "x", "quantity": qty, "unit": "C62", "unit_price": price,
        "item_discount": disc, "item_discount_type": dtype,
    }


def test_basic_19pct():
    computed, line, disc, basis, tax, grand = compute_totals([item("2", "100")], Decimal("19"))
    assert line == Decimal("200.00")
    assert basis == Decimal("200.00")
    assert tax == Decimal("38.00")
    assert grand == Decimal("238.00")


def test_reduced_7pct():
    *_, tax, grand = compute_totals([item("1", "100")], Decimal("7"))
    assert tax == Decimal("7.00")
    assert grand == Decimal("107.00")


def test_zero_rate_reverse_charge():
    *_, tax, grand = compute_totals([item("1", "100")], Decimal("0"))
    assert tax == Decimal("0.00")
    assert grand == Decimal("100.00")


def test_line_discount_pct():
    computed, line, *_ = compute_totals([item("1", "100", "10", "pct")], Decimal("0"))
    assert computed[0]["net"] == Decimal("90.00")
    assert line == Decimal("90.00")


def test_line_discount_abs_capped_to_gross():
    computed, *_ = compute_totals([item("1", "100", "999", "abs")], Decimal("0"))
    assert computed[0]["net"] == Decimal("0.00")


def test_line_discount_pct_capped_at_100():
    computed, *_ = compute_totals([item("1", "100", "150", "pct")], Decimal("0"))
    assert computed[0]["net"] == Decimal("0.00")


def test_overall_discount_clamped_to_line_total():
    _, line, disc, basis, *_ = compute_totals([item("1", "100")], Decimal("19"), Decimal("500"))
    assert disc == Decimal("100.00")
    assert basis == Decimal("0.00")


def test_negative_overall_discount_becomes_zero():
    _, _, disc, *_ = compute_totals([item("1", "100")], Decimal("19"), Decimal("-50"))
    assert disc == Decimal("0.00")


def test_rounding_half_up():
    assert q("0.125") == Decimal("0.13")
    computed, *_ = compute_totals([item("1", "0.125")], Decimal("0"))
    assert computed[0]["gross"] == Decimal("0.13")


def test_multiple_items_sum():
    _, line, *_ = compute_totals([item("2", "50"), item("3", "10")], Decimal("0"))
    assert line == Decimal("130.00")  # 100 + 30


def test_dec_robust_against_garbage():
    assert _dec("abc") == Decimal("0")
    assert _dec("") == Decimal("0")
    assert _dec("NaN") == Decimal("0")
    assert _dec("Infinity") == Decimal("0")
    assert _dec(None) == Decimal("0")
    assert _dec("1.5") == Decimal("1.5")
    assert _dec("x", "7") == Decimal("7")
