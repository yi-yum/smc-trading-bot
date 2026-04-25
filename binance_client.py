"""
幣安 API 封裝 — 支援 Testnet 和 真實 Futures
"""
import requests
import hashlib
import hmac
import time
from urllib.parse import urlencode
import config

_BASE_TESTNET = 'https://testnet.binancefuture.com'
_BASE_LIVE    = 'https://fapi.binance.com'


def _base() -> str:
    return _BASE_TESTNET if config.BINANCE_TESTNET else _BASE_LIVE


def _sign(params: dict) -> str:
    return hmac.new(
        config.BINANCE_SECRET.encode('utf-8'),
        urlencode(params).encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def _headers() -> dict:
    return {'X-MBX-APIKEY': config.BINANCE_API_KEY}


# ─────────────────────────────────────────────────────────────
# 公開端點 (不需要簽名)
# ─────────────────────────────────────────────────────────────
def fetch_candles(symbol: str, interval: str, limit: int = 200):
    """抓取 K 棒資料，回傳統一格式的 list"""
    url = f"{_base()}/fapi/v1/klines"
    r = requests.get(url, params={'symbol': symbol, 'interval': interval, 'limit': limit}, timeout=15)
    r.raise_for_status()
    return [
        {'t': d[0], 'o': float(d[1]), 'h': float(d[2]), 'l': float(d[3]), 'c': float(d[4]), 'v': float(d[5])}
        for d in r.json()
    ]


def get_price(symbol: str) -> float:
    """取得最新標記價格"""
    url = f"{_base()}/fapi/v1/ticker/price"
    r = requests.get(url, params={'symbol': symbol}, timeout=5)
    r.raise_for_status()
    return float(r.json()['price'])


def get_symbol_precision(symbol: str) -> int:
    """取得幣種的數量精度"""
    url = f"{_base()}/fapi/v1/exchangeInfo"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    for s in r.json()['symbols']:
        if s['symbol'] == symbol:
            return int(s['quantityPrecision'])
    return 3


# ─────────────────────────────────────────────────────────────
# 私有端點 (需要簽名)
# ─────────────────────────────────────────────────────────────
def _signed_request(method: str, path: str, params: dict = None):
    params = params or {}
    params['timestamp'] = int(time.time() * 1000)
    params['signature'] = _sign(params)
    url = f"{_base()}{path}"
    if method == 'GET':
        r = requests.get(url, params=params, headers=_headers(), timeout=15)
    elif method == 'POST':
        r = requests.post(url, params=params, headers=_headers(), timeout=15)
    elif method == 'DELETE':
        r = requests.delete(url, params=params, headers=_headers(), timeout=15)
    else:
        raise ValueError(f"Unknown method: {method}")
    r.raise_for_status()
    return r.json()


def get_balance() -> float:
    """取得 USDT 餘額"""
    data = _signed_request('GET', '/fapi/v2/balance')
    for b in data:
        if b['asset'] == 'USDT':
            return float(b['balance'])
    return 0.0


def get_open_positions():
    """取得目前持倉"""
    data = _signed_request('GET', '/fapi/v2/positionRisk')
    return [p for p in data if float(p['positionAmt']) != 0]


def set_leverage(symbol: str, leverage: int):
    """設定槓桿倍數"""
    try:
        _signed_request('POST', '/fapi/v1/leverage', {
            'symbol': symbol,
            'leverage': leverage,
        })
    except Exception as e:
        print(f"[Binance] set_leverage error: {e}")


def place_market_order(symbol: str, side: str, usdt_amount: float):
    """
    下市價單
    side: 'BUY' (做多) 或 'SELL' (做空)
    回傳: (order_dict, entry_price, qty) 或 (None, None, None)
    """
    try:
        price     = get_price(symbol)
        precision = get_symbol_precision(symbol)
        qty       = round(usdt_amount / price, precision)
        if qty <= 0:
            raise ValueError(f"Quantity too small: {qty}")

        order = _signed_request('POST', '/fapi/v1/order', {
            'symbol':   symbol,
            'side':     side,
            'type':     'MARKET',
            'quantity': qty,
        })
        actual_price = float(order.get('avgPrice') or price)
        return order, actual_price, qty
    except Exception as e:
        print(f"[Binance] place_market_order error: {e}")
        return None, None, None


def place_tp_sl(symbol: str, side: str, qty: float, tp_price: float, sl_price: float):
    """下 TP 和 SL 掛單"""
    close_side = 'SELL' if side == 'BUY' else 'BUY'
    results = {}

    try:
        results['tp'] = _signed_request('POST', '/fapi/v1/order', {
            'symbol':      symbol,
            'side':        close_side,
            'type':        'TAKE_PROFIT_MARKET',
            'stopPrice':   round(tp_price, 2),
            'quantity':    qty,
            'reduceOnly':  'true',
            'timeInForce': 'GTE_GTC',
        })
    except Exception as e:
        print(f"[Binance] TP order error: {e}")

    try:
        results['sl'] = _signed_request('POST', '/fapi/v1/order', {
            'symbol':      symbol,
            'side':        close_side,
            'type':        'STOP_MARKET',
            'stopPrice':   round(sl_price, 2),
            'quantity':    qty,
            'reduceOnly':  'true',
            'timeInForce': 'GTE_GTC',
        })
    except Exception as e:
        print(f"[Binance] SL order error: {e}")

    return results


def cancel_all_orders(symbol: str):
    """取消某幣種的所有掛單"""
    try:
        _signed_request('DELETE', '/fapi/v1/allOpenOrders', {'symbol': symbol})
    except Exception as e:
        print(f"[Binance] cancel_all_orders error: {e}")
