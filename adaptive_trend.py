"""
AdaptiveTrend — 月度資產篩選模組
計畫書 §投資組合構建與資產篩選模組 的實作：

1. 透過 CoinGecko API 取得市值排名
2. 過濾出 Binance 期貨可交易對
3. 以過去 30 天 H6 夏普比率篩選多/空備選池
4. 輸出當月可交易的 long_symbols / short_symbols

月度觸發：每月 1 日 00:05 UTC 由 main.py 呼叫 refresh_monthly_assets()
"""
import math
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

import config

# ── 當月資產清單 (由 refresh_monthly_assets 更新) ──
_monthly_long:  List[str] = []
_monthly_short: List[str] = []
_last_refresh_month: Optional[int] = None   # 1~12


# ─────────────────────────────────────────────────────────────
# CoinGecko：市值排名
# ─────────────────────────────────────────────────────────────
_COINGECKO_URL = 'https://api.coingecko.com/api/v3/coins/markets'

def get_coingecko_top(n: int = 250) -> List[Dict]:
    """
    取得市值前 n 名的代幣資料。
    回傳: [{'symbol': 'BTC', 'market_cap_rank': 1, ...}, ...]
    """
    coins = []
    per_page = 100
    pages = math.ceil(n / per_page)
    for page in range(1, pages + 1):
        try:
            r = requests.get(
                _COINGECKO_URL,
                params={
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': per_page,
                    'page': page,
                    'sparkline': 'false',
                },
                timeout=20,
            )
            r.raise_for_status()
            coins.extend(r.json())
            time.sleep(1.2)   # CoinGecko 免費版速率限制
        except Exception as e:
            print(f"[AdaptiveTrend] CoinGecko page {page} 失敗: {e}")
    return coins[:n]


# ─────────────────────────────────────────────────────────────
# Binance 期貨：可交易對
# ─────────────────────────────────────────────────────────────
_BINANCE_BASE = 'https://fapi.binance.com' if not config.BINANCE_TESTNET \
                else 'https://testnet.binancefuture.com'

