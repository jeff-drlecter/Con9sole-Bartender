> 本文是來源分支交接快照。06 整合修正、最新檢查及部署狀態見 [現行總表](CURRENT_INTEGRATION_STATUS.md)，不可將分支通過當作整合版通過。

# 04 → 06：首次觀察、7／28 日再次到場及可信度

## 基準與交付界線

基於最新 main `15d8a9744ce5644e489db2a675b860a27dc78444`，重新讀現行 community_outcomes、co_participation、squad_outcome_state、daily_task_status、Ledger 與獎勵測試。repository、checkout 上層及 /workspace 沒有 AGENTS.md；遵守 Jeff 在本 Chat 提供的指引。已讀 03 PR #182 head `d2d6a4396c11753cf991423e628131194432858b` 的 `docs/PLAN_DISCOVERY_03_HANDOFF.md` 與 `features.plan_services.contract`。

本分支獨立 Draft PR，不取代前輪 #168，也不合併 main／部署／發布報表。沒有正式 /data 或 Fly DB，不用開發 fixture 當社群成效。iPhone Mirroring／實機按 Jeff 指示略過。沒有玩家名單輸出、聊天內容收集、公開榜單、新獎勵、倍率／門檻改動或追扣分。

## 定義（先決定、後實作）

| 項目 | 精確定義 |
|---|---|
| 首次觀察 | 真人在可用、非測試、未被排除來源的最早到場紀錄，**不是加入社群日期**。以 guild/user/session 首次實際觀測為證；早於有效紀錄有未知來源者，不把他重新當新人 |
| 來源篩選 | 首次錨點先在全部有效 linked/natural 來源找出，再按該首次來源篩選；不因切換篩選器就將舊成員改當首次。明確排除的頻道／測試則不屬有效觀察，首次有效錨點可能隨排除範圍改變，不能比較不同範圍的比率 |
| 再次到場 | 相同 guild/user 在**另一個 session** 被觀察到場。相同 session 重入、Gateway 重複或 Bot 重啟不計。另一 session 跨午夜仍持續被看見可算跨日再到場，不宣稱另開一局遊戲 |
| D0 | 首次觀察至該香港日結束前，在另一 session 再到場。該日尚未完結者待觀察 |
| D1–D7 | 首次香港日期後第 1 日 00:00 至第 8 日 00:00（右端不含）內，在另一 session 到場；D7 完整結束才成熟 |
| D1–D28 | 第 1 日 00:00 至第 29 日 00:00（右端不含）；D28 完整結束才成熟。使用香港日曆，不是 first_seen+7/28×24 小時 |
| 分子／分母 | 分子僅為已成熟者中觀察到再到場的人數；分母為時間窗完整經過的首次觀察者，未成熟單列 pending。每人每觀察窗最多計一次 |
| 比率可信度 | 零分母或任何成熟者 first_seen 至觀察窗結束無完整已記錄成功區段，顯示資料不足、不提供確定比率。仍列已觀察人數、成熟分母、pending、連續覆蓋人數；未再出現不等於流失 |
| 共同參與 | 不變：同一對真人有效觀測 120 秒的**局數**證據。沒有參與者 ID，不能把該局所有到場者當達標玩家。C 只路過仍可算到場，不能推成共同參與達標 |

原有同一約局建立批次內的跨局人數仍保持原名，沒有改名成留存率。報表明示觀測庫起點、首次批次區間、判定截至時間、來源／排除數、有效到場時間範圍及已記錄覆蓋秒數。這是觀測再參與，不證明 Bot 的因果成效，也不證明成功完成遊戲。

## 私人入口與權限

原管理選單「社群成效」提供「約局成效」與「首次觀察／再次到場」兩個私人入口。新增 `/observed_returns days:60 origin:all`；days 可選 1–90，按香港日界從指定日數起至現在，以預設 60 天讓 D28 成熟樣本有機會出現。origin=all/linked/natural。

生成前及輸出前都 REST fetch_member 重驗原有 server-admin（administrator/manage_guild）授權；選單按鈕另綁擁有人與 guild。Helper／Tester／普通成員角色本身不取得報表權限；如另獲真正管理員權限，依既有 server-admin 政策處理。沒有宣稱能收回已經顯示的私人資料。查詢失敗回覆私人「缺漏未當作零」，不產生假的空白成功報告。

健康頁只讀 `CommunityOutcomes.health_status()` 的 available/heartbeat/error，不含出席數、首次人數或玩家 ID。可用性要求 Gateway ready、sampler running、最近 10 秒內成功心跳及無待查錯誤；這不是整週覆蓋證據。

## 來源與 03 介面

03 的 `features.plan_services.contract(plan)` 映射 guild/plan/session/source={channel,message}/origin/created_at/test。本分支在接口存在時直接使用，main 尚未有該模組時用相同的唯讀欄位映射相容；無日期／origin 的值維持 None/legacy，不猜歷史。

