# 03 追加功能：成局 Event 與發起人提醒

2026-11-16（香港）。**程式候選，未部署；普通成員／Helper／Tester／Admin 新版實測均未驗證。**

本文件接續 [03 已確認規格](PLAN_EVENTS_HOST_NOTICES_SPEC.md)，該規格來自 Draft PR #186，commit `4315ef782e1753ae20eb52ac5b214f125e61a78a`。規格 PR 本身沒有功能程式。

本分支 `feat/confirmed-plan-events` 以 06 整合版 `9a53a22f2dc5a4ff55ee98b595c07d822c9d1f86`（Draft PR #185）為依賴基線。沒有重放 #165–168、沒有合併 main、沒有將 #186 文件自行部署。完整基線及先前保護規則證據見 [06 總表](CURRENT_INTEGRATION_STATUS.md)。新 PR 的 head 與 CI 是本候選精確版本證據。

## 成員行為及相容

| 功能 | 候選行為 | 證據／限制 |
|---|---|---|
| 發起前摘要 | 未來局表單後顯示人數、Event 及報名提醒開關；可改門檻／上限，取消不發卡 | 沿用一份表單，加最後確認；現在玩快捷摘要亦明示提醒開關 |
| 成局門檻 | 預設申報原有人數＋尚欠；可調整最低／最高。不限且未另設門檻不建立 Event | 有效、確認且仍有原來源權限的報名才計；稍後到明示；隊友不重複按卡 |
| 達標活動 | 發起成功後由既有 30 秒 tick 建立一次，原卡與 Event 互連 | 達標、並發、未知結果的持久 intent 回歸；Discord 原生端到端未驗證 |
| 活動更新 | 人數回落保留活動並更新摘要；改期重確認並同步；取消／結束同步取消或完成 | 人工改內容／人工提前開始、刪除：停止同步，不覆蓋或重建 |
| 活動有興趣 | 不算報名、不佔名額、不開提醒、不計實際到場或 EXP | 沒有訂閱 Event RSVP gateway 或 users 名單 |
| 發起人通知 | 新局預設開啟，30 秒合併，原頻道僅 tag 發起人，可關閉 | 無 DM／角色／everyone mention；其他有權限成員可見；同人每局最多列入一次新報名提醒 |
| 通知相互獨立 | 本局開局提醒仍主動 opt-in；遊戲一次／長期同意及其原收據不改 | 本功能只新增 plan 內 host 通知 receipt，不轉移既有授權 |
| 重啟 | 舊 queued host notices 記 skipped_restart；sending 記 unknown，不補發 | 已 sent、未知及跳過收據都保留；新報名才建立新批次 |
| 舊約局 | 沒有 delivery 欄位即停用；不批次開啟活動或發起人提醒 | 發起人可從新管理設定逐局選擇，沒有歷史補發 |

## Event 類型、可見性及生命週期

採用 **VOICE Event**，先連到同分類已有的「開一個小隊 call」入口；不預先建立第二間或第二個 Bot。從 REST 讀取原頻道、成員、角色及 voice channels，原卡和候選入口的 `VIEW_CHANNEL` 覆寫必須完全相同（包含 member overwrite 與未解析 target）。這是保守相等檢查；即使兩邊實際等效但寫法不同，也會停用該局自動建立。

沒有相符入口、沒有 Bot View／Connect／Create Events（或 Manage Events）就停用，設定頁顯示原因；不修改任何正式權限，也不改用 EXTERNAL。EXTERNAL 沒有頻道可見範圍，而且 Discord 會按預約時間自動啟動，故不使用。

實際 `PlanBook.sync_session` 記錄 live 後才把 Event 連到本局 voice 並設 ACTIVE；新房同樣要通過可見範圍檢查。單純達標、到了預約時間或按建立房間，不代表實際開局。真正 ended／取消同步完成／取消。VOICE API 不要求 end_time，本功能不設定虛構預計結束時間；Discord 本身也可能在語音清空後結束活動，或將過時未開始活動取消，讀回後保留狀態，不重建。

Discord 原生 Interested 通知與 Bot 開局提醒不能承諾完全去重。原生通知時機、從入口轉到本局房間及跨遊戲頻道可見範圍，需要真人身份驗收。

官方依據（2026-11-16 核對）：

