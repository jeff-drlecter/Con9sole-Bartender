> 本文是來源分支交接快照。06 整合修正、最新檢查及部署狀態見 [現行總表](CURRENT_INTEGRATION_STATUS.md)，不可將分支通過當作整合版通過。

# 03 → 02 / 04 / 06：探索、草稿與來源可用性

## 基準與範圍

main `15d8a9744ce5644e489db2a675b860a27dc78444`；Fly run 43696733993 completed/success。僅部署工作流程證據，沒有直接驗證 Fly 程序或正式 DB。
checkout 及上層沒有 AGENTS.md，遵循 Jeff 提供指引。已讀 02 分支 `codex/private-rosters-notification-center` 的 9a34eaa 接口文件。分支基於 main，不整檔覆蓋 02 或 04 擁有檔案。
不部署、不合併、不發正式或測試 Discord 訊息。iPhone Mirroring／實機依 Jeff 指示略過。

## 02 本人提醒服務

`bot.get_cog('SquadPlans').personal_reminders_v1`，version=1。

- `list_for_member(guild, actor_id)` → `{complete: bool, rows: [...], reason?: code}`。
- `read_for_member(guild, actor_id, plan_id)` → `{status: ok, row: ...}` 或 denied/unavailable + reason。
- `set_for_member(guild, actor_id, plan_id, enabled=bool, expected_version=str)` → updated/conflict/denied/unavailable、reason、成功時 version。
- row：id/game/start/status/enabled/can_enable/can_disable/version/url，沒有其他成員 ID 或提醒意願。

遵循 02 `features/plan_reminder_client.py` 所提介面。actor 必須由已驗證的 interaction.user.id 傳入，不接受表單提供其他人 ID。服務本身不要求當前入口等於原頻道，每次以原頻道、原卡 REST 核權。
成員／roles／頻道 overwrites 在局部 guild snapshot 評估，不更改 Gateway 快取。不能跨 Discord 請求提供原子權限快照。
原卡 ReminderView 與通知中心共用此服務；單鎖內 compare-and-set。version 是永久單調的 PlanBook revision：包括 join/leave、改期、提醒操作，退出重報不能重用舊 token。無狀態變動的重複設定返回 unchanged；舊 token 返回 conflict，不重試。
read 狀態會標 unconfirmed；開始後不能再 enable，已存在同意可撤回。新舊報名預設 off、withdrawn、遊戲 once/always 及送達收據規則不改。
原因碼：wrong_guild / denied / not_registered / not_found / source_deleted / card_deleted / source_mismatch / temporary_failure / unknown_result / invalid_choice / revision_changed / state_changed / saved / unchanged。
列表來源失權不回傳名稱或連結；暫時失敗返回 complete=False，不能顯示成沒有提醒。
離線測試替身見 tests/test_plan_services.py（來源可注入 AsyncMock；不可在正式程式 fallback 至 mock）。

## 04 資料合約

`features.plan_services.contract(plan)` 是唯讀映射：
`guild, plan, session, source={channel,message}, origin, created_at, test`。
新局 origin=instant/scheduled；舊紀錄無 origin → legacy，無 created_at/test → None（未知），不猜測或補日期。
沿用 analytics_test、created_at、session 及既有共同參與規則；不寫統計 DB、不新增瀏覽追蹤。availability 不代表取消、未開局或無人到場。

## 使用流程

- 「看看現有約局」：私人，10 筆一頁，可用文字篩選遊戲；每次刷新／翻頁／篩選重新讀來源及原卡，只列可用活動局。顯示預計／尚欠人數、狀態、時間及原卡連結；滿額顯示 0。實際報名仍在原卡，原卡 join/late/leave 重新 REST 核權並在鎖內重算名額。
- 「我的約局」：進行中、即將開始（近至遠）、歷史／來源狀態分組，無 20 筆截斷；保留已核對可用的舊 Teams 卡。失權隱藏，來源無法核對不輸出遊戲詳細資料。刪卡但來源可讀則顯示原卡已刪除，不提供失效連結。
- 「現在玩」欠 1/2/3 → 私人摘要 → 發起／修改／取消。原有人數固定 1；不取任何語音房人數。修改表單提交只回摘要，只有發起才建立紀錄。自訂同樣先經表單回摘要。
- 草稿僅記憶體，重啟失效；取消不寫入、不派 EXP。重複點擊先標草稿已使用；跨草稿仍由現有 PlanBook active-owner 限制防重複。發起前核對來源、成員、Bot 權限；現有發送前 posting 紀錄防未知結果重播。既有任務只在成功發布後觸發。
- 共用引導：在 02 提供 show_next_steps 時直接使用；main 暫以既有 show_route 相容。06 整合 02 後驗證 show_next_steps 分支，不將未整合當完成。

## 原卡可用性與回復

PlanBook 新增可選 availability：available/card_deleted/denied/temporary_failure/unknown_result。與 status 完全分開。
refresh：NotFound=card_deleted；Forbidden=denied；HTTP 暫時故障=temporary_failure；timeout/OSError=unknown_result。刪除、失權、未知停止 dirty 自動更新；不新增補卡。查詢每次重新核對，不盲信舊 availability。
舊 JSON schema 2 相容；新增 origin/availability 可被舊程式忽略。無 SQL 遷移，保留歷史／報名／收據。回復前備份 JSON 與一致 SQLite 快照；回復程式不要回復舊收據、不要刪 posting 證據。未知發送結果沿用人工核對。

## 驗收與限制

完整 unittest 868 項通過；compileall / diff check 於交付前核對。
新增測試：25 筆分頁、滿額 0、撤權翻頁、最後名額競爭、草稿取消、原卡刪／403／500／timeout、通知中心與原卡 token 衝突、重啟、最新角色 snapshot、暫時讀取不冒充空清單。
沿用舊按鈕、提醒去重及共同參與回歸。正式一般成員／Helper／Discord 訊息、Fly 新版程序未驗證；iPhone 實機略過。
02 完整合併驗收（包含來源 origins 收據改動與 dispatcher 的交叉取消情況）由 06 處理，這個分支沒有修改 02 的 shared receipt 來源邏輯。
列表按候選逐一 REST 核權，成員多／約局多時較慢；沒有快取權限結果。瀏覽只用連結返回原卡，不新增遠端報名按鈕。
