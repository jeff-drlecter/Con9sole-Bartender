> 歷史交付／驗收快照：本文的版本及待辦不代表現況。請先看 [現行整合狀態與證據](CURRENT_INTEGRATION_STATUS.md)；保留原文供追溯。

# 06 本輪整合及分階段驗收（2026-11-15，香港時間）

> **2026-11-15 狀態校正：** #170 已於 fede4d7 部署（43634179965 success）；#171 已於 2922760 部署（43635343478 success）。Jeff 接受該輪角色預覽＋Helper 實測的有限放行；一般成員寫入等未驗項未因此變成通過。以下為部署前歷史快照。 本輪完整現況／待決／驗收界線以 [COMMUNITY_ROUND2.md](COMMUNITY_ROUND2.md) 及整合 PR 的部署證據為準。

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
本輪部署前 image／回復目標：`registry.fly.io/con9sole-bartender:deployment-01M7D4TQZWYNRY9Y0ANF2ZXKMR`，digest `sha256:5e210fc5e07cc4b5d14e8942bcbfecd22966a4a56c2c8689d579323b5e28b17c`。
這是歷史工作流程證據，不是現在的 Fly 程序／資料新鮮度證明。部署前須重讀狀態，若有其他新 main 先重新整合。

### 本輪正式部署證據

