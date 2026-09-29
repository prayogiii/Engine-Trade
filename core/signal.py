"""Kategorisasi sinyal & mapping arah/magnitudo ekspektasi."""
from __future__ import annotations
from typing import NamedTuple


class SignalCategory(NamedTuple):
    category: str
    expected_direction: int      # +1 buy, -1 sell, 0 hold/neutral
    expected_magnitude: float    # threshold return minimum


def parse_signal_category(signal_str: str, regime_str: str = "") -> SignalCategory:
    """Parse string sinyal → (kategori, arah, magnitudo)."""
    s = str(signal_str).upper()
    r = str(regime_str).upper()

    if 'STRONG BUY' in s:
        return SignalCategory('STRONG_BUY', +1, 0.020)
    if 'BUY' in s:
        return SignalCategory('BUY', +1, 0.010)
    if 'HOLD' in s:
        return SignalCategory('HOLD', 0, 0.025)
    if 'AVOID' in s or 'SKIP' in s:
        bearish_kw = ['PANIC', 'BEARISH', 'DISTRIBUSI', 'DOWNTREND']
        is_bearish = any(k in s for k in bearish_kw) or any(k in r for k in bearish_kw)
        if is_bearish:
            return SignalCategory('AVOID_BEARISH', -1, 0.015)
        return SignalCategory('AVOID_UNCLEAR', 0, 0.030)
    return SignalCategory('UNKNOWN', 0, 0.030)