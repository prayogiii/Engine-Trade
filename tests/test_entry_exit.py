import pytest
from core.entry_exit import compute_entry_zone_and_sl_tp


def _base(**overrides):
    params = dict(
        last_price=1000.0, s1=970.0, r1=1030.0, r2=1060.0, res20=1020.0,
        atr_val=20.0, atr_pct=2.0, atr_daily=25.0,
        adx=25.0, rsi14=55.0, signal="⚡ BUY (TACTICAL)",
        is_daytrade=False, entry_error=0.0,
        fee_beli_pct=0.15, fee_jual_pct=0.25, bars_per_day=54,
    )
    params.update(overrides)
    return params


# ── Struktur output ──
def test_returns_all_required_keys():
    out = compute_entry_zone_and_sl_tp(**_base())
    for k in ("entry_low", "entry_high", "entry_low_f", "entry_high_f",
              "entry_zone_f", "sl", "sl_f", "sl_pct",
              "tp_low", "tp_high", "tp_low_f", "tp_high_f",
              "tp_pct_low", "tp_pct_high", "rrr"):
        assert k in out, f"missing key: {k}"


# ── Ordering invariant ──
def test_ordering_invariant():
    out = compute_entry_zone_and_sl_tp(**_base())
    assert out["sl"] < out["entry_low"] <= out["entry_high"] < out["tp_low"] <= out["tp_high"]


def test_ordering_invariant_daytrade():
    out = compute_entry_zone_and_sl_tp(**_base(is_daytrade=True))
    assert out["sl"] < out["entry_low"] <= out["entry_high"] < out["tp_low"] <= out["tp_high"]


def test_ordering_invariant_no_resistance():
    out = compute_entry_zone_and_sl_tp(**_base(r1=None, r2=None, res20=None))
    assert out["sl"] < out["entry_low"] <= out["entry_high"] < out["tp_low"]


# ── Swing BUY: pullback cap 2.5% ──
def test_swing_buy_pullback_capped_at_2_5pct():
    # atr_pct 8% akan menarik entry_low ke last*0.92, tapi harus di-cap 0.975
    out = compute_entry_zone_and_sl_tp(**_base(atr_pct=8.0, atr_val=80.0))
    assert out["entry_low"] >= 1000.0 * 0.975 - 0.5  # toleransi pembulatan tick


# ── DT: fee floor ──
def test_dt_tp_covers_fees():
    out = compute_entry_zone_and_sl_tp(**_base(is_daytrade=True))
    fee_floor = out["entry_low"] * (1 + (0.15 + 0.25) / 100.0 + 0.006)
    assert out["tp_low"] >= fee_floor - 0.5


# ── Sigma fallback (scanner path) ──
def test_sigma_ret_fallback_works():
    out = compute_entry_zone_and_sl_tp(**_base(
        atr_val=None, atr_pct=None, atr_daily=None, sigma_ret=0.02,
    ))
    assert out["atr_pct_used"] == pytest.approx(2.0, abs=1e-9)


def test_sigma_ret_none_defaults_to_3pct():
    out = compute_entry_zone_and_sl_tp(**_base(
        atr_val=None, atr_pct=None, atr_daily=None, sigma_ret=None,
    ))
    assert out["atr_pct_used"] == pytest.approx(3.0)


# ── Konsistensi: ATR vs σ yang setara hasilkan output identik ──
def test_atr_pct_and_sigma_equivalent():
    """atr_pct=2.0 dan sigma_ret=0.02 adalah sama secara numerik."""
    out_a = compute_entry_zone_and_sl_tp(**_base())
    out_b = compute_entry_zone_and_sl_tp(**_base(atr_val=None, atr_pct=None,
                                                  atr_daily=None, sigma_ret=0.02))
    assert out_a["entry_low"]  == pytest.approx(out_b["entry_low"],  abs=0.5)
    assert out_a["entry_high"] == pytest.approx(out_b["entry_high"], abs=0.5)
    assert out_a["sl"]         == pytest.approx(out_b["sl"],         abs=0.5)


# ── Entry error shift ──
def test_entry_error_shift_capped_at_1_5pct():
    out = compute_entry_zone_and_sl_tp(**_base(entry_error=0.10))  # 10% gap
    # shift maksimal = last*1.5% = 15 → entry_low tak boleh lebih dari +15 dari baseline
    baseline = compute_entry_zone_and_sl_tp(**_base(entry_error=0.0))
    assert out["entry_low"] - baseline["entry_low"] <= 15.5  # toleransi pembulatan


# ── No NaN, no crash pada edge cases ──
@pytest.mark.parametrize("price", [1.0, 50.0, 500.0, 50000.0])
def test_robust_across_price_ranges(price):
    out = compute_entry_zone_and_sl_tp(**_base(
        last_price=price, s1=price * 0.97,
        atr_val=price * 0.02, atr_pct=2.0,
    ))
    assert out["sl"] > 0
    assert out["entry_low"] > 0
    assert out["rrr"] >= 0


def test_min_rrr_enforced_for_swing():
    # Signal HOLD & R1 jauh → TP low harus tetap ≥ entry_ref + 1.6*risk
    out = compute_entry_zone_and_sl_tp(**_base(
        signal="⏸️ HOLD / WAIT", r1=None, r2=None,
    ))
    entry_ref = (out["entry_low"] + out["entry_high"]) / 2.0
    risk = entry_ref - out["sl"]
    if risk > 0:
        assert out["tp_low"] >= entry_ref + 1.6 * risk - 0.5


# ── Konsistensi lintas-caller: analyzer vs scanner path ──
def test_analyzer_and_scanner_paths_agree():
    """
    Skenario: saham dengan ATR% = σ% = 2.0.
    Analyzer passing atr_val/atr_pct; scanner passing sigma_ret.
    Hasil entry/SL harus identik (modulo tick rounding).
    """
    analyzer = compute_entry_zone_and_sl_tp(**_base(adx=25.0, rsi14=55.0))
    scanner  = compute_entry_zone_and_sl_tp(**_base(
        atr_val=None, atr_pct=None, atr_daily=None,
        sigma_ret=0.02, adx=None, rsi14=55.0,
    ))
    # Scanner tanpa ADX → sl_mult=1.0 (sama dgn analyzer ADX=25 <30 >20)
    assert analyzer["sl_mult_used"] == scanner["sl_mult_used"] == 1.0
    assert analyzer["entry_low_f"] == scanner["entry_low_f"]
    assert analyzer["sl_f"] == scanner["sl_f"]