import os
from typing import List, Optional

# ====== 你的伺服器/模板設定 ======
GUILD_ID: int = 626378673523785731                     # 伺服器
TEMPLATE_CATEGORY_ID: int = 1417446665626849343        # 模板 Category
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519 # 可選；用作複製 forum tags

CATEGORY_NAME_PATTERN = "{game}"   # 新分區命名
ROLE_NAME_PATTERN = "{game}"       # 新角色命名
ADMIN_ROLE_IDS: List[int] = []      # 額外管理角色（可留空）

# 後備頻道（當模板無該類型時會建立）
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],
    "forum": "分區討論區",
    "voice": ["小隊Call 1", "小隊Call 2"],
}

# 臨時語音房設定
VERIFIED_ROLE_ID: int = 1279040517451022419   # 擁有此角色即可用 /vc_new、/vc_teardown、/tu
TEMP_VC_EMPTY_SECONDS: int = 120              # 無人時自動刪除的等待秒數
TEMP_VC_PREFIX: str = "Temp • "               # 自動命名前綴

# 歡迎訊息發送位置（請換成你嘅頻道 ID）
WELCOME_CHANNEL_ID: int = 1010456227769229355  # 歡迎訊息要發送嘅頻道
RULES_CHANNEL_ID: int   = 1278976821710426133 # #rules
GUIDE_CHANNEL_ID: int   = 1279074807685578885 # #教學
SUPPORT_CHANNEL_ID: int = 1362781427287986407 # #支援

# Logging 目的地
LOG_CHANNEL_ID: int = 1401346745346297966

# Token（Fly.io 以環境變數注入）
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
