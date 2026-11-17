# Con9sole 現行整合與驗收總表

## 2026-11-17 整合發布索引

使用者已在本輪明確要求「合併同部署」。本次只整合 #193（`317f499403930f1c6e68871032f2d0083683068b`）、#194（`b0477e8e5930389a602ca4aa89e5e7837499b15f`）、#195（`405ffadf84a992f7d4a2b927642eb898fad40002`）、#196（`f192d0c3ed3d485651f97d04fff0867b09cfe48f`）及 #198（`fb202e7bdbd6ed19b244d1d4edb057475dc0a31f`），不納入四個大版本升級。

本節是發布前的版本清單，不預稱已部署。精確 release head、最終 CI、main SHA、部署流程及讀回結果集中於 [#197](https://github.com/jeff-drlecter/Con9sole-Bartender/issues/197) 與 [本次 release PR](https://github.com/jeff-drlecter/Con9sole-Bartender/pulls?q=head%3Arelease%2F20261117-growth-and-codex)。沿用現有 idle／delivery、單機、備份讀回及 runtime SHA 閘門；不新增 Bot 程序、不改正式 Discord 設定、不發布六篇內容草稿或公告。真人 UI、05 cohort 接口及 Codex 模型 metadata 限制不會因部署而自動變成通過。

下方及來源候選文件的「不合併／不部署／維持 Draft」屬授權前歷史；本輪合併部署授權以本節及 release PR 證據為準，不擴大為其他正式操作授權。

## 2026-11-17 待辦整理（本節為此次核對狀態）

核對 main 為 `9565192ac5d9027b1468b51efc7108a8f3c57388`（#192）；對應 [Fly Deploy 43898217858](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43898217858) 成功。這是已存在的部署紀錄，本次整理沒有重新部署或聲稱即時健康驗證。

待辦、已關閉來源 PR、續作版本及尚未通過的條件統一記錄於 [#197](https://github.com/jeff-drlecter/Con9sole-Bartender/issues/197)。#165–168、#181–187 已按歷史整合／規格取代證據關閉，不再因 Draft 狀態重播。#133 舊語言方案、#18 舊依賴檔更新及 #1 流程測試亦已整理關閉；原提交、分支及驗收限制保留。

#193 統計、#194 草稿、#195 驗收工具、#196 Codex 配置仍是獨立候選；tempVC 未知頻道型態排序及 audit null target 修復亦須以其 PR 的固定 SHA／CI／06 驗收為準。本節不批准合併、部署、改正式 Discord 或發布內容。下方「現行／最新／未部署」字眼均屬其標示日期的歷史快照，不能取代 #197 的續作紀錄。

## 2026-11-16 12:23 香港追加狀態（本節優先）

[修正 #189](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/189) 已部署，現行 runtime/main 為 `71d894169cd117981ed106806eb9aad293b70a99`，tree `abdca81b0c86df53a32c1bfb8753f5b8cfd12717`。[部署 43802653201](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43802653201) 全部成功；04:14:15 UTC 讀回 commit。PR CI `43802479453` 與部署 pipeline 均通過 962 tests，前者亦完成依賴審核與容器檢查。

新備份 `20261116T041343Z-d897a48feca84f4db738fb33c808d09d`，65 stores，回讀通過；仍是同一 machine／volume。更新前兩次持久活動／交付盤點均空閒，origins 欄位已存在；EXP、偏好及收據保留。這次小修的回復 image 是 `registry.fly.io/con9sole-bartender:git-87dc4569606ea6806ff2e4a6fa1136791815d343`，只回程式、不恢復舊資料。

| 最新實測／修正 | 已核實結果 | 限制與下一項證據 |
|---|---|---|
| 草稿取消逾時 | #189 已部署；同一 Helper 帳號 12:16、12:22 均顯示草稿已取消 | 保留 12:01 舊版失敗紀錄，不能抹成一直通過 |
| 成局／最高人數表單 | 12:16 及 Tester 區 12:22 實際改為成局 2、最高 4 | 發現改人數會重新開啟自動活動；後續修正保留手動選擇，見[修正 PR 最新結果表](https://github.com/jeff-drlecter/Con9sole-Bartender/pulls?q=head%3Afix%2Fpreserve-draft-event-choice)；未有該版部署與重測前不算通過 |
| 自動活動／報名提醒開關 | Tester 區私人草稿分別關閉成功 | 未發公開約局、Event 或測試提醒 |
| 舊足跡卡再約 | Tester 區 11 月 13 日原卡按「發起下次」成功帶入測試遊戲／卡片流程測試，並建立可取消私人草稿 | 不代表報名→語音→結束的完整真人流程通過 |
| Helper 健康頁 | 12:12 基本狀態、返回入口可見；管理員專用新聞／直播詳細區未顯示 | 撤權／來源失效及 Admin 詳細區未真人驗證 |
| 主選單及 HK | 重啟後新選單成功，文案指向統一通知中心；HK 偏好保留 | TW／中性仍只有程式回歸，未真人切換 |

Jeff 追加要求所有後續測試在 Tester 區，並明確授權目前帳號加入 Tester。12:20 透過 Channels & Roles 的「社群測試區」自選入口，已為 `jeff_con9sole` 新增 `🧪 Tester`；前後 profile 核對其餘角色不變（包括 Helpers、Verified、HK 和既有遊戲角色）。正式實測身份現在是 **Helper＋Tester**，不是純 Tester 或普通成員。未改角色定義／頻道 overwrite。現用 `體驗交流💬` 頻道 `1564479770014785577`；普通區未發布測試卡、訊息或通知，之前僅私人 ephemeral 草稿，已取消。

## 2026-11-16 首批 release 證據與分項範圍（部署版本以上方追加為準）

首批正式版本由 [release #188](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/188) 部署，main/runtime commit 均為 `87dc4569606ea6806ff2e4a6fa1136791815d343`。下方舊段落中的「未部署」、登入阻擋及舊 main 均為歷史快照。#181–185、#187 的內容已整合於 #188；#165–168 亦已經歷史整合，不因 PR 仍 open 再次合併。所有後續驗收修正及最新 runtime SHA 以[草稿回應修正 PR 的現行結果表](https://github.com/jeff-drlecter/Con9sole-Bartender/pulls?q=head%3Afix%2Fdraft-response-timeout)為追加證據；該次版本已由上方 #189 追加證據更新；下列表格保留首批驗收快照。

### 程式、部署與保存證據

- Release head `18c6315c5441850fc9b578967b615feb0041237f`，tree `c99a8eca8556bbcd2ea248edfad9251333f4ee06`；與 squash main 的 tree 相同。
- [PR checks 43800075668](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43800075668)：955 tests、編譯、hash-locked dependencies、pip-audit 無已知漏洞、容器建置／私檔排除／非 root／持久卷檢查均成功。
- [正式部署 43800236045](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43800236045)，job `133078464723` success；正式 pipeline 再跑 955 tests。03:49:32 UTC 讀回 APP_COMMIT 與 main 完整 SHA 一致。
- 同一 machine `9080d6d9a9d168`、同一 `/data` volume `vol_r688z3eko3nnmln4`；新 image `registry.fly.io/con9sole-bartender:git-87dc4569606ea6806ff2e4a6fa1136791815d343`。沒有第二 Bot。
- 部署前新備份 `20261116T034859Z-1da5e057d6f34f309b38c0a048de2f36`，65 stores，backup_ready/restore_check 通過。這是逐 store 一致性備份，不是跨 store 原子快照或異地備份。
- 03:48:47／03:49:03 UTC 盤點：持久 active plans／voice sessions、待發／不明收據、卡片 posting／語音嘗試、Event／發起人通知未解決狀態均未發現。是 Bot 持久資料盤點，不能冒充即時 Discord 語音原子快照。
- 啟動、recent observer、資料庫完整性、plan readability、RSS／store／Helper sandbox／community health 均通過；EXP 政策與既有通知收據保留。Twitch ready、指令同步成功；沒有為驗收向成員發通知。

### 目前逐項狀態

| 範圍／成員可感受到的改變 | 程式來源 | 已檢查／已部署 | Discord 真人驗收與限制 |
|---|---|---|---|
| 02 私人名單每次重查權限；統一管理本局與遊戲通知 | #181 + #185 整合修正 | 955 項整合回歸涵蓋；87dc456 已部署 | Owner、Helper 均開啟通知中心成功；撤權、他人操作及原卡／中心實際切換尚未真人驗證 |
| 03 探索現有約局、快捷欠人、私人草稿、失效卡 | #182 + #185 | 87dc456 已部署 | Helper 探索空清單、刷新／返回、欠 2 人摘要及取消即玩草稿成功；未發布測試約局 |
| 03 達成成局人數後建立 Discord Event；可關閉活動及報名提醒 | #187 / 5083b771ae39caae13a6f568984485c08ab7e775 | 87dc456 已部署；持久意圖、未知結果不重播及來源範圍回歸通過 | Helper 未來約局摘要預設 3 人成局，兩個開關可獨立切換；未真人建立 Event、發送提醒或進行語音局 |
| 03 未來約局草稿取消逾時 | 87dc456 UI 實測發現 | 修正分支先回應再 REST；取消不讀 REST；962 tests、compile、diff check 本地通過；尚需該修正 CI／部署／真人重測 | 12:01 香港出現一次「didn’t respond in time」，保留失敗紀錄；不能算通過 |
| 一次／長期／本局同意獨立、同局去重 | #181+#182+#185 | 87dc456 已部署；隔離舊未分類 receipts | 不發測試通知；真人去重與取消後交付仍未驗證 |
| 04 首次觀察、D0／D7／D28 再參與與缺漏標示；不改 EXP 政策 | #183 / bce72fc88d522912b7fd69d3596a893032240346 | 87dc456 已部署；日界、成熟分母、排除測試及獎勵回歸 | 正式報表／真實角色拒絕仍未驗證；不宣稱社群成效改善 |
| 05 新聞／直播取得與交付分開；未知與失敗可見 | #184 / 78a799820074439cbfe84a7745e5f4f4ea1521a2 | 87dc456 已部署；健康檢查成功 | 普通成員新聞、Helper／Admin 健康頁完整邊界及外部失敗恢復未真人驗證 |
| 主選單、HK／TW／中性、舊卡、偏好保存 | #185+#187 | 87dc456 已部署；回歸包含語言與舊 custom ID | Helper HK 在服務重啟後仍顯示；TW／中性真實操作、舊卡全矩陣未驗證；主選單舊說明另於修正分支更新 |

### 實際帳號與操作

| 身份 | 已核實帳號／角色證據 | 本輪實測 | 未驗證 |
|---|---|---|---|
| Owner／Admin | `jeff_drlecter`，Server Owner badge；成員列表 Mod | 私人 /menu、通知中心、本局提醒空清單 | 不代表普通成員或 Helper；全角色組合未重新盤點 |
| Helper | `jeff_con9sole`，顯示家用夠の姐夫，成員列表 Helpers | 11:57–12:01 香港：/menu、約局探索／刷新／返回、即玩草稿取消、未來草稿與獨立開關、通知中心開啟 | 未來草稿取消出現逾時；沒有公開發起或送出測試通知；沒有以 Helper 代普通成員 |
| 普通成員 | 未核實獨立普通成員登入 | 無 | 全流程仍未驗證 |
| Tester | 未核實獨立 Tester 登入 | 無 | 全流程仍未驗證 |
| iPhone | 按 Jeff 指示略過 | 無 | 略過，不算通過，不阻擋部署 |

### 回復與剩餘事項

本次只改程式，沒有角色／頻道權限、排序、改名、公告或 Tester 通知。沒有以成功的程式測試取代真人驗收。02／05 原建議的正式權限或改名仍需 Jeff 審閱精確差異，並未混入部署。

後續小修優先回到已部署的 `git-87dc456...` image，保留同一 machine／volume 與所有當前資料；先重新檢查活動及收據，再使用現行 workflow 的單機限定更新。**不要還原舊 DB／JSON／EXP／偏好／通知收據。** 本輪之前的歷史回復 image 為 `deployment-01M7F6E9RBKN6MKG3VJG3RJ4C6`；若已有 linked Event、未知交付或隔離 receipts，不能直接全版回退至缺少同步器／新 dispatcher 的舊程式，需保留該模組或逐項安全收尾。未執行實際 rollback，不宣稱回復演練通過。單 Bot 更新與 ephemeral 面板可能短暫中斷，應從原卡／/menu 重開。

## 歷史紀錄（以下全部保留，不能覆蓋上方現行證據）

> **2026-11-16 部署執行更新（本段優先；下文保留歷史）**：Jeff 再次明確要求部署並允許切換帳號。正式 release 候選包含 #185 的四項整合與 #187 的 03 Event／發起人提醒。#187 head `5083b771ae39caae13a6f568984485c08ab7e775` 已通過 950 tests、鎖定依賴審核及容器檢查（PR CI `43743363310`）。新 release 另加入正式 workflow 的強制單機／持久卷／idle receipts 與活動檢查、近期 observer 健康、備份回讀及實際 commit 核對；最終結果以 release PR／本次 Actions 為準，不能用上一 SHA 的結果代替。正常合併授權 release 到 main 後，production job 在更換機器前執行關卡，失敗就停止；production environment 及 main required `validate` 均保留。舊段落「未合併／未部署／沒有進入 main」僅是當時狀態，不能凌駕後續執行證據。
>
> Chrome 已看到 `jeff_con9sole`，但顯示「Please log in again」，已打開登入頁等候 Jeff 完成；目前仍是 `jeff_drlecter`，未以它代普通成員通過。所有未完成身份矩陣保留未驗證；iPhone 繼續略過。
>
> 部署先只建 image、不啟動 Bot；盤點及新備份成功後，只更新已記錄的單一 machine，`--ha=false --update-only --only-machines`。build fallback 不再重跑結果未知的部署。部署後核對 `APP_COMMIT` 與 release SHA、唯一機器及既有健康檢查。兩次 idle 盤點之間服務仍在線，並非原子鎖；語音與按鈕仍可能短暫受重啟影響。回復必須保留現行 `/data`，已有 Linked Event 或未分類收據時按下文保留新同步器／dispatcher，不直接回舊 image。

> 03 追加候選（2026-11-16）：Jeff 已要求部署最新 03 設計。#186 `4315ef7` 僅為規格；本 `feat/confirmed-plan-events` 分支新增成局 VOICE Event、發起人報名提醒及持久交付保護，依賴下述 #185 `9a53a22`。完整新增狀態／接口／資料／回復見 [03 追加交接](PLAN_EVENTS_HOST_NOTICES_HANDOFF.md)，精確 head／CI 由本分支 Draft PR 記錄。以下 #185 的 918 tests 等證據是基線，不當作本候選通過。正式版本、真人驗收與放行阻擋仍未改變，沒有部署新功能。

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
