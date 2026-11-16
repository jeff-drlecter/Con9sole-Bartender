> 歷史交付／驗收快照：本文的版本及待辦不代表現況。請先看 [現行整合狀態與證據](CURRENT_INTEGRATION_STATUS.md)；保留原文供追溯。

# 04 → 01／06：社群成效統計及獎勵 review

> **2026-11-15 狀態校正：** 原統計已隨 #171 合併為 2922760，Fly Deploy 43635343478 success。以下是原 review 歷史；本輪改房間開局率、補自然語音及觀測覆蓋，詳見新交接。 本輪完整現況／待決／驗收界線以 [COMMUNITY_ROUND2.md](COMMUNITY_ROUND2.md) 及整合 PR 的部署證據為準。

## 基準、授權與交付

核對 main `fa433dd80dd8dcf24313d06277e74e87d58b8f06`，03 Draft PR #166 head `5ca1a9c90141c732ac60ec7cb493ee8be2612253` 及 `docs/SIGNUP_TO_START_HANDOFF.md`。03 尚未合併；本分支不猜測已部署。使用既有 PlanBook `live/ended + session` 關聯，唯讀讀取 SquadCards 當下成員；不改提醒、語音開局、收據或約局狀態機。沒有使用 02 的成員摘要作出席證據（其 attendance=None）。

獨立 PR 保持 Draft，交 06 統一整合。**不要直接合併：main push 會自動部署。** 本次未部署、未發 Discord 訊息、未改 XP、倍率、稱號門檻、排行榜或現有會員資料。沒有聊天內容收集、公開榜單、DM 或自動報告。

## 管理入口

既有管理選單 → 社群成效（預設香港本週）；另有 `/community_outcomes` 今天／本週／上週。只回覆 ephemeral，禁 mentions。選單按現有 server-admin 政策隔離，handler 在生成前及送出前 REST fetch_member 重驗管理員權限；Helpers 不因角色取得權限。普通成員、Helper、iPhone 和正式 Discord 操作尚未實測。

## 統計定義

| 指標 | 定義及界線 |
|---|---|
| 新約局 | 建立時間落在所選香港日／週半開區間的 已發布 plan ID 去重數，包含現在玩及取消局；posting 未發布另列，不計新約局；舊紀錄缺 created_at 不猜建立日 |
| 已實際開局 | 本批約局狀態 live/ended 且有 session。沿用 03 的至少一位真人通過約 30 秒流程；**不表示已湊齊隊伍或 Bot 帶來新隊友** |
| 未開局 | 本批 status=expired；不能把 gathering、history 或舊 started 直接當失敗 |
| 取消 | 本批 cancelled 獨立列出；仍未到判定期限的取消局不先放入成局率分母 |
| 成局率 | 同一建立批次中，開始後 2 小時／現在玩 6 小時已到期的約局為分母，包括取消。分子只計這批到期約局的已開局；未來及未到期限約局不算失敗 |
| 未知 | 到期但無可靠成功／失敗／取消證據；留在到期分母並列未知數，**整批含未知時顯示資料不足，不提供單一確定率**。零分母同樣不顯示 0% |
| 語音參與人次 | 本批連接約局中實際觀測到的 (guild, session, user) 唯一組合；同人重入同局不重算，另一局再計一次 |
| 去重參與人數 | 上述人次再按 user 去重；跨局再參與人數為出現超過一個 session 的人數，不稱留存率 |

本週從香港星期一 00:00 開始。上週採上週建立批次，但按本次查詢時間判定到期及出席，避免僅按上週結束時截斷。面板列明建立區間與判定截止時間。更改預約時間沿用目前 start/deadline，不另造原始場次。

## 可用資料盤點與涵蓋範圍

**本環境只有 repository，沒有正式 /data 快照或 Fly DB 連線；無法核實正式最早／最晚日期、數量及測試污染比例。** 不把目前空白開發資料當正式零人／零場。

| 來源 | 能證明 | 涵蓋日期／缺漏 |
|---|---|---|
| STATS_DB command_usage | 功能使用及時間 | 正式 MIN/MAX 尚待快照核實；無成功出席證據、無完整測試標記，不用作成效 |
| daily_bar_completions | 每日完成任務 | 有 day/completed_at；程式 2026-11-09 切換任務排程是規則日期，不能當正式資料起點 |
| community_levels.sqlite3 xp_events | 計分事件來源／時間／分數 | 正式範圍未知；可能有匯入、重置／遷移，不能等同完整社群參與史；receipts 只保留最近 7 日，不能推回完整歷史 |
| squad_plans.json | 現存狀態、時間、session 關聯 | 舊資料沒有 created_at；start 是預約時間而非建立時間。新程式才為新約局保存 created_at／analytics_test，無歷史補填 |
| squad_cards.json | 尚存場次與累積參與顯示 | 完結會移除；名字快照不足以排除歷史 Bot 或確定到場時間，**不回填統計** |
| STATS_DB squad_participant_snapshots | 卡片名單及 legacy 文字 | 沒有完整日期／Bot／測試標記；不用作新觀測出席 |
| squad_interest_*、squad_card_posts、squad_ended_sessions | 訂閱／通知／卡片嘗試與結束收據 | 通知成功不等於真人到場；不讀 users 或 context 來推斷出席 |
| 新 community_outcomes.sqlite3 | session／plan、真人 ID 及首次觀測時間、測試標記 | 第一次啟動記錄 since；5 秒抽樣及語音進出事件，不讀／保存聊天、display_name、報名名單或朋友數 |

