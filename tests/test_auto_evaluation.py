"""
Test Poin 7: auto-evaluation + real return computation.
"""
import pytest

from services.sheets_client import (
    _parse_price_range, _parse_price_single, _determine_outcome,
)


# ═══════════════════════════════════════════════════════════════
# Parsing helpers
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("s,expected", [
    ("Rp 1,000 - Rp 1,100", (1000.0, 1100.0)),
    ("Rp 500 - Rp 600",     (500.0, 600.0)),
    ("Rp 1,234,567 - Rp 1,300,000", (1234567.0, 1300000.0)),
    ("Rp 5,000",            (None, None)),
    ("",                    (None, None)),
    (None,                  (None, None)),
])
def test_parse_price_range(s, expected):
    assert _parse_price_range(s) == expected


@pytest.mark.parametrize("s,expected", [
    ("1,000", 1000.0),
    ("Rp 1,000", 1000.0),
    ("500", 500.0),
    ("", None),
    (None, None),
])
def test_parse_price_single(s, expected):
    assert _parse_price_single(s) == expected


# ═══════════════════════════════════════════════════════════════
# Outcome determination
# ═══════════════════════════════════════════════════════════════
def _out(**kw):
    defaults = dict(
        entry_low=100, entry_high=101, tp_low=105, sl=97,
        actual_high=103, actual_low=99, actual_close=102,
        entry_miss="No",
    )
    defaults.update(kw)
    return _determine_outcome(**defaults)


def test_outcome_win_tp_hit():
    assert _out(actual_high=106) == "Win"


def test_outcome_loss_sl_hit():
    assert _out(actual_low=96) == "Loss"


def test_outcome_sl_wins_when_both_hit():
    """Konservatif: candle yang sentuh SL + TP → Loss (SL menang)."""
    assert _out(actual_low=95, actual_high=110) == "Loss"


def test_outcome_close_based_win():
    assert _out(actual_close=102, actual_high=103, actual_low=99) == "Win"


def test_outcome_close_based_loss():
    assert _out(actual_close=100, actual_high=102, actual_low=99.5) == "Loss"


def test_outcome_not_touched():
    assert _out(entry_miss="Yes", actual_low=103) == "Not Touched"


def test_outcome_suspended_zero_high():
    assert _out(actual_high=0) == "Suspended"


def test_outcome_no_sl_tp_falls_back_to_close():
    assert _out(sl=None, tp_low=None, actual_close=102) == "Win"
    assert _out(sl=None, tp_low=None, actual_close=100) == "Loss"


# ═══════════════════════════════════════════════════════════════
# integrate_actual_to_v12 — real return computation (bukan ±0.03)
# ═══════════════════════════════════════════════════════════════
def _make_pred(entry_low=100, entry_high=101, close=100):
    from config.settings import FACTOR_KEYS
    pred = {"entry_low": entry_low, "entry_high": entry_high, "close_price": close}
    for k in FACTOR_KEYS:
        pred[f"sig_{k}"] = 0.5
    return pred


def test_integrate_uses_real_return_for_win(monkeypatch):
    """WIN: actual_return = (Actual_High - entry_high) / entry_high."""
    from services import sheets_client
    monkeypatch.setattr(
        sheets_client, "load_v12_predictions",
        lambda t, mode: _make_pred(),
    )
    captured = {}
    def fake_update(ticker, sigs, ret, volatility=0.02,
                    memory_store=None, skip_save=False):
        captured["ret"] = ret
        captured["skip_save"] = skip_save
    monkeypatch.setattr(sheets_client, "update_v12_memory", fake_update)

    sheets_client.integrate_actual_to_v12(
        waktu="2026-09-01 10:00", saham="BBRI", mode="swing",
        actual_data={
            "Actual_High": "110", "Actual_Low": "99",
            "Actual_Close": "108", "Outcome": "Win", "Entry_Miss": "No",
        },
        memory_store={},
    )
    # (110 - 101) / 101 = 0.0891
    assert captured["ret"] == pytest.approx(0.0891, abs=0.001)
    assert captured["skip_save"] is True  # cron mode


