# 03 報名到開局 → 06 部署／02 介面交接

> **2026-11-15 狀態校正：** 原程式已隨 #170 合併為 fede4d7，Fly Deploy 43634179965 success。以下未部署／Draft 字句為歷史狀態，不能作目前狀態。 本輪完整現況／待決／驗收界線以 [COMMUNITY_ROUND2.md](COMMUNITY_ROUND2.md) 及整合 PR 的部署證據為準。

## 基準與發布界線

2026-11-15 核對 main `fa433dd80dd8dcf24313d06277e74e87d58b8f06`。
GitHub Fly Deploy run `43601225924` completed/success（2026-11-14）。這是部署工作流程證據，未直接讀取目前 Fly process／資料庫。
獨立分支 `feat/signup-to-session`；不合併、不部署、不發布 Discord 訊息。
main push 會自動部署，06 必須統一安排合併時機。另有新聞 PR #165，部署前重新整合並跑完整測試。

## 行為

- 新舊報名均不代開提醒。加入／稍後到後提供私人開關；原卡的「本局提醒」可重新開啟設定。
- 本局提醒與原有 once/always 合併，一個 session 每位成員最多進一張通知收據；跨 scope 也去重。
- 退出及撤回為本局 veto，即使仍訂閱該遊戲也不通知此局。重新加入不恢復提醒，需再次主動開啟；遊戲訂閱本身不刪除。
- 改期／遊戲／模式變動保留既有重確認；確認前不提醒，確認後保留先前明確同意。取消／修改只更新原卡。
- 已在房內、離群、bot、無法查看文字或查看／連接語音者排除。發送前 REST fetch_member 重新取得角色，再計算頻道權限；API 失敗保守排除。頻道覆寫使用 Discord Gateway 快取，離線實測不能證明零延遲一致性。
- 現有實際場次定義保留：至少一位真人在語音連續約 30 秒，既有場次流程建立卡／接管原卡。建立預約、滿額、時間到及空房皆不消耗訂閱。
- 啟動前已有 session（含未貼卡）與啟動時已佔用房間只建立基線，不因重啟補發通知。
- 原有 pending／uncertain／sent 收據沿用；已知 4xx 拒絕按原機制可重試，timeout／不確定結果不自動重播；管理員人工核對流程保留。
- 通知只發既有組隊目的地；個別 user mentions，無 DM、role 或 everyone mention。
- 「現在玩」欠 1／2／3 人／自訂 → 可編輯表單，遊戲按分類預填，原有人數按目前語音真人數預填（無語音為 1）。平台／模式可自由填。
- 原按鈕 ID、原卡接管、足跡及再約保留。再約只帶表單內容，不帶任何舊報名者或提醒意願。報名與實際到場分開。

## 02 只讀介面

`await bot.get_cog('SquadPlans').member_status(guild, user_id, plan_id)`

每次重新 fetch_member／fetch_channel，檢查本伺服器、驗證資格及 View Channel／Read Message History。
無權／找不到返回 `None`。成功只提供 `id,status,game,mode,start,registered,party,capacity,attendance,revision,permissions`。
`attendance=None` 表示本介面不提供到場數；不得用 registered 或 party 推算。
不提供其他成員 ID、名單、提醒意願、收據。Helper 沒有自動管理權；edit 僅發起人，cancel 僅發起人或既有管理員授權。
permissions 是當下 UI 提示，真正操作仍須由原 handler 重驗。此介面不寫身份組、不更改權限、不發訊息。

## 遷移及回復

新增 JSON 可選欄位 `reminders`、`withdrawn`；維持 schema 2。舊紀錄缺欄位等於空陣列，讀取不寫回；首次操作原子寫入。沒有批次替成員開啟，也沒有 SQLite schema 遷移。
部署前停止寫入或使用一致快照，備份持久 DATA_DIR 的 squad_plans.json、squad_cards.json 及 STATS_DB（SQLite backup API，不能只複製活躍 WAL 資料庫主檔）。
回復程式可讀取額外 JSON 欄位；舊版不會發報名提醒。保留現時 SQLite 收據和場次紀錄，**不要回復舊收據快照**，避免重複提醒。若舊程式期間有退出／重新加入，重新啟用新版前需清除受影響的 reminders 或人工核對，不能恢復過期同意。
如要完全撤回新資料，可在停機備份後移除 reminders/withdrawn，但要同時停用此版本功能；不要刪除 delivery/attempts/cancellations 證據。
部署會重啟 Bot；私人短效面板可能需重開，持久公開按鈕重註冊。不能承諾零中斷。06 須觀察既有語音、卡片、預約、足跡及新聞等服務。

## 驗收

完整 unittest：791 項通過；compileall 及 git diff --check 通過。

離線測試涵蓋：雙來源／跨 scope 去重、預設 off、稍後到、退出／再加入／撤回、滿額、到時／空房不消耗、改期重確認、JSON 舊資料／重開、原收據重試及不確定發送、fresh member 離群／權限變動、快捷表單、私人語言與擁有人限制、02 查閱拒絕與資料最小化。
普通成員、Helper、iPhone Discord、正式語音／訊息及新版本 Fly 執行均 **未驗證**。06 部署後按授權安排；本次沒有發送測試或正式 Discord 訊息。
