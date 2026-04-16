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
FALLBACK_CHANNELS = {}

# 臨時語音房設定
VERIFIED_ROLE_ID: int = 1279040517451022419
TEMP_VC_EMPTY_SECONDS: int = 120
TEMP_VC_HUB_NAME: str = "開call"

TEMP_VC_PREFIX: str = "小隊call •"   # 👈 有空格 + 點
TEMP_VC_SWEEP_SECONDS: int = 300
TEMP_VC_DEFAULT_USER_LIMIT: int = 32
#social media link
SOCIAL_INSTAGRAM_URL = "https://www.instagram.com/con9sole/"
SOCIAL_THREADS_URL = "https://threads.net/con9sole"

# 歡迎訊息頻道 ID
WELCOME_CHANNEL_ID: int = 1010456227769229355
RULES_CHANNEL_ID: int   = 1278976821710426133
GUIDE_CHANNEL_ID: int   = 1279074807685578885
SUPPORT_CHANNEL_ID: int = 1362781427287986407

# Logging 頻道
LOG_CHANNEL_ID: int = 1401346745346297966

# Token（由環境變數注入）
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