def get_binance_futures_symbols() -> List[str]:
    """回傳目前 Binance 期貨所有可交易的 USDT 永續合約 symbol，例如 ['BTCUSDT', ...]"""
    try:
        r = requests.get(f'{_BINANCE_BASE}/fapi/v1/exchangeInfo', timeout=20)
        r.raise_for_status()
        return [
            s['symbol'] for s in r.json()['symbols']
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING'
               and s['contractType'] == 'PERPETUAL'
        ]
    except Exception as e:
        print(f"[AdaptiveTrend] Binance exchangeInfo 失敗: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# 夏普比率計算
# ─────────────────────────────────────────────────────────────
def calc_sharpe(prices: List[float], rf_annual: float = 0.045) -> float:
    """
    從 H6 收盤價序列計算年化夏普比率。
    annualization factor = sqrt(365 * 4) ≈ 38.16 (每天4根H6)
    """
    if len(prices) < 2:
        return 0.0
    returns = [(prices[i] - prices[i-1]) / prices[i-1]
               for i in range(1, len(prices)) if prices[i-1] != 0]
    if not returns:
        return 0.0
    n    = len(returns)
    mean = sum(returns) / n
    var  = sum((r - mean) ** 2 for r in returns) / n
    std  = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    ann_factor = math.sqrt(365 * 4)   # H6 年化
    rf_per_bar = rf_annual / (365 * 4)
    return (mean - rf_per_bar) / std * ann_factor


# ─────────────────────────────────────────────────────────────
# H6 歷史資料（直接呼叫 Binance，30天=120根）
# ─────────────────────────────────────────────────────────────
def _fetch_h6_closes(symbol: str, limit: int = 120) -> List[float]:
    """取得 H6 收盤價列表，用於計算夏普比率"""
    try:
        r = requests.get(
            f'{_BINANCE_BASE}/fapi/v1/klines',
            params={'symbol': symbol, 'interval': '6h', 'limit': limit},
            timeout=15,
        )
        r.raise_for_status()
        return [float(k[4]) for k in r.json()]
    except Exception as e:
        print(f"[AdaptiveTrend] 抓取 {symbol} H6 失敗: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# 月度資產篩選主函數
# ─────────────────────────────────────────────────────────────
def select_monthly_assets(
    long_n:             int   = 15,
    short_n:            int   = 15,
    min_sharpe_long:    float = None,
    min_sharpe_short:   float = None,
) -> Tuple[List[str], List[str]]:
    """
    計畫書兩階段篩選：
    階段一：市值排名前 long_n / 後 short_n 建立備選池
    階段二：計算過去 30 天 H6 夏普比率，低於門檻的剔除

    回傳 (long_symbols, short_symbols) — Binance 格式，如 'BTCUSDT'
    """
    min_sl = min_sharpe_long  if min_sharpe_long  is not None else config.AT_MIN_SHARPE_LONG
    min_ss = min_sharpe_short if min_sharpe_short is not None else config.AT_MIN_SHARPE_SHORT

    print('[AdaptiveTrend] 開始月度資產篩選...')

    # 取 Binance 期貨可交易對
    futures_symbols = set(get_binance_futures_symbols())
    if not futures_symbols:
        print('[AdaptiveTrend] 無法取得 Binance 期貨對，跳過篩選')
        return [], []

    # 取 CoinGecko 市值排名 Top 250
    top_coins = get_coingecko_top(250)
    if not top_coins:
        print('[AdaptiveTrend] 無法取得 CoinGecko 資料，跳過篩選')
        return [], []

    # 對應 CoinGecko symbol → Binance USDT 期貨 symbol
    tradeable = []
    for coin in top_coins:
        sym = coin.get('symbol', '').upper() + 'USDT'
        if sym in futures_symbols:
            tradeable.append({'symbol': sym, 'rank': coin.get('market_cap_rank', 9999)})

    tradeable.sort(key=lambda x: x['rank'])

    # 多頭備選池：市值前 long_n
    long_candidates  = [c['symbol'] for c in tradeable[:long_n]]
    # 空頭備選池：市值後 short_n（在期貨宇宙內）
    short_candidates = [c['symbol'] for c in tradeable[-short_n:]]

    print(f'[AdaptiveTrend] 多頭備選: {long_candidates}')
    print(f'[AdaptiveTrend] 空頭備選: {short_candidates}')

    # 階段二：Sharpe 篩選
    def sharpe_filter(candidates: List[str], min_sharpe: float) -> List[str]:
        passed = []
        for sym in candidates:
            closes = _fetch_h6_closes(sym, 120)
            sr = calc_sharpe(closes)
            print(f'  {sym}: Sharpe={sr:.2f} (門檻={min_sharpe})')
            if sr >= min_sharpe:
                passed.append(sym)
            time.sleep(0.3)   # 避免 rate limit
        return passed

    long_symbols  = sharpe_filter(long_candidates,  min_sl)
    short_symbols = sharpe_filter(short_candidates, min_ss)

    print(f'[AdaptiveTrend] 篩選結果 — 多頭: {long_symbols}')
    print(f'[AdaptiveTrend] 篩選結果 — 空頭: {short_symbols}')
    return long_symbols, short_symbols


# ─────────────────────────────────────────────────────────────
# 月度刷新入口（由 main.py 呼叫）
# ─────────────────────────────────────────────────────────────
def refresh_monthly_assets():
    """
    更新當月多/空標的清單，並回傳合併後的所有監控幣種。
    main.py 每月 1 日 00:05 UTC 呼叫。
    """
    global _monthly_long, _monthly_short, _last_refresh_month
    month = datetime.now(timezone.utc).month
    if _last_refresh_month == month:
        print('[AdaptiveTrend] 本月已刷新，略過')
        return get_active_symbols()
    try:
        _monthly_long, _monthly_short = select_monthly_assets()
        _last_refresh_month = month
    except Exception as e:
        print(f'[AdaptiveTrend] refresh_monthly_assets 失敗: {e}')
    return get_active_symbols()


def get_active_symbols() -> List[str]:
    """回傳當月所有需監控的幣種（多頭 + 空頭去重）"""
    return list(dict.fromkeys(_monthly_long + _monthly_short))


def get_direction_hint(symbol: str) -> Optional[str]:
    """
    根據當月篩選結果給出方向提示：
    - 只在多頭池 → 偏多
    - 只在空頭池 → 偏空
    - 兩者都在 / 都不在 → None（不限制）
    """
    in_long  = symbol in _monthly_long
    in_short = symbol in _monthly_short
    if in_long and not in_short:
        return 'LONG'
    if in_short and not in_long:
        return 'SHORT'
    return None
