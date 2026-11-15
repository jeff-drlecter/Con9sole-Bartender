# Con9sole 現行整合與驗收總表

更新：2026-11-16（香港）。本文件記錄本輪 02–05 的整合候選，不是發布公告或放行證明。版本以 GitHub PR head / Actions 的完整 SHA 為準；舊文件只代表當時快照。iPhone Mirroring／實機依 Jeff 指示略過，不計通過，也不作部署阻擋。

## 正式基線與交接證據

最新已核對 main：`15d8a9744ce5644e489db2a675b860a27dc78444`。
真正 Fly 部署：[43696353088](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43696353088)，job `132757633515`，success；image `registry.fly.io/con9sole-bartender:deployment-01M7F6E9RBKN6MKG3VJG3RJ4C6`，digest `sha256:61ace5bc5a85bf87d47b5f8aa51af67502b4c9bddbbd28076db0ec6770c27c23`，machine `9080d6d9a9d168`。
`43696733993` 是 Channel emoji names 工作流程，並非 Fly deploy；03 原交接的該項分類已在此更正。歷史 workflow success 不代表現在的服務健康。

| 任務 | Draft PR / 精確 head | 分支交接與原檢查 | 接口／相容／未驗證 |
|---|---|---|---|
| 02 私人權限／通知中心 | [#181](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/181) / `9a34eaae9262a6bc04c02bdd2afcf282657f0fa1` | [交接](PRIVATE_CENTER_02_HANDOFF.md)；877 tests；CI `43732033673` success | 依賴 03 `personal_reminders_v1`；新增 receipt origins；舊來源不可推定；真人權限未驗證 |
| 03 探索／草稿／失效卡 | [#182](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/182) / `d2d6a4396c11753cf991423e628131194432858b` | [交接](PLAN_DISCOVERY_03_HANDOFF.md)；868 tests；CI `43733092235` success | 提供本人 CAS 提醒服務、04 `contract(plan)`；JSON schema 2 新欄位向後相容；真人流程未驗證 |
| 04 再參與／資料可信度 | [#183](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/183) / `bce72fc88d522912b7fd69d3596a893032240346` | [交接](OBSERVED_RETURNS_04_HANDOFF.md)；876 獨立／884 與 03；CI `43734663583` success | SQLite additive 來源／按日觀察／覆蓋表及索引；不補歷史；正式資料範圍未驗證 |
| 05 新聞／直播／健康頁 | [#184](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/184) / `78a799820074439cbfe84a7745e5f4f4ea1521a2` | [交接](DELIVERY_HEALTH_HANDOFF.md)；865 tests；CI `43735465707` success | 既有 DB 加觀測表；只讀 health snapshot；04 僅 available/heartbeat/error；正式 API/交付未驗證 |

四份交接已具備 PR、精確 commit、測試、接口、相容／回復及未驗證說明。分支各自 CI 不作整合版通過的替代。

## 保留與合併範圍

整合分支：`codex/round-20261116-integration`，從上述 main 建立隔離 worktree。保留期間 main 的 #173 Helper／Tester 邊界、#174 已批准 EXP／共同參與政策及 #175–180 頻道名稱相容修改。沒有新增正式角色或頻道改動。

#165–168 雖仍 open，其舊內容已透過 #169、#170、#171 的 squash 與後續 main 修正整合。沒有重複合併／重放這四個舊 head，亦不以原始 commit 非 ancestor 判定未整合；依 main 歷史、現行程式和後續修正核對。

03 先接入，02 按 `squad_cards` 私人頁面／入口的方法範圍接入；04 與 05 的 `bot_health` 唯一文字衝突保留 05 管理員詳細區，04 只提供約定三項健康值。沒有整檔覆蓋其他開發內容。

## 整合時發現及修正

- 首次合併跑 906 tests，發現 02／03 共用新人路線測試仍使用舊 response fixture；更新為真實 defer/followup、按選擇遊戲後核對 `<id:customize>`。沒有刪除原測試。
- 發送器仍將本局 withdrawn/unconfirmed 排除套在所有遊戲訂閱上。現在 game 與 plan 各自判定，合併後 session 去重；收據傳入當前 plan recipients，取消 game 亦不能借已撤回 plan 授權送出。
- 缺少完整 origins 的舊／部分 receipt 不能證明同意來源。自動 dispatcher 不 claim、不改 sent、不重播，原 pending/uncertain／users／revision 原樣保留，中心提示未分類。這是隔離，**不是已清理或已送達**；未分類資料數量以正式盤點為準。人工 review 的一般 retry 也不能繞過來源要求。
- 私人名單過濾的成員重新綁定已取得的角色 snapshot；管理報表與健康頁讀取 REST member **及** role definitions，輸出前再次授權。保持共享 gateway cache 原樣；仍無跨 Discord HTTP 請求的原子權限快照。
- 健康頁遵守管理員詳細區、Helper 基本區；原始統計錯誤不輸出。測試覆蓋讀取期間撤權、embed 欄位／長度。
- 03 來源暫時失敗不再顯示「沒有約局」；本局提醒原卡刪除等 unavailable 不再回傳空清單假成功。約局列表增加返回主選單路徑；草稿補私人 HK 文案和使用者文字 escape。
- RSS 排程觀測不再更新最後嘗試時間或清除故障／待核對標記；真正取得或交付成功才重設連敗。直播健康頁從持久 pending 收據補回未知狀態；沒有觀測紀錄時不猜成功交付。`checked_current_batch` 僅代表本次輪詢批次，個別帳號的待核對仍各自列出。

## 現行功能狀態

| 成員可感受到的改變 | 程式來源／整合檢查 | 本輪部署 | Discord 實測／未驗證 |
|---|---|---|---|
| 私人足跡／訂閱名單開啟後撤權會停止新輸出，重新過濾離群／失權者 | #181；REST roles、來源刪除、他人操作、重新過濾回歸 | 未部署 | 普通成員／Helper／Tester 真帳號未驗證；不能收回以前已顯示資料 |
| 「我的組隊通知」分本局提醒／遊戲訂閱，原卡同一設定、舊操作不能復活已取消同意 | #181+#182；真 `PersonalReminders` + 真 PlanBook/SQLite + 中心／原卡交替及 CAS | 未部署 | 沒有對成員發任何測試通知；正式去重／撤權延遲待驗證 |
| 私人查看現有約局、分頁篩選；即玩先看摘要，取消草稿不發卡 | #182；既有 25 筆／最後名額／失效卡及整合錯誤／返回測試 | 未部署 | 正式發起→報名→語音→結束→再約尚未實測 |
| 一次、長期與本局同意各自保存；同局只提醒一次 | receipt origins + dispatcher 整合修正；既有收據／重試／重啟回歸 | 未部署 | 舊未分類收據會隔離，不猜原同意；正式盤點仍待紀錄 |
| 管理員查看首次觀察、D0／D7／D28，再參與缺漏不當流失 | #183；香港日界、成熟分母、未知來源、測試排除、覆蓋中斷 | 未部署 | 正式觀測起點、污染範圍、真人報表待驗證；不宣稱社群成效提升 |
| 同日離群重入的每日獎勵提示更準確 | #183；真 Ledger 重入／Lv5／舊每日收據，獎勵政策不改 | 未部署 | 正式會員資料沒有修改或重算 |
| 新聞／直播區分來源取得、交付、失敗、無內容、結果未知 | #184 + 整合修正；重啟、失敗恢復、空窗口稍後到文、收據未知 | 未部署 | 正式來源、外部 API、新交付與管理員健康頁待驗證 |
| HK／TW／未選語言、舊卡、偏好保存 | 既有語言、舊 custom ID、重啟及新私人操作測試 | 未部署 | 本輪電腦 UI 三語未實測；iPhone 按指示略過 |

## 整合檢查證據

本地 Python 3.12.14：`python -m pip install --require-hashes -r requirements.txt`、`python -m compileall -q .`、`git diff --check`；完整 suite `python -m unittest discover -s tests -q`。最新程式完整回歸結果以整合 PR 的 CI SHA 和下方追加紀錄為準。使用 isolated fixtures，未啟動第二個 Bot、未登入 Discord gateway、未取得正式 token、未向成員送訊息。

`tests/test_current_round_integration.py` 使用真 02 adapter、真 03 service、真 PlanBook／receipt DB；只有 Discord transport 是替身。原有 `tests/test_round_integration.py` 完整保留。`tests/test_round_readiness.py` 驗證舊 schema 只讀、缺檔不當零、不輸出成員 ID。

GitHub `Python checks` 對整合 head 執行 Python 3.11 完整回歸、編譯、鎖定依賴 pip-audit、容器私檔排除及 UID/GID 10001 / 持久卷保留。當前本機沒有 Docker；不以靜態讀 Dockerfile 冒充容器通過。CI 未完成前不預稱成功。

## 電腦版身份驗收

| 身份 | 本輪實際帳號／證據 | 操作與結果 | 狀態 |
|---|---|---|---|
| 普通成員 | 沒有已核實可操作的普通成員登入 | 未執行新版本端到端流程 | 未驗證 |
| Helper | 沒有獨立 Helper 登入 | 未執行新版本名單／健康頁邊界 | 未驗證 |
| Tester | 沒有獨立 Tester 登入 | 未執行正式工具拒絕／示範區驗收 | 未驗證 |
| Admin／Owner | Chrome 現有 `jeff_drlecter`；可見 Server Settings、Security Actions，未重新核對完整角色組合 | 只讀取 Channels & Roles 及管理選單後關閉；未改任何選項，未操作新版本 | 環境已核對；不算本輪功能驗收、不代普通成員 |
| iPhone | 無 | 按 Jeff 指示略過 | 略過，不是通過 |

待真人桌面矩陣：無遊戲身份→合法引導→探索／發起→報名→本局提醒→語音開局→結束／再約；撤權後翻頁／刷新、他人操作、來源刪除、並發；三語／原卡／中心一致、偏好重啟；統計與健康頁分權。測試身份可用既有專用帳號；不得自行改正式權限來製造身份或向真成員送測試提醒。

## 正式盤點、備份與回復

新增 `Round integration read-only inspection` 現僅允許 main 手動執行（不會隨 push 或部署自動執行），借既有 Fly SSH 程序讀 image、SQLite 與 JSON。沒有 Bot login、migrate、UPDATE、POST 或角色操作；只輸出存在與否及資料完整性，無玩家／活動名單或私人統計。腳本成功只代表讀取完成，固定 `deployment_approved=false`。

`persisted_active_voice_sessions_present` 來自 Bot 持久狀態，**不是即時 Discord voice snapshot**；部署前仍要核實活動語音／約局及 pending/posting 的影響。無法讀取不當作空閒或零筆。

上一正式部署的備份 `20261115T085103Z-ac7e05a630c142689dafe70598a5d5b8`，62 stores，SQLite backup/restore readback passed。這是歷史證據，不能代替下次部署前的新備份。既有部署 workflow 會先記 current image、對 `/data` 新建備份並回讀；每 store 一致，不是跨 store 全域交易，也不是異地備份。

遷移：02 加 `origins`；04 加 nullable 來源、visits、coverage/state 及索引；05 在既有 DB 加 `delivery_observations`；03 JSON 可選欄位。均 additive，可重跑；未知歷史不回填，既有 EXP／同意／通知收據保留。

回復目標以部署前**再次核實**的正式 image 為準，目前歷史候選為上列 `01M7F6E9...`。執行方式：單機 `flyctl deploy --app con9sole-bartender --image <已記錄image> --ha=false`，先核實 image 與既有 `/data` 掛載／單機設定。不要啟動第二 Bot，不要還原舊 DB／JSON／EXP／偏好／收據；新增欄位表保留。回舊版會失去本輪權限及取消修正，並可能讓隔離的舊 pending 重新被舊 dispatcher 處理，因此有未分類待發紀錄時**不可直接全版回退**；優先針對故障模組修復／保留新 dispatcher。真正 rollback 尚未執行，不宣稱演練通過。

單 Bot 更新可能短暫斷線；舊 ephemeral 面板、進行中未完成觀測區段及 callback 可能失效，從持久原卡重開。語音房、約局及收據不刪，但不承諾零中斷或無漏接。

## 放行及剩餘事項

尚未合併 main／部署。本輪沒有發布公告、Tester 通知或宣傳，也沒有代 Jeff 發言、改正式角色／頻道或 XP 政策。

放行前須取得整合 head CI、正式資料盤點、可用新備份／回復目標，以及關鍵權限和資料保存的可核實結果。缺少實際身份繼續標未驗證，不能由 Owner 或 fixture 代簽。涉及會送出訊息的真人流程，只能在既有授權專用測試安排內做；目前沒有這項實測證據。

Jeff 已授權條件達標後部署，不需重問同一部署許可。真正需要 Jeff 補充的，是可操作的普通成員／Helper／Tester 測試登入或其操作證據；不要提供密碼或 token。若正式盤點發現未分類舊收據，先只保留／隔離，額外取消或人工發送另列精確內容決定，不能在程式部署時自行處置。


## 2026-11-16 00:50 香港｜已完成檢查及正式存取阻擋

- 程式整合 SHA `cb54644cf4c85e44052ad44759a00e6f7759cfb7`，tree `5eb2e0d1d5f490c179afed3efdf9534823eb9f56`；[整合 Draft PR #185](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/185)。本地與遠端 tree 相同。
- 此 SHA [PR CI 43737611809](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43737611809) 及 push CI `43737607727` 均 success；job `132883573723` 的安裝、編譯、完整回歸、locked dependency audit、容器建置／私檔排除／非 root／持久卷檢查全部 success。本地 917 tests / OK。
- [正式只讀盤點 43737608053](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43737608053) 在執行任何 step 前被 GitHub production environment protection 拒絕：本整合分支不獲允許進入 production。Annotations 明確列出 branch protection；沒有 SSH、沒有資料讀取／寫入、沒有 Fly deploy。
- **沒有移除 environment、修改保護規則、改用其他 secret 或先合併 main 來避過限制。** 只讀 workflow 已收窄為既有 main 手動入口，避免無效分支重試；腳本仍可供已有授權的正式執行環境檢閱及執行。尚未在 main，不能宣稱現在已能手動執行它。
- 現有正式版本只獲歷史 Fly deploy 證據；即時健康、活動語音、活躍未分類 receipts、新備份及可用回復目標仍未核實。這些與真身份驗收是目前放行阻擋，**沒有部署本輪新程式**。
- 此後新增一項實際 dispatcher 整合回歸，驗證三類來源在 reserve 後各自撤回、僅剩有效 game 候選送一次，以及 legacy pending 保留。這是假的 Discord transport，不是成員實測。最終 head 及最新 CI 見 #185 checks；本段舊 SHA 的成功不自動冒充後續 SHA 成功。