- [Discord Scheduled Event API](https://github.com/discord/discord-api-docs/blob/main/developers/resources/guild-scheduled-event.mdx)：VOICE 讀取受 VIEW_CHANNEL 控制，建立需要 Create Events／View／Connect；EXTERNAL 自動開始／結束及事件狀態轉換。
- [discord.py API](https://discordpy.readthedocs.io/en/stable/api.html#discord.Guild.create_scheduled_event)：create、fetch、edit 的參數與回傳。已核對本專案已安裝 2.7.1 的實際 signature；沒有更改鎖定依賴。

REST 請求之間沒有原子權限快照，無法承諾撤權零延遲。跨來源 ACL 改變時，已連結且未被人工改動的活動會關閉；來源／原卡消失或發起人失權亦關閉本 Bot 未被人工改動的活動。Discord 拒絕關閉或結果未知時保留待核對；不偽稱已撤回已顯示資料。

## 持久資料、未知結果及回復

沒有新 DB、沒有 token 或成員名單輸出。沿用原 `squad_plans.json` schema 2，逐新局新增 `delivery`，內含 settings、Event intent／snapshot、host notice receipts、seen。RSVP 和 notice 入隊在同一次原子 JSON 寫入中；其他模組仍保留未知欄位。載入時檢查新欄位，損壞就 fail closed，不重建空資料。原 EXP、共同參與、語言角色及組隊收據不改。

Event POST 前先存 creating + wanted。403／明確 4xx 記 failed；逾時、5xx 等不確定記 unknown。重啟後只讀 Scheduled Events，必須唯一匹配 Bot creator、plan marker 及原 payload 才綁定；無匹配或多個匹配都不自動重試。人工改動不覆蓋，已刪除不重建。PATCH 亦先記 intent，讀回比對，不假裝成功。Discord API 沒有提供本功能所用的 create idempotency key；SDK／網路層不能保證遠端恰好一次，重複 marker 的情況需人工核對。

回復需保留完整新 JSON（包括 Event ID／snapshot 和所有 notice receipt），以及全部既有 SQLite／偏好／EXP／通知收據。不可用部署前舊 JSON 覆蓋新資料。**已有 Linked Event 時不能直接退回不管理它們的舊版**：先盤點並按已確認範圍收尾或保留新同步器，只回有問題的 UI／模組。未知 Event／notice 不得當作未送而重播。回復尚未真人演練；舊私人面板在重啟後可能失效，不承諾零中斷。

`scripts/inspect_round_readiness.py` 增加 Event／host notice 未解決狀態的布林盤點，不輸出身分／活動內容。既有正式保護規則仍生效，沒有取得 production 執行權；不能聲稱已執行正式盤點或新備份。

## 檢查與放行

本機：32 項新測試，覆蓋門檻、既滿最低門檻、跨遊戲文字、稍後到、退出重入、重確認、最後名額並發、原卡／設定身份與 revision、雙擊摘要、Create intent 先存、403／timeout／讀回、被刪／人工修改、原生 interest 不報名、實際 session 才啟動、ACL 範圍／Bot 權限、撤權、原卡刪除、重啟未知不重播、HK／TW／中性及損壞資料保留。測試用真 PlanBook、真 JSON、真 SDK UI；Discord HTTP 為替身，沒有對成員送通知。

更新原跨頻道發起測試，要求先看到摘要再按確認；過程修正原 SDK TextInput 於建構後改 default 未反映 value 的草稿 bug。舊測試沒有刪除。最新完整回歸、編譯、鎖定依賴審核、容器結果以本 PR 最終 head CI 為準。

| 真人／正式檢查 | 結果 |
|---|---|
| 普通成員／Helper／Tester／Admin | 本候選全部未驗證，沒有用 Owner 或模型代簽 |
| iPhone | 按 Jeff 指示略過，不是通過，不作阻擋 |
| 正式即時 voice／約局／新收據 | 未驗證 |
| Event 實際建立、連結、啟動、改期、取消／原生通知 | 未驗證；沒有建立正式測試 Event 或發測試 tag |
| Bot 現行 Event 權限及各區 ACL 相容 | 未核實；不自行授權或放寬頻道 |
| 新備份／回復 image／資料 readback | 未完成；舊備份不代替本輪 |
| 合併／部署 | 未執行；既有部署授權保留，條件未滿足不放行 |

沒有公告、Tester 通知、宣傳或代表 Jeff 發言。本輪新增自動通知只會在正式放行後，由使用者明示確認的新約局及真正新報名觸發。
