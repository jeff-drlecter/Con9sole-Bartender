import os
from typing import List, Optional

# ====== 伺服器 / 模板設定 ======
GUILD_ID: int = 626378673523785731                     # 伺服器 ID
TEMPLATE_CATEGORY_ID: int = 1417446665626849343        # 模板 Category
TEMPLATE_FORUM_ID: Optional[int] = 1417446670526058519 # 可選；用作複製 forum tags

CATEGORY_NAME_PATTERN = "{game}"   # 新分區命名
ROLE_NAME_PATTERN = "{game}"       # 新角色命名
ADMIN_ROLE_IDS: List[int] = []      # 額外管理角色（可留空）

# 後備頻道
FALLBACK_CHANNELS = {
    "text": ["read-me", "活動（未有）"],
    "forum": "分區討論區",
    "voice": ["小隊Call 1", "小隊Call 2"],
}

# 臨時語音房設定
VERIFIED_ROLE_ID: int = 1279040517451022419   # 擁有此角色即可用 /vc_new、/vc_teardown、/tu
TEMP_VC_EMPTY_SECONDS: int = 120              # 無人時自動刪除的等待秒數
TEMP_VC_PREFIX: str = "Temp • "               # 自動命名前綴

# 歡迎訊息頻道 ID
WELCOME_CHANNEL_ID: int = 1010456227769229355
RULES_CHANNEL_ID: int   = 1278976821710426133
GUIDE_CHANNEL_ID: int   = 1279074807685578885
SUPPORT_CHANNEL_ID: int = 1362781427287986407

# Logging 頻道
LOG_CHANNEL_ID: int = 1401346745346297966

# Token（由環境變數注入）
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
