"""
LINE Messaging API 通知模組
(LINE Notify 已於 2025/03/31 停止服務，改用 Messaging API)
"""
import requests
from datetime import datetime
import config


def _fmt(p) -> str:
    if p is None:
        return 'N/A'
    if p >= 10000:
        return f"{p:,.0f}"
    if p >= 100:
        return f"{p:.1f}"
    return f"{p:.4f}"


def send(message: str):
    """發送 LINE 訊息，無 token 時只印出 log"""
    if not config.LINE_TOKEN or not config.LINE_USER_ID:
        print(f"[LINE] {message}")
        return
    try:
        requests.post(
            'https://api.line.me/v2/bot/message/push',
            headers={
                'Authorization': f'Bearer {config.LINE_TOKEN}',
                'Content-Type': 'application/json',
            },
            json={
                'to': config.LINE_USER_ID,
                'messages': [{'type': 'text', 'text': message.strip()}],
            },
            timeout=10
        )
    except Exception as e:
        print(f"[LINE] 發送失敗: {e}")


# ─────────────────────────────────────────────────────────────
# 各類型通知
# ─────────────────────────────────────────────────────────────
def notify_startup(symbols, strategy, primary_tf, testnet):
    mode = '🧪 Testnet 模擬' if testnet else '🔴 真實交易'
    send(f"""
🤖 SMC Signal Bot 啟動
策略: {strategy} | 主時框: {primary_tf.upper()}
監控: {', '.join(s.replace('USDT','') for s in symbols)}
模式: {mode}
時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}""")


def notify_signal(symbol, strategy, tfs, kill_zone, disp):
    """偵測到信號時通知 (partial / watch 等)"""
    sym = symbol.replace('USDT', '')
    s   = strategy
    match_map = {'perfect': '✅ 條件完整', 'partial': '⚠ 部分符合', 'watch': '👁 觀察中'}
    dir_emoji  = {'LONG': '🟢', 'SHORT': '🔴'}.get(s.get('dir'), '⚪')
    kz_emoji   = '🟢' if kill_zone['active'] else '🔴'
    disp_str   = f"{disp['strength']:.1f}x ATR {'✅' if disp['strong'] else '⚠'}"

    entry = s.get('entry')
    sl    = s.get('sl')
    tp    = s.get('tp')
    rr    = s.get('rr')

    send(f"""
{dir_emoji} [信號] {sym} 策略{s['id']} — {s['name']}
狀態: {match_map.get(s['match'], s['match'])}
時框: {tfs['htf'].upper()}/{tfs['mtf'].upper()}/{tfs['ltf'].upper()}
方向: {s.get('dir') or '觀察中'}
進場: ${_fmt(entry)}  止損: ${_fmt(sl)}  目標: ${_fmt(tp)}
RR: 1:{f"{rr:.1f}" if rr else "N/A"}
殺戮區: {kz_emoji} {kill_zone['name']}
位移強度: {disp_str}""")


def notify_entry(symbol, strategy_id, direction, entry_price, sl, tp, rr, qty, order_id, tfs):
    """下單成功時通知"""
    sym      = symbol.replace('USDT', '')
    emoji    = '🟢' if direction == 'LONG' else '🔴'
    sl_pct   = abs(entry_price - sl) / entry_price * 100
    tp_pct   = abs(tp - entry_price) / entry_price * 100

    send(f"""
{emoji} [進場成功] {sym} {direction}
策略 {strategy_id} | {tfs['htf'].upper()}/{tfs['mtf'].upper()}/{tfs['ltf'].upper()}
進場: ${_fmt(entry_price)}
止損: ${_fmt(sl)}  (-{sl_pct:.2f}%)
目標: ${_fmt(tp)}  (+{tp_pct:.2f}%)
RR: 1:{rr:.1f}
數量: {qty} {sym}
訂單: #{order_id}""")


def notify_exit(symbol, direction, entry_price, exit_price, pnl, is_win, stats):
    """平倉時通知 (含累計統計)"""
    sym    = symbol.replace('USDT', '')
    emoji  = '✅' if is_win else '❌'
    label  = '獲利' if is_win else '止損'
    sign   = '+' if pnl >= 0 else ''
    pnl_pct = pnl / (entry_price * 0.001) * 100 if entry_price else 0  # rough

    total_sign = '+' if stats['total_pnl'] >= 0 else ''

    send(f"""
{emoji} [{label}] {sym} {direction}
進場: ${_fmt(entry_price)} → 出場: ${_fmt(exit_price)}
損益: {sign}${pnl:.2f}
────────────────
📊 累計統計
勝: {stats['wins']} | 敗: {stats['losses']} | 勝率: {stats['win_rate']:.0f}%
總損益: {total_sign}${stats['total_pnl']:.2f}""")


def notify_daily_summary(stats):
    """每日定時統計報告"""
    sign = '+' if stats['total_pnl'] >= 0 else ''
    send(f"""
📈 每日統計報告  {datetime.now().strftime('%Y-%m-%d')}
────────────────
總交易: {stats['total']}
勝: {stats['wins']} | 敗: {stats['losses']}
勝率: {stats['win_rate']:.1f}%
總損益: {sign}${stats['total_pnl']:.2f}""")


def notify_error(msg: str):
    send(f"\n⚠ [Bot 錯誤]\n{msg}")