def test_integrate_uses_real_return_for_loss(monkeypatch):
    from services import sheets_client
    monkeypatch.setattr(
        sheets_client, "load_v12_predictions",
        lambda t, mode: _make_pred(),
    )
    captured = {}
    def fake_update(ticker, sigs, ret, volatility=0.02,
                    memory_store=None, skip_save=False):
        captured["ret"] = ret
    monkeypatch.setattr(sheets_client, "update_v12_memory", fake_update)

    sheets_client.integrate_actual_to_v12(
        waktu="2026-09-01 10:00", saham="BBRI", mode="swing",
        actual_data={
            "Actual_High": "102", "Actual_Low": "95",
            "Actual_Close": "96", "Outcome": "Loss", "Entry_Miss": "No",
        },
        memory_store={},
    )
    # (95 - 101) / 101 = -0.0594
    assert captured["ret"] == pytest.approx(-0.0594, abs=0.001)


def test_integrate_not_touched_skips_update(monkeypatch):
    from services import sheets_client
    monkeypatch.setattr(
        sheets_client, "load_v12_predictions",
        lambda t, mode: _make_pred(),
    )
    called = {"n": 0}
    def fake_update(*a, **kw): called["n"] += 1
    monkeypatch.setattr(sheets_client, "update_v12_memory", fake_update)

    sheets_client.integrate_actual_to_v12(
        waktu="2026-09-01 10:00", saham="BBRI", mode="swing",
        actual_data={"Actual_High": "110", "Actual_Low": "103",
                     "Actual_Close": "108", "Outcome": "Not Touched",
                     "Entry_Miss": "Yes"},
        memory_store={},
    )
    assert called["n"] == 0


# ═══════════════════════════════════════════════════════════════
# update_v12_memory — memory_store + skip_save
# ═══════════════════════════════════════════════════════════════
def test_update_v12_memory_uses_provided_store(monkeypatch):
    from services import sheets_client
    saved = {"n": 0}
    monkeypatch.setattr(
        sheets_client, "save_v12_memory",
        lambda mem: saved.update({"n": saved["n"] + 1}),
    )
    store = {}
    sheets_client.update_v12_memory(
        "BBRI", {"Momentum": 0.5, "MeanRev": -0.3},
        actual_return=0.05, memory_store=store,
    )
    assert "BBRI" in store
    assert saved["n"] == 1  # skip_save=False default → save dipanggil


def test_update_v12_memory_skip_save(monkeypatch):
    from services import sheets_client
    saved = {"n": 0}
    monkeypatch.setattr(
        sheets_client, "save_v12_memory",
        lambda mem: saved.update({"n": saved["n"] + 1}),
    )
    store = {}
    sheets_client.update_v12_memory(
        "BBRI", {"Momentum": 0.5, "MeanRev": -0.3},
        actual_return=0.05, memory_store=store, skip_save=True,
    )
    assert "BBRI" in store
    assert saved["n"] == 0  # skip_save=True → save tidak dipanggil


# ═══════════════════════════════════════════════════════════════
# get_gsheet — env var override (cron context)
# ═══════════════════════════════════════════════════════════════
def test_get_gsheet_uses_env_vars_when_set(monkeypatch, tmp_path):
    """Cron: env var → bypass st.secrets."""
    from services import sheets_client

    fake_json = tmp_path / "fake_creds.json"
    fake_json.write_text('{"type": "service_account"}')

    captured = {}
    def fake_from_file(path, scopes):
        captured["path"] = path
        captured["scopes"] = scopes
        return "fake_creds_obj"
    class FakeClient:
        def open_by_key(self, sid):
            captured["sheet_id"] = sid
            return "fake_sheet"
    class FakeGSpread:
        @staticmethod
        def authorize(creds):
            captured["auth_creds"] = creds
            return FakeClient()

    monkeypatch.setattr(sheets_client, "Credentials", type(
        "FakeCreds", (), {"from_service_account_file": staticmethod(fake_from_file)}
    ))
    monkeypatch.setattr(sheets_client, "gspread", FakeGSpread)
    monkeypatch.setenv("CRON_GCP_CREDENTIALS_PATH", str(fake_json))
    monkeypatch.setenv("CRON_SHEET_ID", "FAKE_SHEET_ID_123")

    result = sheets_client.get_gsheet()
    assert result == "fake_sheet"
    assert captured["path"] == str(fake_json)
    assert captured["sheet_id"] == "FAKE_SHEET_ID_123"
