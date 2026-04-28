"""
SMC Engine — 從 index.html 的 JavaScript 邏輯移植到 Python
保持與網頁分析器完全一致的演算法
"""
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

BULL = 1
BEAR = -1


# ─────────────────────────────────────────────────────────────
# ATR (Wilder's Smoothing)
# ─────────────────────────────────────────────────────────────
def calc_atr(candles: List[Dict], period: int = 14) -> List[float]:
    n = len(candles)
    tr = []
    for i, k in enumerate(candles):
        if i == 0:
            tr.append(k['h'] - k['l'])
        else:
            tr.append(max(
                k['h'] - candles[i-1]['c'],
                abs(k['l'] - candles[i-1]['c']),
                k['h'] - k['l']
            ))
    res = [0.0] * n
    p = min(period, n)
    res[p-1] = sum(tr[:p]) / p
    for i in range(p, n):
        res[i] = (res[i-1] * (p-1) + tr[i]) / p
    for i in range(p-1):
        res[i] = res[p-1]
    return res


# ─────────────────────────────────────────────────────────────
# 結構偵測 (Swing / Internal)
# ─────────────────────────────────────────────────────────────
def detect_structure_level(candles, size, parsed_h, parsed_l, atrs):
    n = len(candles)
    pivot_highs, pivot_lows, structures, order_blocks = [], [], [], []
    current_leg = 0
    trend_bias = 0
    last_ph = None
    last_pl = None
    ph_crossed = False
    pl_crossed = False

    for i in range(size, n):
        max_h = max(candles[j]['h'] for j in range(i - size + 1, i + 1))
        min_l = min(candles[j]['l'] for j in range(i - size + 1, i + 1))
        px = i - size

        if candles[px]['h'] > max_h and current_leg != 0:
            current_leg = 0
            last_ph = {'price': candles[px]['h'], 'idx': px}
            ph_crossed = False
            pivot_highs.append({'idx': px, 'price': candles[px]['h']})
        elif candles[px]['l'] < min_l and current_leg != 1:
            current_leg = 1
            last_pl = {'price': candles[px]['l'], 'idx': px}
            pl_crossed = False
            pivot_lows.append({'idx': px, 'price': candles[px]['l']})

        # 看多突破
        if last_ph and not ph_crossed and candles[i]['c'] > last_ph['price']:
            ph_crossed = True
            tag = 'CHoCH' if trend_bias == BEAR else 'BOS'
            structures.append({'type': tag, 'dir': 'bull', 'idx': i, 'price': last_ph['price'], 'from_idx': last_ph['idx']})
            trend_bias = BULL
            ob_idx = last_ph['idx']
            min_val = float('inf')
            for j in range(last_ph['idx'], i):
                if parsed_l[j] < min_val:
                    min_val = parsed_l[j]
                    ob_idx = j
            order_blocks.append({'type': 'bull', 'high': candles[ob_idx]['h'], 'low': candles[ob_idx]['l'],
                                  'idx': ob_idx, 'mitigated': False, 'struct_tag': tag})

        # 看空突破
        if last_pl and not pl_crossed and candles[i]['c'] < last_pl['price']:
            pl_crossed = True
            tag = 'CHoCH' if trend_bias == BULL else 'BOS'
            structures.append({'type': tag, 'dir': 'bear', 'idx': i, 'price': last_pl['price'], 'from_idx': last_pl['idx']})
            trend_bias = BEAR
            ob_idx = last_pl['idx']
            max_val = float('-inf')
            for j in range(last_pl['idx'], i):
                if parsed_h[j] > max_val:
                    max_val = parsed_h[j]
                    ob_idx = j
            order_blocks.append({'type': 'bear', 'high': candles[ob_idx]['h'], 'low': candles[ob_idx]['l'],
                                  'idx': ob_idx, 'mitigated': False, 'struct_tag': tag})

    # 標記已失效 OB
    last_c = candles[-1]
    for ob in order_blocks:
        if ob['type'] == 'bull' and last_c['l'] < ob['low']:
            ob['mitigated'] = True
        if ob['type'] == 'bear' and last_c['h'] > ob['high']:
            ob['mitigated'] = True

    return {'pivot_highs': pivot_highs, 'pivot_lows': pivot_lows,
            'structures': structures, 'order_blocks': order_blocks,
            'trend_bias': trend_bias, 'size': size}