06 可在一致且唯讀的 runtime 備份執行：

```sh
python scripts/inventory_outcomes.py --data-dir /path/to/consistent-backup
```

輸出只含表列數量與最早／最晚欄位值，沒有聊天／名字／成員 ID。SQLite 使用 mode=ro，不初始化缺失資料庫。若 STATS_DB_PATH／約局 path 有 override，06 須按實際設定準備對應檔案名稱，不能誤讀預設位置。日期為 Unix 秒或原表 ISO 文字，需按香港時區解讀；現時無正式執行結果。

## 品質、測試與限制

- 新約局按頻道或分類包含「測試／test／sandbox」保存保守 test flag；歷史查詢再按仍可辨識的頻道標籤排除，支援 `test/is_test` 舊旗標及 `OUTCOMES_TEST_CHANNEL_IDS` 明確 ID 排除。不猜成員是 Tester 就把其全部真實參與排除。已刪除／改名且未標記的歷史測試仍可能無法辨認，06 需補已確認的排除 ID。
- 只收集既有 live + session 一致的連接約局、當下語音成員；Bot、AFK 頻道、未開局／結束／錯誤 session 都排除。到場不要求開咪；EXP 原本有更嚴格有效語音資格，兩者不能混用。
- (guild,session,user) SQLite 主鍵在重啟後仍去重。全程不回放舊 participants、報名、稍後到或 party。
- 所有到場數是**已觀測下限**；短於抽樣、Gateway 漏接、停機、未連接約局的自然語音場次未涵蓋。重啟只記當下見到的人，不推算離線到場。無觀測場次標示出席未知，不能聲稱 0 人到場。
- 新資料庫不會刪現有資料，無個人公開輸出；只有必要識別鍵／時間，不另存聊天內容。沒有新排程發訊息；sampler 只寫內部觀測。
- 約局狀態及觀測 DB 是分開快照；並發操作可能到下一次查詢才反映，非跨來源原子快照。任何資料讀取錯誤不得解釋為零，需修復資料來源後重查。

## 獎勵 review：有證據支持

| 發現及證據 | 建議（未實作政策變更） |
|---|---|
| `FootprintView.toggle` joined 時 dispatch 唯一 `interest:{scope}:{user}:{interaction}`；`Ledger.award` 以新 event 收據＋共用 engagement CD 計 activity。測試在隔 61 秒的新事件可再獲 XP；預設 activity_daily_cap=0 | 訂閱偏好應考慮不再作重複可得分互動，或按遊戲／期間一次性；這是可刷機制證據，**非已發生濫用的證據** |
| `features/daily_bar.py` 的 team 任務以成功建立卡片完成，`cogs/squad_plans.py` 發布後 complete_task；不要求開局／到場 | 任務完成只當招募行為，不當成功組隊。日後可評估以觀測成局或有效雙人參與作另一類成果，先處理取消、斷線與未知，勿追溯扣分 |
| Ledger 活動與文字共用 CD；活動可設每日 cap；每日任務 reward_task 使用 HK day + user 唯一收據，+5 每日一次 | 保留現有防重／冷卻作基線；不因操作數高就加倍率。酒吧互動重複經新 interaction 過 CD 可入帳，尚無真實濫用比例 |
| `voice_members` 排除 Bot／AFK／耳聾／舞台 suppress；voice_tick 要至少兩位有效真人及計分週期，預設 300 秒／25 XP | 現有語音資格比卡片開局嚴格。保留此區分，不以一人 live 或剛進房就派成果獎勵 |

以上是 main 程式預設及離線測試；**未讀正式 settings，不宣稱正式目前倍率／上限與預設相同**。

## 仍需觀察（01 決策）

部署後至少觀察完整週及足夠到期約局，再比較同批成局、取消、未知比例、跨局重複參與。沒有樣本前不設成功率目標／數字門檻，不推算因果。現在未知是否已有刷分、哪些酒吧互動帶來後續真人參與、語音是否純掛房、訂閱是否增加出席。這些不能由操作次數／XP 總量證明。若要衡量「至少兩人同時相處一段時間／湊齊指定隊伍」，需先定義另一個成果指標；本 PR 不擅改 03 開局標準。

## 06 整合、備份與回復

將本 PR 與 #166 及其他待整合 PR 在隔離分支驗證，不直接合併到 main。保留 DATA_DIR 持久掛載；新增資料庫為 `community_outcomes.sqlite3`，既有 PlanBook schema 2 可讀新欄位。備份仍須停止寫入或 SQLite backup API 的一致副本，不只複製活躍 WAL 主檔。

回復此 PR 程式不需改會員／XP DB，不回復任何通知收據。可保留觀測 DB 與新 JSON 欄位，舊程式忽略額外欄位；若停止記錄，期間出席未知，不能回填。部署會重啟及重新 sync 指令，私人短效面板可能需重開；對既有卡、語音、約局及通知仍需 06 正式驗收，無零中斷承諾。

驗證結果見本 PR 描述；普通成員、Helper-only、iPhone、正式 DB 範圍及部署均未驗證。