# ═══════════════════════════════════════════════════════════════
# REGRESSION — _compute_learning_return aligned with memory update
# ═══════════════════════════════════════════════════════════════
def test_learning_return_win_uses_high():
    """Win → pakai actual_high (best-case, notes: alpha)."""
    from services.sheets_client import _compute_learning_return
    # entry=101, high=110 → (110-101)/101 = +8.91%
    assert _compute_learning_return(101, "Win", 110, 99, 108) == pytest.approx(0.0891, abs=1e-4)


def test_learning_return_loss_uses_low():
    """Loss → pakai actual_low (worst-case, simetris)."""
    from services.sheets_client import _compute_learning_return
    # entry=101, low=95 → (95-101)/101 = -5.94%
    assert _compute_learning_return(101, "Loss", 102, 95, 96) == pytest.approx(-0.0594, abs=1e-4)


def test_learning_return_loss_with_positive_close():
    """
    REGRESSION: Loss karena SL hit, tapi close rebound positif.
    actual_return yang dilaporkan harus tetap negatif (dari actual_low),
    bukan positif dari close.
    """
    from services.sheets_client import _compute_learning_return
    # entry=101, low=95 (SL hit), close=106 (rebound)
    # Harus pakai low → -5.94%, BUKAN close → +4.95%
    r = _compute_learning_return(101, "Loss", 108, 95, 106)
    assert r < 0, f"Loss harus return negatif, dapat {r}"
    assert r == pytest.approx(-0.0594, abs=1e-4)


def test_learning_return_zero_for_nt():
    from services.sheets_client import _compute_learning_return
    assert _compute_learning_return(101, "Not Touched", 105, 99, 102) == 0.0
    assert _compute_learning_return(101, "Suspended", 0, 0, 0) == 0.0


def test_learning_return_zero_entry_ref():
    from services.sheets_client import _compute_learning_return
    assert _compute_learning_return(0, "Win", 110, 99, 108) == 0.0
    assert _compute_learning_return(-5, "Loss", 100, 90, 95) == 0.0


def test_learning_return_clips_extreme():
    """Return di-clip ke [-1, 1] walau harga ekstrem."""
    from services.sheets_client import _compute_learning_return
    # high jauh 5× entry → clip ke 1.0
    assert _compute_learning_return(100, "Win", 500, 95, 400) == 1.0
    # low mendekati 0 → clip ke -1.0
    assert _compute_learning_return(100, "Loss", 102, 1, 50) == pytest.approx(-0.99, abs=0.01)
# ═══════════════════════════════════════════════════════════════
# REGRESSION — SQMI lookahead case
# ═══════════════════════════════════════════════════════════════
def test_outcome_not_touched_when_low_above_entry_high():
    """SQMI: entry_high=83, actual_low=84 → NT, bukan Loss."""
    from services.sheets_client import _determine_outcome
    outcome = _determine_outcome(
        entry_low=82, entry_high=83, tp_low=86, sl=79,
        actual_high=90, actual_low=84, actual_close=87,
        entry_miss="Yes",
    )
    assert outcome == "Not Touched"


def test_auto_adjust_false_used_in_fetch():
    """Guard: fetch WAJIB pakai auto_adjust=False."""
    import inspect
    from services import sheets_client
    src = inspect.getsource(sheets_client.auto_evaluate_riwayat_actual)
    assert "auto_adjust=False" in src


def test_conditional_filter_uses_signal_hour():
    """Guard: filter harus conditional `>` untuk post-market, `>=` intraday."""
    import inspect
    from services import sheets_client
    src = inspect.getsource(sheets_client.auto_evaluate_riwayat_actual)
    assert "signal_hour >= 16" in src
    assert "df.index.date > dt_signal" in src
    assert "df.index.date >= dt_signal" in src