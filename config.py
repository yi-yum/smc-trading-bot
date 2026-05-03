import os

# ── 監控標的 ──
SYMBOLS = ['BTCUSDT', 'ETHUSDT']

# ── 主時框架 ──
PRIMARY_TF = os.environ.get('PRIMARY_TF', '4h')  # 可改: 15m / 1h / 4h / 1d

TF_MAP = {
    '15m': {'htf': '15m', 'mtf': '5m',  'ltf': '1m'},
    '1h':  {'htf': '1h',  'mtf': '15m', 'ltf': '5m'},
    '4h':  {'htf': '4h',  'mtf': '1h',  'ltf': '15m'},
    '6h':  {'htf': '6h',  'mtf': '1h',  'ltf': '15m'},  # AdaptiveTrend 核心時框
    '1d':  {'htf': '1d',  'mtf': '4h',  'ltf': '1h'},
}

# ── 策略設定 ── A / B / C / ALL
ACTIVE_STRATEGY = os.environ.get('ACTIVE_STRATEGY', 'A')

# ── 進場門檻：只在 perfect 且殺戮區且強位移時才下單 ──
REQUIRE_KILL_ZONE  = os.environ.get('REQUIRE_KILL_ZONE', 'false').lower() == 'true'
REQUIRE_STRONG_DISP = os.environ.get('REQUIRE_STRONG_DISP', 'true').lower() == 'true'
MIN_RR             = float(os.environ.get('MIN_RR', '1.5'))

# ── 每筆模擬倉位 (USDT) ──
POSITION_USDT = float(os.environ.get('POSITION_USDT', '100'))

# ── 最多同時持倉數量 (0 = 不限制，建議設 1~3) ──
MAX_OPEN_TRADES = int(os.environ.get('MAX_OPEN_TRADES', '1'))

# ── 槓桿倍數 (1~20，建議驗證期間用低槓桿) ──
LEVERAGE = int(os.environ.get('LEVERAGE', '3'))

CANDLE_LIMIT = 200

# ── API 金鑰 (從環境變數讀取，不要寫死在程式裡) ──
LINE_TOKEN       = os.environ.get('LINE_TOKEN', '')    # LINE Messaging API Channel Access Token
LINE_USER_ID     = os.environ.get('LINE_USER_ID', '')  # 你的 LINE User ID (格式: Uxxxxxxxxxx)
BINANCE_API_KEY  = os.environ.get('BINANCE_API_KEY', '')
BINANCE_SECRET   = os.environ.get('BINANCE_SECRET', '')
BINANCE_TESTNET  = os.environ.get('BINANCE_TESTNET', 'true').lower() == 'true'

# ── 掃描間隔：每小時掃一次，內部判斷 K 棒是否新收 ──
SCAN_INTERVAL_SECONDS = int(os.environ.get('SCAN_INTERVAL_SECONDS', '3600'))

TRADES_FILE = 'trades.csv'

# ── AdaptiveTrend 策略參數 ──
# 是否啟用 Strategy D (AdaptiveTrend 動量策略)
AT_ENABLE        = os.environ.get('AT_ENABLE', 'false').lower() == 'true'

# 動量回看週期 L (H6 K棒數，12~48 步長6，預設20根≈5天)
AT_LOOKBACK_L    = int(os.environ.get('AT_LOOKBACK_L', '20'))

# 動量進場閾值 θ_entry (0.01~0.05，超過此值才進場)
AT_THETA_ENTRY   = float(os.environ.get('AT_THETA_ENTRY', '0.02'))

# ATR 乘數 α (2.0~4.0，追蹤止損線距離)
AT_ATR_MULT      = float(os.environ.get('AT_ATR_MULT', '2.5'))

# 多頭資金比例 (70/30 架構)
AT_LONG_RATIO    = float(os.environ.get('AT_LONG_RATIO', '0.7'))

# Strategy D 進場判定：|MOM| 需超過 θ*perfect_factor 才為 perfect
AT_PERFECT_FACTOR = float(os.environ.get('AT_PERFECT_FACTOR', '1.8'))

# 月度資產篩選：多頭夏普比率門檻
AT_MIN_SHARPE_LONG  = float(os.environ.get('AT_MIN_SHARPE_LONG', '1.3'))

# 月度資產篩選：空頭夏普比率門檻 (更嚴格，因加密市場存在結構性上行偏誤)
AT_MIN_SHARPE_SHORT = float(os.environ.get('AT_MIN_SHARPE_SHORT', '1.7'))
