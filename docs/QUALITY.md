# 功能地圖與離線驗證

先由出問題嘅使用者動作查入口、狀態擁有者同對應測試。改一個功能時先跑該組，交 PR 時跑全套。以下路徑均相對於 repository 根目錄。

| 要驗證嘅行為 | 先睇邊度 | 測試組 |
| --- | --- | --- |
| 會員、Helper、Admin、私人名單及通知中心 | `core/permissions.py` 分配工具權限，`core/private_source.py` 重查操作者及來源，`features/private_roster_views.py`、`features/notification_center.py` 處理 callback | `members` |
| 語音房、招募卡、足跡卡、舊按鈕重啟後註冊 | `cogs/squad_cards.py` 的 `add_view`、`features/squad_interest.py` 的訂閱及發送收據；歡迎選單另見 `cogs/member_entry.py` | `plans`；歡迎選單見 `tests/test_welcome_verification.py` |
| 預約、加入／退出、發起人通知、Discord Event | `cogs/squad_plans.py` 接互動，`features/squad_plans.py` 的 `PlanBook` 寫 JSON，`features/plan_delivery_ui.py` 接收設定，`features/plan_delivery.py` 管理活動及通知狀態 | `plans` |
| EXP、排行榜、回鍋、稱號角色 | `features/community_levels.py` 的 SQLite 帳本，`cogs/community_levels.py` 的升級公告，`features/title_roles.py` 及 `cogs/title_roles.py` 的稱號同步 | `growth` |
| 香港／台灣語言及中性預設 | `features/language_preferences.py` 從 Discord 身份組讀取偏好，`features/notification_words.py` 管理通知文案 | `locale` |
| 日誌私隱、備份、部署前檢查 | `core/audit_privacy.py`、`core/storage_paths.py`、`scripts/backup_runtime.py`、`scripts/inspect_round_readiness.py` | `runtime` |
| 背景工作、外部 API 及啟動 | `bot.py` 建立 Bot 時傳入已設定嘅 intents，`setup_hook` 載入 cogs 及同步指令。RSS 的 429／退避分別見 `cogs/rss_delivery.py` 及 `core/rss_delivery.py`，直播通知另見 `cogs/stream_alerts.py` | `all`，可先搜尋對應 `tests/test_rss*` 或 `tests/test_stream*` |
| 遊戲官方更新繁中回覆 | `cogs/gta_translation.py` 以原生回覆將公告譯文連回原帖。允許的頻道 ID、共用收據及每月額度見 `core/gta_translation.py`。[操作說明](GTA_TRANSLATION.md) | `python -m unittest discover -s tests -p test_gta_translation.py` |
| FC27 官方直收私人預覽 | [來源限制及驗證](FC27_UPDATES.md)。以 Pitch Notes 結構樣本核對雙語全文、分段與圖說，另以 `--receipt-demo` 核對基線及額度 | `python scripts/preview_fc27_updates.py --metrics` |

## 本機與 CI

在 Git checkout 使用 Python 3.11 的虛擬環境。首次安裝鎖定依賴後，以下 Python 檢查可以用合成資料離線執行。

```sh
python -m pip install --require-hashes -r requirements.txt
python scripts/verify.py static
python scripts/verify.py plans
python scripts/verify.py all
```

將 `plans` 換成表內組名即可縮小測試範圍。`static` 強制重新編譯 Git 追蹤嘅 Python 源碼，將 `SyntaxWarning` 升格成錯誤，並驗證 Codex 配置同測試清單。新增 Python 檔後先 stage，先會納入本機編譯。`all` 再以 unittest discovery 執行整個 `tests/`，包括未列入任何快速組別嘅測試。執行器會建立臨時資料目錄，測試子程序唔繼承主機嘅 Bot Token 或資料庫路徑。

開啟 PR（包括 Draft）或推送新提交到已有 PR 嘅分支，都會自動跑必要檢查 `validate`。未開 PR 時，可以喺 Actions → Python checks → Run workflow 揀分支手動執行。兩種入口都會跑全套測試、鎖檔依賴審計、容器排除私密檔案探針、非 root 身份及掛載卷驗證。Fly 嘅 main 部署流程重用同一 Python 指令，保留機器、持久卷、閒置狀態及備份檢查。正式合併同部署繼續跟原有授權流程。

## 可執行嘅驗收條件