# ─────────────────────────────────────────────────────────────
# FVG 偵測
# ─────────────────────────────────────────────────────────────
def detect_fvgs(candles):
    n = len(candles)
    fvgs = []
    for i in range(2, n):
        if candles[i]['l'] > candles[i-2]['h'] and candles[i-1]['c'] > candles[i-2]['h']:
            fvgs.append({'type': 'bull', 'top': candles[i]['l'], 'bottom': candles[i-2]['h'], 'idx': i, 'mitigated': False})
        if candles[i]['h'] < candles[i-2]['l'] and candles[i-1]['c'] < candles[i-2]['l']:
            fvgs.append({'type': 'bear', 'top': candles[i-2]['l'], 'bottom': candles[i]['h'], 'idx': i, 'mitigated': False})
    last = candles[-1]
    for f in fvgs:
        if f['type'] == 'bull' and last['l'] < f['bottom']:
            f['mitigated'] = True
        if f['type'] == 'bear' and last['h'] > f['top']:
            f['mitigated'] = True
    return fvgs[-40:]


# ─────────────────────────────────────────────────────────────
# 等高 / 等低點 (EQH / EQL)
# ─────────────────────────────────────────────────────────────
def detect_equal_hl(pivot_highs, pivot_lows, atrs):
    thr = 0.1
    eqh, eql = [], []
    for i in range(1, len(pivot_highs)):
        a, b = pivot_highs[i-1], pivot_highs[i]
        if abs(b['price'] - a['price']) < thr * atrs[b['idx']]:
            eqh.append({'idx1': a['idx'], 'idx2': b['idx'], 'price': (a['price'] + b['price']) / 2})
    for i in range(1, len(pivot_lows)):
        a, b = pivot_lows[i-1], pivot_lows[i]
        if abs(b['price'] - a['price']) < thr * atrs[b['idx']]:
            eql.append({'idx1': a['idx'], 'idx2': b['idx'], 'price': (a['price'] + b['price']) / 2})
    return {'eqh': eqh[-3:], 'eql': eql[-3:]}


