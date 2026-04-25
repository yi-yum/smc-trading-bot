"""
交易記錄與勝率統計
"""
import csv
import os
from datetime import datetime
import config

FIELDS = [
    'trade_id', 'symbol', 'strategy', 'direction',
    'entry_price', 'sl', 'tp', 'qty', 'order_id',
    'entry_time', 'exit_time', 'exit_price',
    'result', 'pnl', 'status'
]


def _ensure_file():
    if not os.path.exists(config.TRADES_FILE):
        with open(config.TRADES_FILE, 'w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def add_trade(symbol, strategy_id, direction, entry_price, sl, tp, qty, order_id) -> str:
    """新增一筆交易，回傳 trade_id"""
    _ensure_file()
    trade_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    row = {
        'trade_id': trade_id, 'symbol': symbol, 'strategy': strategy_id,
        'direction': direction, 'entry_price': entry_price, 'sl': sl, 'tp': tp,
        'qty': qty, 'order_id': order_id,
        'entry_time': datetime.now().isoformat(),
        'exit_time': '', 'exit_price': '', 'result': '', 'pnl': '',
        'status': 'open'
    }
    with open(config.TRADES_FILE, 'a', newline='', encoding='utf-8') as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
    return trade_id


def close_trade(trade_id, exit_price, result: str):
    """
    更新交易結果
    result: 'win' 或 'loss'
    """
    _ensure_file()
    rows = []
    with open(config.TRADES_FILE, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        if row['trade_id'] == trade_id:
            entry = float(row['entry_price'])
            qty   = float(row['qty'])
            pnl   = (exit_price - entry) * qty if row['direction'] == 'LONG' else (entry - exit_price) * qty
            row.update({
                'exit_time':  datetime.now().isoformat(),
                'exit_price': exit_price,
                'result':     result,
                'pnl':        round(pnl, 4),
                'status':     'closed',
            })
            break

    with open(config.TRADES_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def get_open_trades() -> list:
    _ensure_file()
    with open(config.TRADES_FILE, 'r', encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if r['status'] == 'open']


def get_stats() -> dict:
    _ensure_file()
    with open(config.TRADES_FILE, 'r', encoding='utf-8') as f:
        closed = [r for r in csv.DictReader(f) if r['status'] == 'closed']

    if not closed:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0, 'total_pnl': 0.0}

    wins      = sum(1 for r in closed if r['result'] == 'win')
    losses    = len(closed) - wins
    total_pnl = sum(float(r['pnl']) for r in closed if r['pnl'])
    return {
        'total':     len(closed),
        'wins':      wins,
        'losses':    losses,
        'win_rate':  wins / len(closed) * 100,
        'total_pnl': total_pnl,
    }
