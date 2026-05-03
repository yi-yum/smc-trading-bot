"""
SMC Signal Bot — 主程式
自動掃描信號、下測試網單、LINE 通知、記錄勝率
"""
import time
import traceback
from datetime import datetime, timezone

import config
import smc_engine
import binance_client as bc
import line_notify as ln
import tracker
import adaptive_trend as at_module

# 記錄每個幣種上次處理的 HTF K棒時間，避免重複觸發
_last_candle_time: dict = {}

# 記錄目前持倉中的交易 {symbol: trade_id}
_active_trades: dict = {}


# ─────────────────────────────────────────────────────────────
# 輔助函數
# ─────────────────────────────────────────────────────────────
def _is_new_candle(symbol: str, htf_candles: list) -> bool:
    """只在新的 HTF K棒收盤後才觸發分析"""
    if not htf_candles:
        return False
    latest_t = htf_candles[-2]['t']  # 用倒數第二根 (已收盤的最新K棒)
    if _last_candle_time.get(symbol) == latest_t:
        return False
    _last_candle_time[symbol] = latest_t
    return True


def _should_enter(s: dict, kill: dict, disp: dict) -> bool:
    """判斷是否滿足下單門檻"""
    if s['match'] != 'perfect':
        return False
    if config.REQUIRE_KILL_ZONE and not kill['active']:
        return False
    if config.REQUIRE_STRONG_DISP and not disp['strong']:
        return False
    rr = s.get('rr') or 0
    if rr < config.MIN_RR:
        return False
    if not all([s.get('dir'), s.get('entry'), s.get('sl'), s.get('tp')]):
        return False
    return True


# ─────────────────────────────────────────────────────────────
# 監控持倉是否觸及 TP / SL
# ─────────────────────────────────────────────────────────────
def _close_trade_record(trade: dict, exit_price: float, is_win: bool):
    """共用的平倉記錄邏輯"""
    symbol = trade['symbol']
    dire   = trade['direction']
    entry  = float(trade['entry_price'])
    pnl    = (exit_price - entry) * float(trade['qty']) if dire == 'LONG' \
             else (entry - exit_price) * float(trade['qty'])
    result = 'win' if is_win else 'loss'
    tracker.close_trade(trade['trade_id'], exit_price, result)
    bc.cancel_all_orders(symbol)
    stats = tracker.get_stats()
    ln.notify_exit(symbol, dire, entry, exit_price, pnl, is_win, stats)
    if symbol in _active_trades:
        del _active_trades[symbol]
    print(f"[{_now()}] {symbol} 平倉: {result} @ {exit_price:.2f}  PNL={pnl:+.2f}")


def check_open_trades():
    open_trades = tracker.get_open_trades()
    for trade in open_trades:
        symbol = trade['symbol']
        try:
            cur   = bc.get_price(symbol)
            entry = float(trade['entry_price'])
            tp    = float(trade['tp'])
            sl_p  = float(trade['sl'])
            dire  = trade['direction']

            # ── Strategy D：用 ATR 追蹤止損取代靜態止損 ──
            if trade.get('strategy') == 'D' and config.AT_ENABLE:
                tfs = config.TF_MAP.get(config.PRIMARY_TF, config.TF_MAP['4h'])
                candles = bc.fetch_candles(symbol, tfs['htf'], config.CANDLE_LIMIT)
                if candles:
                    atr_stop = smc_engine.calc_atr_trailing_stop(
                        candles, config.AT_ATR_MULT, dire
                    )
                    hit_atr_stop = (dire == 'LONG'  and cur <= atr_stop) or \
                                   (dire == 'SHORT' and cur >= atr_stop)
                    hit_tp       = (dire == 'LONG'  and cur >= tp) or \
                                   (dire == 'SHORT' and cur <= tp)
                    if hit_tp or hit_atr_stop:
                        _close_trade_record(trade, cur, hit_tp)
                        print(f"  {'TP 達成' if hit_tp else f'ATR止損觸發 @ {atr_stop:.4f}'}")
                continue  # D 策略不走下方靜態邏輯

            # ── 其他策略：靜態 TP / SL ──
            hit_tp = (dire == 'LONG'  and cur >= tp) or (dire == 'SHORT' and cur <= tp)
            hit_sl = (dire == 'LONG'  and cur <= sl_p) or (dire == 'SHORT' and cur >= sl_p)

            if hit_tp or hit_sl:
                exit_price = tp if hit_tp else sl_p
                _close_trade_record(trade, exit_price, hit_tp)

        except Exception as e:
            print(f"[{_now()}] check_open_trades({symbol}) error: {e}")


