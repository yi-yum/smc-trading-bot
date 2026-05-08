"""
Triple Supertrend Signal Bot — 主程式
策略：三條全綠進場，任一翻紅+低於進場價止損 / 全紅退場
基礎設施（Binance / LINE / tracker）沿用原架構
"""
import time
import traceback
from datetime import datetime, timezone

import config
import triple_st
import binance_client as bc
import line_notify as ln
import tracker

# 記錄每個幣種上次處理的 K棒時間，避免重複觸發
_last_candle_time: dict = {}

# 目前持倉中的交易 {symbol: trade_id}
_active_trades: dict = {}


def _load_active_trades():
    """從 trades.csv 還原 open 狀態的持倉，防止重啟後重複開單"""
    open_trades = tracker.get_open_trades()
    for t in open_trades:
        _active_trades[t['symbol']] = t['trade_id']
    if _active_trades:
        print(f"[啟動] 還原 {len(_active_trades)} 筆持倉: {list(_active_trades.keys())}")


def _is_new_candle(symbol: str, candles: list) -> bool:
    """只在新 K棒收盤後才觸發分析（用倒數第二根，已確定收盤）"""
    if not candles or len(candles) < 2:
        return False
    latest_t = candles[-2]['t']
    if _last_candle_time.get(symbol) == latest_t:
        return False
    _last_candle_time[symbol] = latest_t
    return True


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ─────────────────────────────────────────────────────────────
# 監控持倉 TP / SL（Triple ST：動態出場，每次掃描重新計算）
# ─────────────────────────────────────────────────────────────
def check_open_trades():
    open_trades = tracker.get_open_trades()
    for trade in open_trades:
        symbol      = trade['symbol']
        entry_price = float(trade['entry_price'])
        direction   = trade['direction']
        try:
            candles = bc.fetch_candles(symbol, config.ST_TIMEFRAME, config.CANDLE_LIMIT)
            if not candles:
                continue

            state = triple_st.analyze(candles)
            exit_now, reason = triple_st.should_exit(state, entry_price)

            dir_icons = ['🟢' if d == -1 else '🔴' for d in state['directions']]
            print(f"  [{symbol}] 持倉檢查 ST={dir_icons} cur={state['cur_price']:.2f} entry={entry_price:.2f}")

            if exit_now:
                cur_price = bc.get_price(symbol)
                qty       = float(trade['qty'])
                pnl       = (cur_price - entry_price) * qty if direction == 'LONG' \
                            else (entry_price - cur_price) * qty
                result    = 'win' if pnl > 0 else 'loss'

                tracker.close_trade(trade['trade_id'], cur_price, result)
                bc.cancel_all_orders(symbol)

                stats = tracker.get_stats()
                ln.notify_exit(symbol, direction, entry_price, cur_price, pnl, pnl > 0, stats)
                ln.send(f"📌 出場原因：{reason}")

                if symbol in _active_trades:
                    del _active_trades[symbol]

                print(f"  [{symbol}] 平倉: {result} @ {cur_price:.2f}  PNL={pnl:+.2f}  原因={reason}")

        except Exception as e:
            print(f"[{_now()}] check_open_trades({symbol}) error: {e}")


# ─────────────────────────────────────────────────────────────
# 分析單一幣種
# ─────────────────────────────────────────────────────────────
def analyze_symbol(symbol: str):
    candles = bc.fetch_candles(symbol, config.ST_TIMEFRAME, config.CANDLE_LIMIT)
    if not candles:
        return

    if not _is_new_candle(symbol, candles):
        return

    state     = triple_st.analyze(candles)
    dir_icons = ['🟢' if d == -1 else '🔴' for d in state['directions']]
    print(f"[{_now()}] {symbol} {config.ST_TIMEFRAME.upper()}  ST={dir_icons}  "
          f"all_green={state['all_green']}  price={state['cur_price']:.2f}")

    # ── 進場 ──────────────────────────────────────────────────
    at_limit = config.MAX_OPEN_TRADES > 0 and len(_active_trades) >= config.MAX_OPEN_TRADES

    if triple_st.should_enter(state) and symbol not in _active_trades and not at_limit:
        side = 'BUY'  # 策略為純做多
        bc.set_leverage(symbol, config.LEVERAGE)
        order, actual_price, qty = bc.place_market_order(symbol, side, config.POSITION_USDT)

        if order and actual_price and qty:
            trade_id = tracker.add_trade(
                symbol, 'TST', 'LONG', actual_price,
                sl=0, tp=0, qty=qty,
                order_id=order.get('orderId', '')
            )
            _active_trades[symbol] = trade_id
            ln.notify_st_entry(symbol, actual_price, state, qty,
                               order.get('orderId', ''), config.ST_TIMEFRAME)
            print(f"  ✅ 進場 LONG @ {actual_price:.2f}  qty={qty}")
        else:
            print(f"  ❌ 下單失敗")

    # ── 未持倉但出現出場信號（非全綠）→ 僅通知觀察 ──────────────
    elif symbol not in _active_trades and state['any_red']:
        count_red = sum(1 for d in state['directions'] if d == 1)
        print(f"  ⚠ 非全綠，{count_red}/3 條看空，等待進場")


# ─────────────────────────────────────────────────────────────
# 主迴圈
# ─────────────────────────────────────────────────────────────
def main():
    print(f"[{_now()}] Triple Supertrend Bot 啟動")
    print(f"  時框={config.ST_TIMEFRAME.upper()}  幣種={config.SYMBOLS}")
    print(f"  倉位={config.POSITION_USDT}U  槓桿={config.LEVERAGE}x  "
          f"最多持倉={config.MAX_OPEN_TRADES}  Testnet={config.BINANCE_TESTNET}")

    _load_active_trades()
    ln.notify_startup(config.SYMBOLS, 'Triple Supertrend', config.ST_TIMEFRAME, config.BINANCE_TESTNET)

    last_daily_date = None

    while True:
        now_utc = datetime.now(timezone.utc)

        # 每日 00:05 UTC 發統計報告
        if now_utc.hour == 0 and now_utc.minute < 10 and last_daily_date != now_utc.date():
            try:
                stats = tracker.get_stats()
                ln.notify_daily_summary(stats)
                last_daily_date = now_utc.date()
            except Exception as e:
                print(f"[{_now()}] daily summary error: {e}")

        # 檢查持倉出場條件
        try:
            check_open_trades()
        except Exception as e:
            print(f"[{_now()}] check_open_trades error: {e}")

        # 掃描所有幣種尋找進場機會
        for symbol in config.SYMBOLS:
            try:
                analyze_symbol(symbol)
            except Exception as e:
                print(f"[{_now()}] analyze_symbol({symbol}) error: {e}")
                traceback.print_exc()
                ln.notify_error(f"{symbol}: {e}")

        print(f"[{_now()}] 等待下次掃描 ({config.SCAN_INTERVAL_SECONDS}s)...")
        time.sleep(config.SCAN_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