- 階段 1 [PR #169](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/169) 已合併；head `5902918293c0ba9bd2c790e1d086437d791dc5e1`，實際 main／部署 commit `053b3e404b8705dc0d7c239f3116ecc277798463`。GitHub 發布前 CI `43627780043`／`43627776162` success。
- [Fly Deploy 43627962077](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43627962077) completed/success；2026-11-15 02:41–02:43 香港時間。image `registry.fly.io/con9sole-bartender:deployment-01M7DNV5MKY154VGG3S2YCB7RS`，同一 machine `9080d6d9a9d168` 通過 health checks。
- 部署前私有備份 `20261114T184145Z-42e04faa17da4128a57fb4ee7fd0153e`；49 個資料檔案／store，ready=true、target=上述部署 SHA、restore_check=passed。實際執行過逐 store 還原讀回；未進行以舊 image 回復服務的破壞性演練。
- 只讀 migration marker 在部署前後均通過；未執行權限 migration。部署後 publisher 三目的地、持久隊列、member 指令、偏好 DB、Helper 既有面板／角色覆寫模型、非 root UID/GID 10001、Twitch credential／roster／command 檢查通過。這些都不等於普通成員操作。
- Store source 實際檢查有 22 篇 news、1 個已核實 offer；public_browsing_enabled=false、automatic_store_notifications=false。交接中「offers={}」屬歷史資料，不能當現在狀態。
- 2026-11-15 02:43–02:44，現有 Chrome 帳號 `jeff_drlecter`，畫面以 Mod 分組並顯示 Server Owner；私人 HK 文案。從既有 PS 卡「調整偏好」打開新情報設定，再打開「個人情報篩選」，顯示 Only you can see this、分流說明／19:00／上限 8 篇正常。只讀開面板，未選擇選項、未改任何身份組／偏好，未發公開文字或測試通知。
- 一般成員、Helper-only、iPhone 不在此輪可用登入 session；不得把上述 Owner 結果當通過。階段 2／3 停在此關卡。

## 分批順序及關卡

1. `codex/round-20261115-news`：05 新聞改善、只讀遷移核對、部署前私有備份。新聞設定／來源／推送規則沿用既有授權。
2. `codex/round-20261115-squads`：03＋02；必須先取得階段 1 一般成員新聞驗收，不能以 Admin 代替。
3. `codex/round-20261115-integration`：04＋06 主選單及導覽；必須在階段 2 驗收後才部署。

階段 2 [Draft PR #170](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/170)，head `5e65c5018d70b9d089db5b0e679ebb5693ef9c0e`；程式樹 `270a8d74971fc0413c7b08e17729f0755352f3d8` 與本地測試一致。階段 3 交獨立 Draft PR，以該 PR head／檔案 blob 核對最終版本。原 #165–#168 保留交接，不再直接合併觸發混批部署。

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
| RSS 設定分流及舊新聞按鈕 | #169／053b3e4 | 787 項完整 unittest、GitHub CI、部署檢查通過 | 053b3e4／上述 image | jeff_drlecter，Owner／Mod，HK 私人設定及篩選入口通過 | 一般成員、Helper-only、iPhone、三頻道真人互動、19:00 新摘要 |
| 新聞遷移保護／私有備份 | #169／053b3e4 | WAL／JSON／隔離還原、拒絕錯誤等離線＋正式通過 | 053b3e4；49 stores 備份已完成 | 不涉及成員操作 | 舊 image 回復服務未演練、非跨 store 全域快照 |
| 約局／足跡／一次及長期提醒 | #170／5e65c50 | 階段 2 完整 802 項、最終整合 819 項通過 | 未部署；正式仍 053b3e4 舊約局行為 | 無新版真人操作 | 階段 1 成員關卡；語音、退出／撤回、收據及重啟現場驗收 |
| Helper 概覽／新聞權限盤點 | #170／5e65c50 | 同上，含 64 種角色模型；不等於正式權限 | 未部署；正式仍舊 Dashboard | 本輪無 Helper 登入操作 | Helper-only、完整 live overwrite 快照、外部 Bot 依賴 |
| 私人成效統計／EXP | 階段 3，04 源 38c975c | 最終整合 819 項通過；未改 XP／倍率／稱號規則 | 未部署 | 無新版真人操作 | 正式涵蓋日期、測試污染、Admin／Helper 拒絕及觀測出席 |
| 主選單／語言／舊訊息按鈕 | 階段 3，menu_registry blob 18d987d9f2161e7ee7430e03d292d9e3b1949e15 | 最終整合 819 項、compileall、diff check 通過 | 未部署；正式仍舊主選單 | 新版無真人操作；只有階段 1 HK 設定已實測 | iPhone／電腦可讀性、舊卡、實際角色偏好、返回路徑 |

本輪未取得可登入的一般成員／Helper-only 驗收 session；既有 Owner 畫面不替代。實際角色未在本輪重新核實時，不挪用歷史角色當作本輪已驗收身份。

## 繼續工作：新聞一般成員驗收

續查 main 仍為 `053b3e4`，#170 head `5e65c50`／#171 程式 head `f76fd44` 均未合併。此次只有驗收交接文件更新，未新增程式測試、未部署、未新增 Discord 實測結果。現有 819 項程式測試與 CI 屬 `f76fd44` 的證據；文件更新不冒充新的執行證據。

目前未提供可控制的 Discord 瀏覽器入口，不能檢查是否另有一般成員登入 session；不能據此宣稱帳號不存在，也不改用其他瀏覽器繞過登入或權限。下一步需要可控制、已登入指定一般測試帳號的 Discord 分頁；毋須提供密碼、Token，亦毋須調整正式角色／頻道權限。

### 簡短操作

1. 用已驗證的一般測試帳號，開啟自己已選擇的新聞頻道，按原卡「我的情報」及「調整偏好」。只開私人面板，不輸入聊天訊息。
2. 到「個人情報篩選」，記錄原選項後測試儲存／重開，確認只影響「我的情報」，沒有更改新聞頻道顯示。完成後恢復原篩選。
3. 用同一測試帳號的「顯示新聞頻道」測試全取消，再由 Discord 原生「頻道與身份組」恢復原選擇。記錄頻道實際出現／消失，以及與個人篩選互不影響。這是測試帳號既有自選功能，不是修改正式權限設計；不直接派／移除其他角色。

以下逐項留待現場填寫，不以 Owner、API 模型或其他人的口頭結論代簽。測試者帳號、實際全部角色及有效權限核實前，任何項目不得標「通過」。角色證據只保存在私人交接，不把完整成員快照或私人畫面放公開 PR。

| 驗收項目 | 通過條件 | 結果／證據 |
|---|---|---|
| 身份及環境 | 記錄測試帳號、已驗證身份、裝置、Discord 版本及時間；沒有 Owner／Administrator／管理員／Helper 或其他測試區繞過權限 | 未實測 |
| PS 固定入口 | 已自選 PS；可讀原卡、開私人情報與設定；不需發文字訊息 | 未實測；channel 1364201334798290994 |
| Xbox 固定入口 | 同上，按成員自己的 Xbox 選擇驗證，不用 Admin 可見性代替 | 未實測；channel 1379699174668505098 |
| PC 固定入口 | 同上，按成員自己的 PC 選擇驗證 | 未實測；channel 1364210080043630612 |
| 唯讀頻道操作 | 有 View／History、沒有 Send Messages 時仍能按按鈕；若帳號可發言，該次不能證明此項。不為測試更改正式覆寫 | 未實測 |
| 私人結果及用語 | 回覆為 Only you can see this；香港／台灣／未選語言各按實際選擇驗證，沒有把共用原卡改成個人用語 | 未實測 |
| 篩選持久讀回 | 選擇可重新讀回；公開摘要、頻道顯示及手機推播設定未被連帶改動。重開面板不等於 Bot 重啟驗收 | 未實測 |
| 全取消與恢復 | 全取消後三頻道隱藏；從區外原生入口恢復原選擇；遊戲／舊新聞角色沒有被額外清除 | 未實測 |
| 返回及手機閱讀 | 既有正式版可回原卡或原生入口；iPhone 另作實機操作，不以桌面縮窄視窗當 iPhone 通過。#171 新返回按鈕尚未部署，不能拿來驗階段 1 | 未實測 |

一般成員的互動關卡未通過前，#170／#171 繼續保持 Draft。Helper-only、正式完整覆寫、19:00 新摘要、真實語音及 Bot 重啟前後資料均維持各自的未驗證狀態；完成其中一項不自動勾選其他項。即使解除新聞關卡，下一批部署仍須重新核對最新 main／PR head、新備份及回復目標，不能重用上一批備份當作最新。

## Jeff 待決項目（不混入程式部署）

| 提案 | before → after | 可用證據／執行條件 |
|---|---|---|
| 05 新聞分類名稱 | category `1424877575850692719`，name `📡📡 - 即時情報站 - 📡📡` → `📡📡 - 遊戲情報站 - 📡📡` | 本輪由 Discord sidebar DOM data-list-item-id 及 aria-label 唯讀核實 ID／原名。精確提案只改 name；不改 parent、position、permission_overwrites、子頻道或 ID；回復原名。尚未取得完整覆寫快照，套用前另行核對；本輪未執行 |
| 02 角色／頻道權限 | 本 PR 提出的正式差異為空 | 不刪 no-news-sub、不增 Helper 全新聞權限；如 live audit 發現差異，再列 channel、target、allow/deny before→after 交 Jeff 決定 |

## 文件時效

docs/RSS_DELIVERY.md、舊測試摘要與歷史 acceptance 是累積歷史，涉及 MonitoRSS 仍派送／尚未正式取代等文字可能已過時。正式規則以本輪版本的 fly.toml、docs/rss_production.json、實際程式及最新部署證據為準。
四份 HANDOFF 保留原始交接，不把其中「未部署」視為永遠最新；本表需隨每批證據更新。Steam／Epic 仍 STORE_NEWS_PUBLIC=0，不藉本輪轉正式推送。

## 06 主選單與未完成整合

四行每行兩個：約一局／小隊語音；我的會員卡／我的組隊通知；飲一杯／請人飲；更多／語言設定。私人面板按成員港台語言，未選使用中性繁中。今日任務從會員卡或更多進入；房控從語音建立／房間相關面板進入。舊 quick/home IDs 持久註冊，包含移走的任務、房控及邀請；無新佔位按鈕。

通知尚未形成一個同時編輯「本局同意」與「遊戲訂閱」的統一面板，故保留準確名稱「我的組隊通知」，管理一次／長期遊戲訂閱；本局提醒從原約局卡管理。主選單已明確說明分工，不把新聞選項或情報篩選稱作手機推播設定。情報設定／篩選加返回路徑；舊公開固定卡文字保持不重發，新 code 能接收舊按鈕。

公海入口已移除過時的獨立入群題目提示，改用現行原生頻道與身份組入口；私人引導按港台語言，拒絕時不代派角色。

回歸包含真實 discord.py 離線 extension load/reload、所有 registry routes、舊卡、去重／uncertain 收據、RSS、角色語言持久選擇、XP、Helper 拒絕與最小資料。程式模型通過不證明實機手機可讀或正式外部 Bot 設定；未驗證項不移除。