# ─────────────────────────────────────────────────────────────
# 分析單一幣種
# ─────────────────────────────────────────────────────────────
def analyze_symbol(symbol: str):
    tfs = config.TF_MAP.get(config.PRIMARY_TF, config.TF_MAP['4h'])

    # 先只抓 HTF 判斷是否為新K棒，節省 API 呼叫
    htf_candles = bc.fetch_candles(symbol, tfs['htf'], config.CANDLE_LIMIT)
    if not _is_new_candle(symbol, htf_candles):
        return

    print(f"[{_now()}] 分析 {symbol}  {tfs['htf'].upper()}/{tfs['mtf'].upper()}/{tfs['ltf'].upper()}")

    # 平行抓三個時框 (依序呼叫，避免 rate limit)
    mtf_candles = bc.fetch_candles(symbol, tfs['mtf'], config.CANDLE_LIMIT)
    ltf_candles = bc.fetch_candles(symbol, tfs['ltf'], config.CANDLE_LIMIT)

    htf_analysis = smc_engine.smc_analyze(htf_candles)
    mtf_analysis = smc_engine.smc_analyze(mtf_candles)
    ltf_analysis = smc_engine.smc_analyze(ltf_candles)
    plan         = smc_engine.build_smc_plan(htf_candles, htf_analysis)

    # 若啟用 AdaptiveTrend，傳入 at_params 觸發 Strategy D
    at_params = None
    if config.AT_ENABLE:
        at_params = {
            'L':             config.AT_LOOKBACK_L,
            'theta':         config.AT_THETA_ENTRY,
            'alpha':         config.AT_ATR_MULT,
            'perfect_factor': config.AT_PERFECT_FACTOR,
        }

    strategies, disp, kill = smc_engine.detect_strategy(
        htf_candles, htf_analysis,
        mtf_candles, mtf_analysis,
        ltf_candles, ltf_analysis,
        plan, tfs,
        at_params=at_params,
    )

    active_strat = config.ACTIVE_STRATEGY  # 'A' / 'B' / 'C' / 'ALL'

    for s in strategies:
        # 篩選啟用的策略
        if active_strat != 'ALL' and s['id'] != active_strat:
            continue
        if s['match'] == 'watch':
            continue

        rr_display = f"{s['rr']:.1f}" if s.get('rr') else 'N/A'
        print(f"  策略{s['id']} match={s['match']} dir={s.get('dir')} rr={rr_display}")

        # 發送信號通知 (partial 和 perfect 都通知)
        ln.notify_signal(symbol, s, tfs, kill, disp)

        # 下單條件：perfect + 殺戮區 + 強位移 + 未有持倉
        if _should_enter(s, kill, disp) and symbol not in _active_trades:
            side  = 'BUY' if s['dir'] == 'LONG' else 'SELL'
            bc.set_leverage(symbol, config.LEVERAGE)
            order, actual_price, qty = bc.place_market_order(symbol, side, config.POSITION_USDT)

            if order and actual_price and qty:
                tp = s['tp']
                sl = s['sl']
                bc.place_tp_sl(symbol, side, qty, tp, sl)

                trade_id = tracker.add_trade(
                    symbol, s['id'], s['dir'], actual_price, sl, tp, qty,
                    order.get('orderId', '')
                )
                _active_trades[symbol] = trade_id

                ln.notify_entry(
                    symbol, s['id'], s['dir'], actual_price, sl, tp,
                    s['rr'], qty, order.get('orderId', ''), tfs
                )
                print(f"  ✅ 下單成功: {s['dir']} @ {actual_price:.2f}  qty={qty}  TP={tp:.2f}  SL={sl:.2f}")
            else:
                print(f"  ❌ 下單失敗")


# ─────────────────────────────────────────────────────────────
# 主迴圈
# ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def main():
    print(f"[{_now()}] SMC Signal Bot 啟動")
    print(f"  策略={config.ACTIVE_STRATEGY}  時框={config.PRIMARY_TF.upper()}")
    print(f"  幣種={config.SYMBOLS}  Testnet={config.BINANCE_TESTNET}")
    print(f"  需殺戮區={config.REQUIRE_KILL_ZONE}  需強位移={config.REQUIRE_STRONG_DISP}  最低RR={config.MIN_RR}")

    ln.notify_startup(config.SYMBOLS, config.ACTIVE_STRATEGY, config.PRIMARY_TF, config.BINANCE_TESTNET)

    last_daily_date   = None
    last_monthly_date = None

    # 若啟用 AdaptiveTrend，啟動時先執行月度篩選
    if config.AT_ENABLE:
        print(f"[{_now()}] AdaptiveTrend 已啟用，執行首次月度資產篩選...")
        try:
            at_symbols = at_module.refresh_monthly_assets()
            if at_symbols:
                # 將 AT 篩選出的幣種加入監控清單（不重複）
                for s in at_symbols:
                    if s not in config.SYMBOLS:
                        config.SYMBOLS.append(s)
                print(f"[{_now()}] AT 監控幣種: {at_symbols}")
        except Exception as e:
            print(f"[{_now()}] AT 初始篩選失敗: {e}")

    while True:
        now_utc = datetime.now(timezone.utc)

        # 每月 1 日 00:05 UTC 執行月度資產篩選 (AT_ENABLE)
        if config.AT_ENABLE and now_utc.day == 1 and now_utc.hour == 0 and \
                now_utc.minute < 10 and last_monthly_date != now_utc.date():
            try:
                at_symbols = at_module.refresh_monthly_assets()
                # 重建監控清單：原始 SMC 標的 + AT 篩選標的
                base = ['BTCUSDT', 'ETHUSDT']
                config.SYMBOLS = list(dict.fromkeys(base + at_symbols))
                last_monthly_date = now_utc.date()
                ln.send(f"[AdaptiveTrend] 月度篩選完成\n多頭: {at_module._monthly_long}\n空頭: {at_module._monthly_short}")
            except Exception as e:
                print(f"[{_now()}] AT monthly refresh error: {e}")

        # 每日 00:05 UTC 發統計報告
        if now_utc.hour == 0 and now_utc.minute < 10 and last_daily_date != now_utc.date():
            try:
                stats = tracker.get_stats()
                ln.notify_daily_summary(stats)
                last_daily_date = now_utc.date()
            except Exception as e:
                print(f"[{_now()}] daily summary error: {e}")

        # 檢查持倉 TP/SL
        try:
            check_open_trades()
        except Exception as e:
            print(f"[{_now()}] check_open_trades error: {e}")

        # 掃描所有幣種
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
