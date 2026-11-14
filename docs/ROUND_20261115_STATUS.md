# 06 本輪整合及分階段驗收（2026-11-15，香港時間）

本文件是本輪狀態入口。PR 交接的本地測試及口頭完成均不代表已部署或成員驗收。

## 可核對來源

| 分工 | 原 PR／分支 | 原始 commit | 實際交付 |
|---|---|---|---|
| 05 | #165 feat/news-experience-settings | 211cedbc66a93db0bcf0deb83ccfe148e5c254f9 | 情報設定分流、日期及來源、SQLite 偏好讀回 |
| 03 | #166 feat/signup-to-session | 5ca1a9c90141c732ac60ec7cb493ee8be2612253 | 預設關閉的本局提醒、去重收據、現在玩快捷人數 |
| 02 | #167 codex/news-helper-access | 072f09662e34d0ba57f0e4c0789b82118c44e28d | 權限只讀盤點、零分類恢復提示、Helper 概覽 |
| 04 | #168 feat/community-outcomes | 38c975c0a89dc6d33d65f1b0d06b58e2348cca42 | 私人同批成效統計、觀測出席、獎勵風險 review；未改 XP 規則 |

基線 main `fa433dd80dd8dcf24313d06277e74e87d58b8f06`。
Fly workflow [43601225924](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43601225924) success，日誌證明更新單一 machine `9080d6d9a9d168`。
最後已核實成功 image：`registry.fly.io/con9sole-bartender:deployment-01M7D4TQZWYNRY9Y0ANF2ZXKMR`，digest `sha256:5e210fc5e07cc4b5d14e8942bcbfecd22966a4a56c2c8689d579323b5e28b17c`。
這是歷史工作流程證據，不是現在的 Fly 程序／資料新鮮度證明。部署前須重讀狀態，若有其他新 main 先重新整合。

## 分批順序及關卡

1. `codex/round-20261115-news`：05 新聞改善、只讀遷移核對、部署前私有備份。新聞設定／來源／推送規則沿用既有授權。
2. `codex/round-20261115-squads`：03＋02；必須先取得階段 1 一般成員新聞驗收，不能以 Admin 代替。
3. `codex/round-20261115-integration`：04＋06 主選單及導覽；必須在階段 2 驗收後才部署。

不得一次合併全部到 main；main push 會自動部署。未有普通成員實測時階段 2／3 留 Draft。
沒有公告、Tester 摘要、宣傳、測試通知、DM、角色／頻道權限或名稱變更。

## 備份及回復

- 工作流程先把本次 checked-out 的只讀 marker verifier 在舊機執行；缺失／損壞的 applied.json 直接失敗，不再自動執行 apply_news_channel_categories.py。人工 migration 工具仍保留但本輪不執行。
- 再記錄當時 image／machine，執行 `scripts/backup_runtime.py`，私有結果放 `/data/release_backups/<backup-id>`。不把資料庫、收據、名單或備份附件發到 GitHub。
- SQLite 使用 backup API（包含 WAL），quick_check 後重新還原到隔離記憶體驗證；JSON 讀取完整原子替換版本、解析並計 SHA256。全部讀回成功才寫 ready manifest；任一步失敗阻擋部署。
- 這是逐 store 的 online 一致副本，**不是跨 store 全域同一時間快照**。每檔記錄 captured_at。跨 store 災難重建須先停寫，逐來源 reconciliation，不能直接覆蓋全部。
- 外部路徑 override、symlink、空資料目錄或資料損壞會阻擋備份，需私下核對。備份與服務共用 volume，不能代替離機災難備援；本輪不擅自把會員資料匯出到其他服務。
- 程式回復：以部署前實際 image 透過既有 Fly 部署方式回復，保持相同 /data 掛載及單一 instance。不要啟動第二個 Bot。若 status 與上述歷史 image 不符，以最新已核實的部署前 image 為準。
- **程式回復不還原資料庫／通知收據／XP 舊快照。** 保留 pending／uncertain／sent、一次訂閱消耗、取消紀錄及場次。結果不明的發送不重試。
- 03 新增 JSON 可選 reminders／withdrawn；04 新增 created_at／analytics_test 及獨立 community_outcomes.sqlite3，無 XP 或既有 SQLite schema 破壞性遷移。舊版忽略新欄位；03 回復期間有退出再加入時，重啟新版前需核對／清除受影響同意。
- 單機更新會短暫中斷 Bot 回覆、按鈕、背景工作／新房建立；現有 Discord 語音房不是隨 Bot 刪除，但服務恢復與場次重連仍須驗證。短效私人面板重開；持久卡 ID 保留。停機出席未知，不能補造。