# ─────────────────────────────────────────────────────────────
# 主分析函數
# ─────────────────────────────────────────────────────────────
def smc_analyze(candles):
    n = len(candles)
    atrs = calc_atr(candles, 14)
    parsed_h = [candles[i]['l'] if (candles[i]['h'] - candles[i]['l']) >= 2 * atrs[i] else candles[i]['h'] for i in range(n)]
    parsed_l = [candles[i]['h'] if (candles[i]['h'] - candles[i]['l']) >= 2 * atrs[i] else candles[i]['l'] for i in range(n)]

    sw_size = min(50, max(10, n // 5))
    swing    = detect_structure_level(candles, sw_size, parsed_h, parsed_l, atrs)
    internal = detect_structure_level(candles, 5, parsed_h, parsed_l, atrs)
    fvgs     = detect_fvgs(candles)
    eq       = detect_equal_hl(swing['pivot_highs'], swing['pivot_lows'], atrs)

    tr_high, tr_low = float('-inf'), float('inf')
    for i in range(sw_size, n):
        tr_high = max(tr_high, candles[i]['h'])
        tr_low  = min(tr_low,  candles[i]['l'])

    r = tr_high - tr_low or 1
    return {
        'swing': swing, 'internal': internal, 'fvgs': fvgs,
        'eqh': eq['eqh'], 'eql': eq['eql'],
        'tr_high': tr_high, 'tr_low': tr_low,
        'premium':    {'top': tr_high,            'bottom': tr_high - 0.05 * r},
        'discount':   {'top': tr_low + 0.05 * r,  'bottom': tr_low},
        'equilibrium':{'top': tr_high - 0.45 * r, 'bottom': tr_low + 0.45 * r},
        'atrs': atrs
    }


# ─────────────────────────────────────────────────────────────
# 交易計畫
# ─────────────────────────────────────────────────────────────
def build_smc_plan(candles, analysis):
    swing    = analysis['swing']
    internal = analysis['internal']
    fvgs     = analysis['fvgs']
    premium  = analysis['premium']
    discount = analysis['discount']
    cur      = candles[-1]['c']

    in_premium    = cur >= premium['bottom']
    in_discount   = cur <= discount['top']
    in_equilibrium = not in_premium and not in_discount

    sw_bull_obs = [o for o in swing['order_blocks']    if o['type'] == 'bull' and not o['mitigated']]
    sw_bear_obs = [o for o in swing['order_blocks']    if o['type'] == 'bear' and not o['mitigated']]
    in_bull_obs = [o for o in internal['order_blocks'] if o['type'] == 'bull' and not o['mitigated']]
    in_bear_obs = [o for o in internal['order_blocks'] if o['type'] == 'bear' and not o['mitigated']]
    active_fvgs = [f for f in fvgs if not f['mitigated']]

    last_sw = swing['structures'][-1]    if swing['structures']    else None
    last_in = internal['structures'][-1] if internal['structures'] else None

    bs = ss = 0
    if swing['trend_bias'] == BULL:    bs += 3
    elif swing['trend_bias'] == BEAR:  ss += 3
    if internal['trend_bias'] == BULL: bs += 2
    elif internal['trend_bias'] == BEAR: ss += 2
    if last_sw:
        if   last_sw['type'] == 'CHoCH' and last_sw['dir'] == 'bull': bs += 3
        elif last_sw['type'] == 'CHoCH' and last_sw['dir'] == 'bear': ss += 3
        elif last_sw['type'] == 'BOS'   and last_sw['dir'] == 'bull': bs += 1
        elif last_sw['type'] == 'BOS'   and last_sw['dir'] == 'bear': ss += 1
    if last_in:
        if last_in['type'] == 'CHoCH' and last_in['dir'] == 'bull': bs += 2
        elif last_in['type'] == 'CHoCH' and last_in['dir'] == 'bear': ss += 2
        elif last_in['type'] == 'BOS'   and last_in['dir'] == 'bull': bs += 1
        elif last_in['type'] == 'BOS'   and last_in['dir'] == 'bear': ss += 1
    if in_discount: bs += 2
    if in_premium:  ss += 2

    near_bull_ob = next((o for o in sw_bull_obs + in_bull_obs if cur <= o['high'] and cur >= o['low'] * 0.98), None)
    near_bear_ob = next((o for o in sw_bear_obs + in_bear_obs if cur >= o['low']  and cur <= o['high'] * 1.02), None)
    if near_bull_ob: bs += 3
    if near_bear_ob: ss += 3

    near_bull_fvg = next((f for f in active_fvgs if f['type'] == 'bull' and cur <= f['top']    and cur >= f['bottom'] * 0.99), None)
    near_bear_fvg = next((f for f in active_fvgs if f['type'] == 'bear' and cur >= f['bottom'] and cur <= f['top']    * 1.01), None)
    if near_bull_fvg: bs += 2
    if near_bear_fvg: ss += 2

    direction = 'LONG' if bs > ss else 'SHORT' if ss > bs else None
    base = {'dir': direction, 'bs': bs, 'ss': ss,
            'in_premium': in_premium, 'in_discount': in_discount, 'in_equilibrium': in_equilibrium,
            'last_sw': last_sw, 'last_in': last_in, 'entry_ob': None, 'entry': None}
    if not direction or abs(bs - ss) < 2:
        return base

    entry_ob = (near_bull_ob or (sw_bull_obs[-1] if sw_bull_obs else None) or (in_bull_obs[-1] if in_bull_obs else None)) \
               if direction == 'LONG' else \
               (near_bear_ob or (sw_bear_obs[-1] if sw_bear_obs else None) or (in_bear_obs[-1] if in_bear_obs else None))
    if not entry_ob:
        return base

    if direction == 'LONG':
        entry = entry_ob['low']  + (entry_ob['high'] - entry_ob['low']) * 0.3
        sl    = entry_ob['low']  * 0.995
        tp    = entry + (entry - sl) * 2.5
    else:
        entry = entry_ob['high'] - (entry_ob['high'] - entry_ob['low']) * 0.3
        sl    = entry_ob['high'] * 1.005
        tp    = entry - (sl - entry) * 2.5

    rr = abs(tp - entry) / abs(entry - sl)
    return {**base, 'entry': entry, 'sl': sl, 'tp': tp, 'rr': rr, 'entry_ob': entry_ob}


# ─────────────────────────────────────────────────────────────
# 位移強度 & 殺戮區
# ─────────────────────────────────────────────────────────────
def calc_displacement(candles, atrs):
    n = len(candles)
    max_str, strong_idx = 0.0, -1
    for i in range(max(0, n-12), n):
        body = abs(candles[i]['c'] - candles[i]['o'])
        s = body / (atrs[i] or 1)
        if s > max_str:
            max_str = s
            strong_idx = i
    return {'strength': max_str, 'idx': strong_idx, 'strong': max_str > 1.5}


def get_kill_zone():
    now = datetime.now(timezone.utc)
    utc_min = now.hour * 60 + now.minute
    if 420 <= utc_min < 600:  return {'name': '倫敦時段開盤', 'active': True}
    if 810 <= utc_min < 960:  return {'name': '紐約時段開盤', 'active': True}
    if 0   <= utc_min < 180:  return {'name': '亞洲時段',    'active': True}
    return {'name': '非活躍時段', 'active': False}


# ─────────────────────────────────────────────────────────────
# 策略偵測 (A / B / C)
# ─────────────────────────────────────────────────────────────
def detect_strategy(htf_candles, htf_analysis, mtf_candles, mtf_analysis, ltf_candles, ltf_analysis, plan, tfs):
    swing    = htf_analysis['swing']
    internal = htf_analysis['internal']
    fvgs     = htf_analysis['fvgs']
    atrs     = htf_analysis['atrs']
    cur      = htf_candles[-1]['c']
    active_fvgs = [f for f in fvgs if not f['mitigated']]
    disp     = calc_displacement(htf_candles, atrs)
    kill     = get_kill_zone()
    strategies = []

    # ── 策略 A：MTF EQH/EQL 識別 + LTF CHoCH 確認 ──
    last_eqh = mtf_analysis['eqh'][-1] if mtf_analysis['eqh'] else None
    last_eql = mtf_analysis['eql'][-1] if mtf_analysis['eql'] else None
    if last_eqh or last_eql:
        recent_mtf = mtf_candles[-12:]
        swept_eqh  = bool(last_eqh and any(c['h'] > last_eqh['price'] for c in recent_mtf) and cur < last_eqh['price'])
        swept_eql  = bool(last_eql and any(c['l'] < last_eql['price'] for c in recent_mtf) and cur > last_eql['price'])
        ltf_choch  = any(s['type'] == 'CHoCH' for s in ltf_analysis['internal']['structures'][-4:])
        direction  = 'LONG' if swept_eql else 'SHORT' if swept_eqh else None

        match = 'perfect' if (swept_eqh or swept_eql) and ltf_choch else \
                'partial'  if (swept_eqh or swept_eql) or ltf_choch else 'watch'

        strategies.append({
            'id': 'A', 'name': '流動性掃蕩+反轉', 'match': match, 'dir': direction,
            'swept_eqh': swept_eqh, 'swept_eql': swept_eql, 'ltf_choch': ltf_choch,
            'last_eqh': last_eqh, 'last_eql': last_eql,
            'entry': plan.get('entry'), 'sl': plan.get('sl'), 'tp': plan.get('tp'), 'rr': plan.get('rr'),
        })

    # ── 策略 B：HTF FVG 識別 + MTF 方向確認 ──
    pullback_fvgs = [f for f in active_fvgs if
                     (f['type'] == 'bull' and cur > f['bottom']) or (f['type'] == 'bear' and cur < f['top'])]
    if pullback_fvgs:
        top_fvg   = pullback_fvgs[-1]
        ce        = (top_fvg['top'] + top_fvg['bottom']) / 2
        dist_pct  = abs(cur - ce) / cur * 100
        mtf_aligned = (top_fvg['type'] == 'bull' and mtf_analysis['swing']['trend_bias'] == BULL) or \
                      (top_fvg['type'] == 'bear' and mtf_analysis['swing']['trend_bias'] == BEAR)
        match = 'perfect' if dist_pct < 1.5 else 'partial' if dist_pct < 4 else 'watch'
        sl_price  = top_fvg['bottom'] * 0.998 if top_fvg['type'] == 'bull' else top_fvg['top'] * 1.002
        # TP: 與 index.html 一致 — 用結構高低點（而非主計畫TP，主計畫方向可能與FVG方向相反）
        tr_high = htf_analysis.get('tr_high', ce + abs(ce - sl_price) * 3)
        tr_low  = htf_analysis.get('tr_low',  ce - abs(ce - sl_price) * 3)
        tp_price  = tr_high if top_fvg['type'] == 'bull' else tr_low
        rr        = abs(tp_price - ce) / abs(ce - sl_price) if sl_price and tp_price else None

        strategies.append({
            'id': 'B', 'name': '大時區FVG填充', 'match': match,
            'dir': 'LONG' if top_fvg['type'] == 'bull' else 'SHORT',
            'fvg': top_fvg, 'ce': ce, 'dist_pct': dist_pct, 'mtf_aligned': mtf_aligned,
            'entry': ce, 'sl': sl_price, 'tp': tp_price, 'rr': rr,
        })

    # ── 策略 C：HTF 環境判斷 + LTF 精確進場 ──
    in_zone        = plan.get('in_premium') or plan.get('in_discount')
    sw_in_aligned  = swing['trend_bias'] != 0 and swing['trend_bias'] == internal['trend_bias']
    near_any_poi   = bool(plan.get('entry_ob')) or any(
        cur >= f['bottom'] * 0.99 and cur <= f['top'] * 1.01 for f in active_fvgs
    )
    ltf_chochs = [s for s in ltf_analysis['internal']['structures'][-4:] if s['type'] == 'CHoCH']
    ltf_last_choch = ltf_chochs[-1] if ltf_chochs else None

    if in_zone or sw_in_aligned:
        direction   = 'LONG' if plan.get('in_discount') else 'SHORT' if plan.get('in_premium') else plan.get('dir')
        ltf_confirm = bool(ltf_last_choch) and (not direction or
            (direction == 'LONG'  and ltf_last_choch['dir'] == 'bull') or
            (direction == 'SHORT' and ltf_last_choch['dir'] == 'bear'))
        match = 'perfect' if in_zone and sw_in_aligned and near_any_poi and ltf_confirm else \
                'partial'  if in_zone and (sw_in_aligned or near_any_poi) else 'watch'

        strategies.append({
            'id': 'C', 'name': '多時區共振', 'match': match, 'dir': direction,
            'in_zone': in_zone, 'sw_in_aligned': sw_in_aligned,
            'near_any_poi': near_any_poi, 'ltf_confirm': ltf_confirm,
            'entry': plan.get('entry'), 'sl': plan.get('sl'), 'tp': plan.get('tp'), 'rr': plan.get('rr'),
        })

    return strategies, disp, kill