| 操作／故障 | 可核對嘅結果 | 測試檔 |
| --- | --- | --- |
| 清空草稿門檻、發布、有人報名，再重開同一份資料及修改通知 | 空門檻保留；未填過嘅新草稿仍採用原有預設。明確停用嘅活動即使滿人，亦唔會呼叫建立 Event。原有舊格式仍可讀 | `test_plan_delivery.py` |
| 重複報名、退出再加入、建立 Event 超時、程序喺通知發送前後中斷 | 發起人唔會收到同一會員嘅第二次報名通知；結果未明嘅寫入保留待核對，唔會盲目重發 | `test_plan_delivery.py` |
| 同一遊戲切換「下次通知我」／「長期跟局」；切換某一局嘅提醒 | 同一會員同一遊戲只保留 once 或 always 其中一種。某一局嘅提醒同遊戲訂閱則獨立，四種組合都受測。訂閱、可見、被提及及實際到場分開判斷 | `test_squad_interest.py`、`test_private_notification_center.py`、`test_plan_delivery.py` |
| 權限被撤、原訊息失效、Helper 操作 Admin 工具、另一會員開私人頁 | 各 callback 重新驗證，拒絕未授權操作。通知首頁只顯示自己嘅總數；打開遊戲清單先檢查標籤可見性 | `test_staff_boundaries.py`、`test_private_notification_center.py` |
| 回鍋、重送舊 EXP 事件、跨小級或大階梯、稱號同步失敗 | 回鍋按有效角色下限只初始化一次；重大階梯且開啟提醒先容許提及本人；失敗嘅稱號同步保留可重試工作 | `test_level_membership.py`、`test_level_audit.py`、`test_title_roles.py` |
| 重新建構 Cog、保留舊卡；按成員身份組切換語言 | 舊足跡卡重新註冊 persistent view；有相應語言身份組時讀取該偏好，無選擇或衝突時用中性版本 | `test_squad_integration.py`、`test_language_preferences.py`、`test_stage3_wording.py` |

以上測試用真正嘅 Python callbacks、臨時 JSON／SQLite、合成會員及模擬 Discord transport。Discord 客戶端顯示、真實 Gateway 重新派發舊卡、伺服器權限／角色保存、實際通知及平台限流仍須用獨立測試公會及 Bot 驗證。

## 首輪審核紀錄

基線為 `f0383de`。合併入 main 嘅 #207 已有成功嘅 Fly workflow。開始審核時 #203 涉及模型配置，#128／#129 更新 Actions，#127 及 #22 涉及 Python／TwitchIO 升級，另有 issue #197。本輪沿用 Python 3.11、discord.py 2.7.1、TwitchIO 2.8.2 及現有 GitHub 流程。

| 可重現嘅證據 | 影響及今次處理 |
| --- | --- |
| `features/plan_delivery.py:17` 原本將「冇傳參數」同「明確清空」都解成 capacity。三個回歸測試喺舊實作見到數值取代空門檻 | 草稿顯示同已儲存設定可以唔一致。由共用 API 區分兩種輸入，令建立、修改及重載保留使用者選擇。歷史數值無法還原原意，故無批量改寫 |
| `features/notification_center.py` 的 `show_center` 原本為首頁數量逐個查遊戲卡。兩個本人訂閱嘅 fixture 量到兩次查卡 | 減少每次開首頁對 Discord 嘅讀取。修正後同一 fixture 零次查遊戲卡、兩次核對首頁來源；詳細清單保留即時權限檢查。未量度正式流量或 429 次數 |
| `tests/test_community_outcomes.py:33` 等七處用字串常量作 `is None` 判斷。舊編譯步驟成功，新嘅嚴格編譯可指出檔案同行號。原有 `core/storage_paths.py` 亦會接受環境指定資料庫路徑 | 修正 fixture，將嚴格編譯、環境隔離及完整 discovery 接入原有 PR 與部署前檢查；無新增依賴。無證據顯示舊測試曾寫入正式資料 |

## 下一階段

| 優先度 | 根據、工作及驗收 | 成本／收益 |
| --- | --- | --- |
| Critical | 今次抽查、回歸及權限測試未證實有越權或私隱外洩 | 如有新證據，優先重現及修正 |
| High | `features/notification_center.py` 的 `game_rows` 仍會為詳細清單處理全部訂閱，每項最多檢查 20 張卡。測量多頁合成資料嘅 REST 次數，再將可見性檢查限於當頁；翻頁同撤權測試須通過 | 中／減少高訂閱量時等待及限流風險 |
| Medium | `bot.py` 的 `setup_hook` 會記錄 guild 指令同步例外，但可繼續啟動。加模擬同步失敗測試及健康狀態，區分指令同步失敗同 Bot 可連線 | 中／更快發現選單與註冊版本不一致 |
| Low | `docs/COMMUNITY_LEVELS.md:67` 寫離會保留 XP，容易同現行回鍋初始化規則混讀。按 `test_level_membership.py` 核對並標出歷史規則及適用版本 | 低／避免下一次修改採用過時規格 |
