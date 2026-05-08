"""
Triple Supertrend Strategy (ported from Pine Script)

Parameters (matching TradingView default):
  ST1: ATR=11, Factor=2.0
  ST2: ATR=10, Factor=1.0
  ST3: ATR=12, Factor=3.0

Entry : all 3 bullish (dir == -1)
Exit 1: any bearish AND close < entry_price  → Stop Loss
Exit 2: all bearish                           → Full Trend Flip
"""

from smc_engine import calc_atr

ST_PARAMS = [
    {'atr_period': 11, 'factor': 2.0},
    {'atr_period': 10, 'factor': 1.0},
    {'atr_period': 12, 'factor': 3.0},
]


def calc_supertrend(candles: list, factor: float, atr_period: int):
    """
    Matches ta.supertrend() logic in Pine Script.
    direction: -1 = bullish/green, 1 = bearish/red
    """
    n    = len(candles)
    atrs = calc_atr(candles, atr_period)
    hl2  = [(c['h'] + c['l']) / 2 for c in candles]

    upper_basic = [hl2[i] + factor * atrs[i] for i in range(n)]
    lower_basic = [hl2[i] - factor * atrs[i] for i in range(n)]

    final_upper = [upper_basic[0]] + [0.0] * (n - 1)
    final_lower = [lower_basic[0]] + [0.0] * (n - 1)
    direction   = [1] * n
    supertrend  = [upper_basic[0]] * n

    for i in range(1, n):
        # Final upper: ratchet down (never rises unless price broke above)
        if upper_basic[i] < final_upper[i-1] or candles[i-1]['c'] > final_upper[i-1]:
            final_upper[i] = upper_basic[i]
        else:
            final_upper[i] = final_upper[i-1]

        # Final lower: ratchet up (never falls unless price broke below)
        if lower_basic[i] > final_lower[i-1] or candles[i-1]['c'] < final_lower[i-1]:
            final_lower[i] = lower_basic[i]
        else:
            final_lower[i] = final_lower[i-1]

        # Direction — matches Pine: close > upperBand[1] → bull, close < lowerBand[1] → bear
        if candles[i]['c'] > final_upper[i-1]:
            direction[i] = -1
        elif candles[i]['c'] < final_lower[i-1]:
            direction[i] = 1
        else:
            direction[i] = direction[i-1]

        supertrend[i] = final_lower[i] if direction[i] == -1 else final_upper[i]

    return supertrend, direction


def analyze(candles: list) -> dict:
    """
    Compute Triple Supertrend state for the latest bar.
    Returns dict with all_green, any_red, all_red, directions, st_values, cur_price.
    """
    directions = []
    st_values  = []

    for p in ST_PARAMS:
        st, dir_ = calc_supertrend(candles, p['factor'], p['atr_period'])
        directions.append(dir_[-1])
        st_values.append(round(st[-1], 4))

    all_green = all(d == -1 for d in directions)
    any_red   = any(d ==  1 for d in directions)
    all_red   = all(d ==  1 for d in directions)

    return {
        'all_green':  all_green,
        'any_red':    any_red,
        'all_red':    all_red,
        'directions': directions,  # [-1, -1, -1] = all green
        'st_values':  st_values,   # [price, price, price]
        'cur_price':  candles[-1]['c'],
    }


def should_enter(state: dict) -> bool:
    """進場：三條全綠"""
    return state['all_green']


def should_exit(state: dict, entry_price: float) -> tuple:
    """
    出場判斷，回傳 (bool, reason_str)
    Exit 1: any red AND close < entry_price  → 止損
    Exit 2: all red                          → 趨勢全翻
    """
    if state['all_red']:
        return True, '全紅翻空 (Full Trend Flip)'
    if state['any_red'] and state['cur_price'] < entry_price:
        return True, '任一翻紅 + 低於進場價 (Stop Loss)'
    return False, ''