新到場 session 保存 source_channel、voice_channel、origin=linked/natural、plan_origin=instant/scheduled/legacy。linked 的 source 是原約局文字頻道，natural 的 source 是語音頻道；兩類都按**記錄下來**的 source_channel 與 voice_channel 套用 OUTCOMES_TEST_CHANNEL_IDS 排除。只在新觀測當下以頻道／分類標籤作 test flag；查歷史時不再按現在頻道名稱倒推。

原有 session 若缺來源，**整個原 session 保持未知**，不因再次看到同一場就填入今天來源或反寫舊到場。新 session 才採新可信來源。若已記錄來源在同一 session 中改變（例如原自然場次其後接管成約局），不悄悄改寫原來源；該次觀察失敗、切斷覆蓋，直到新的可判定 session。這是保守的未涵蓋情況，06 不得當作不存在活動；後續如需支援來源切換，應另定事件級合約。

既有約局成效報表也改為按已儲存來源排除自然／約局到場與共同參與；來源未知歷史另列，沒有刪除舊資料或利用現時名字補造來源。

## 覆蓋證據

新增 outcome_coverage(guild,run,start,end) 與 state。成功抽樣只連接同一 run、相隔 0–10 秒的成功端點；第一次成功為零長區段。超時、中斷／失敗、Gateway disconnect、重啟均不補算間隔。成功不代表每個 Gateway 事件都完整送達，只能支持已記錄的抽樣覆蓋。

錯誤／斷線會切斷健康狀態；例外會換 run ID，即使資料庫當時不能記自己的失敗，下一次成功也不會跨過該間隔續接。既有 outcome_observer_runs 的 last_success/failures 留存但不回填新區段。若早期整星期都沒記區段，那星期仍未知。回復到舊程式再升回來也不補空檔。

## 資料遷移／回復

- 初始化 additive migration：outcome_sessions 加 4 個 nullable 來源欄位，舊列一律 NULL；不修改舊 first_seen/test 或 XP。
- 新增 outcome_visits：按 guild/session/user/HK day 保存該日首次觀測，讓跨午夜的另一 session 被正確看見；相同原 session 仍排除。只有必要識別鍵、日期及時間，沒有名字／聊天。
- 新增 coverage/state 與 guild/time、guild/user/time、guild/source 索引。遷移可重跑；部分 DDL 中途失敗時，重新初始化補齊缺失欄位／表，不推造來源或覆蓋。
- 新查詢先用 guild/time 界定最多 90 天候選，再用 guild/user/time 索引查首次及最長 D28 內的事件；來源在 SQL 過濾。使用一致 read transaction；不是每次掃全庫。既有報表出席／共同參與亦限制到本批 plan IDs 或自然場次時間。
- 06 在停寫／一致 SQLite backup API 快照後升級；不要只複製活躍 WAL 主檔。新表與欄位可保留，前版 observe 已使用明確欄位 INSERT，回復程式可忽略新欄位。
- 回復只回程式；不回復舊通知收據／會員／XP。保留新增表避免丟失證據；舊程式期間不會新增可信來源及區段，再升級後該段未知。沒有需要刪除或重算會員的步驟。

## 獎勵回歸與實際修正

先新增同日重入測試，修正前確實失敗：舊 `daily-task:HK日:user` 收據令 UI 誤示「✅ 已入帳 +5 XP」。修正只比較 proof.stamp 與本次 joined_at，較早收據改顯示「屬於重新加入前；不代表本輪已入帳，不會重複發放」。測試包含真正 member_left／ensure_membership 重置與回鍋 Lv5，再核對每日收據仍阻止重發；沒有改 daily_bonus、award 或任何金額／倍率／門檻。

完整 suite 回歸既有：通知設定零 EXP、每日一次（並發收據）、有效雙人語音計分／Bot、AFK 排除、大 Level 提及／小級文字、Role 稱號、回鍋 Lv5／既定離群重置、邀請獎勵收據。沒有引入留存獎勵，也沒有追扣舊分。

## 驗證與未驗證

新增測試涵蓋同場／跨局／同日／跨日、D7/D28/D29、香港午夜及跨年、未成熟觀察窗、失敗／斷線／重啟缺漏、已知來源後加排除、來源未知歷史、來源變更拒絕、A+B 達標而 C 路過、撤權／查詢失敗、舊 schema 重跑與個資隔離。測試數及精確 commit 見 PR 描述。

本地只用可重現 fixtures，不接正式 DB、不發布 Discord 報表。03 d2d6a43 隔離整合及完整 suite 結果見 PR；02／05 與後續 main 的完整整合由 06 負責。沒有驗證正式資料日期／污染比例／實際覆蓋或真人帳號 UI；iPhone Mirroring／實機已依指示略過。不能由測試宣稱社群已提升參與或已無流失。