## 功能狀態

| 功能 | 程式版本／階段 | 程式檢查 | 新部署版本 | 本輪 Discord 身份／結果 | 尚未完成 |
|---|---|---|---|---|---|
| RSS 設定分流及舊新聞按鈕 | 05／階段 1 | 787 項完整 unittest 通過，含部署／備份檢查 | 尚未部署 | 只讀看見既有 PS 固定卡，無按鈕操作；不能當一般成員 | 一般成員、Helper、iPhone、三頻道互動、19:00 摘要、正式 DB |
| 新聞遷移保護／私有備份 | 06／階段 1 | WAL／JSON／隔離還原、拒絕錯誤／外部路徑等離線通過 | 尚未執行 | 不涉及成員操作 | 真正 /data 備份 id、現機狀態及復原操作未驗證 |
| 約局／足跡／一次及長期提醒 | 03／階段 2 | 初次 05＋03＋02 整合 800 項通過 | 未部署 | 無真人操作 | 階段 1 成員關卡；語音、退出／撤回、收據及重啟現場驗收 |
| Helper 概覽／新聞權限盤點 | 02／階段 2 | 含 64 種權限模型；不等於正式權限 | 未部署 | 本輪無 Helper 登入操作 | Helper-only、完整 live overwrite 快照、外部 Bot 依賴 |
| 私人成效統計／EXP | 04／階段 3 | 待 06 完整整合回歸；XP 規則未改 | 未部署 | 無真人操作 | 正式涵蓋日期、測試污染、Admin／Helper 拒絕及觀測出席 |
| 主選單／語言／舊訊息按鈕 | 06／階段 3 | 待完整整合回歸 | 未部署 | 無真人操作 | iPhone／電腦可讀性、舊卡、實際角色偏好、返回路徑 |

本輪未取得可登入的一般成員／Helper-only 驗收 session；既有 Owner 畫面不替代。實際角色未在本輪重新核實時，不挪用歷史角色當作本輪已驗收身份。

## Jeff 待決項目（不混入程式部署）

| 提案 | before → after | 可用證據／執行條件 |
|---|---|---|
| 05 新聞分類名稱 | `📡📡 - 即時情報站 - 📡📡` → `📡📡 - 遊戲情報站 - 📡📡` | 目前只是設計提案；分類 ID／當前名稱／子頻道覆寫仍需最新只讀核對，未到可執行狀態。保留 ID、排序、子頻道、權限，原名作回復 |
| 02 角色／頻道權限 | 本 PR 提出的正式差異為空 | 不刪 no-news-sub、不增 Helper 全新聞權限；如 live audit 發現差異，再列 channel、target、allow/deny before→after 交 Jeff 決定 |

## 文件時效

docs/RSS_DELIVERY.md、舊測試摘要與歷史 acceptance 是累積歷史，涉及 MonitoRSS 仍派送／尚未正式取代等文字可能已過時。正式規則以本輪版本的 fly.toml、docs/rss_production.json、實際程式及最新部署證據為準。
四份 HANDOFF 保留原始交接，不把其中「未部署」視為永遠最新；本表需隨每批證據更新。Steam／Epic 仍 STORE_NEWS_PUBLIC=0，不藉本輪轉正式推送。
