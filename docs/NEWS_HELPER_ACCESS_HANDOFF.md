> 歷史交付／驗收快照：本文的版本及待辦不代表現況。請先看 [現行整合狀態與證據](CURRENT_INTEGRATION_STATUS.md)；保留原文供追溯。

# 02 → 06｜新聞使用權限及 Helper 約局概覽

日期：2026-11-15（Asia/Hong_Kong）。本文件是程式／唯讀核對交接，不是正式權限套用或真人驗收通過證明。

## 已讀交接與基準

- main `fa433dd80dd8dcf24313d06277e74e87d58b8f06`；最後一次 main Fly Deploy run `43601225924` 為 completed/success。這不等於目前程序／DB 已直接檢驗。
- Part 1 / 05：Draft PR #165，`feat/news-experience-settings`，`211cedbc66a93db0bcf0deb83ccfe148e5c254f9`，已讀 `docs/NEWS_EXPERIENCE_HANDOFF.md`。
- Part 2 / 03：Draft PR #166，`feat/signup-to-session`，`5ca1a9c90141c732ac60ec7cb493ee8be2612253`，已讀 `docs/SIGNUP_TO_START_HANDOFF.md`。
- 兩份交接均未合併／部署。02 分支 `codex/news-helper-access` 基於 main，沒有複製兩份交接的實作。06 必須整合三份後部署。
- 禁止直接合併這份 PR：main push 會自動部署，而且既有 workflow 包含新聞權限 migration。今次沒有改正式角色／頻道權限、沒有新增測試或正式 Discord 訊息。

## 新聞入口與權限矩陣

以下是預期權限模型及程式測試，**不是目前正式覆寫的完整快照**。

| 身份／選擇 | 對應新聞頻道 | 其他新聞頻道 | 讀摘要／按固定按鈕 | 發文字要求 | 取消全部後恢復 |
|---|---|---|---|---|---|
| 一般成員，選 PS | PS 可見 | Xbox／PC 隱藏 | View Channel＋Read Message History；程式不要求 Send Messages | 無 | Discord 頻道與身份組 |
| 一般成員，選多類 | 所選可見 | 未選隱藏 | 同上 | 無 | 同上 |
| 一般成員，全取消 | 全部隱藏 | 全部隱藏 | 改用區外入口 | 無 | 同上；亦有既有功能選單 → 資訊與設定 → 新聞頻道接收 |
| Helper | 完全跟自己選擇 | 不因 Helper 額外開放 | 同一般成員 | 無 | 同上 |
| Owner／Administrator | Discord 管理權可繞過頻道限制 | 通常可見 | 可操作不證明普通成員可操作 | 不適用 | 可開設定，但不能作一般驗收 |
| 有分類角色＋舊 no-news-sub 的 View deny | 同層角色 Allow 可勝出 Deny | 無其他 grant 時隱藏 | 若 History 另被 deny，仍可能讀不到摘要 | 無 | 需逐 bit 核對 |
| 成員個別 View deny／缺讀歷史 | 仍可被個別覆寫限制 | 同左 | 不可視為通過 | 加 Send 並不能修正 | 交 06 核對差異 |

`RSSDelivery.personal_access` 不檢查發言權、Helper 身份或管理權。既有 `NewsCardPanel` 以私人回覆提供我的情報／偏好。新聞頁可見與手機推播不同；沿用 05 分流，不將角色選擇與 RSS 個人偏好混合。

清空分類後，02 新增私人成功訊息中的 `<id:customize>` 恢復提示。既有 `NewsChannelView` 接受空集合，重新開啟不要求持有分類角色；原功能選單亦保留入口。Discord 原生「頻道與身份組」不依附任何 news channel。但不同手機版本下是否易找、功能指南頻道對普通成員是否可見，仍須真人驗收；不宣稱已通過。

## 舊角色：已確認程式依賴、影響及遷移

| 依賴 | 實際程式位置／現況 | 影響 |
|---|---|---|
| 權限整理工具 | `features/news_permissions.py::build` 以名稱識別 news-sub／no-news-sub | 只處理三個新聞頻道的 View bit；保留舊角色顯式 View deny及其他 bits；不是刪角色工具 |
| 新版分類選擇器 | `core/news_channel_ui.py` 只讀／增減 applied.json 所列三個零權限分類角色 | 不會刪舊角色或改遊戲角色；不寫個人 RSS 偏好 |
| 歷史新聞問卷 | `features/news_channel_categories.py::LEGACY_PROMPT`，`category_prompts` | 舊問卷 ID 1426676369567387826 若與新選項共存，遷移會阻擋；不能重套歷史問卷 |
| 舊問卷文案／語言配置 | `features/onboarding_wording.py`、`features/language_preferences.py::make_room_for_language` | 舊 ID 仍供歷史配置辨識；後者不會在舊題缺失時憑空建立新題 |
| 一次性 migration | `scripts/apply_news_channel_categories.py` | 依照當時可見性保留讀者，不單靠角色名稱；applied.json 存在時應 no-op。06 須先確認該檔案 |
| 正式角色持有人 | 本次 native profile 唯讀見 jeff_con9sole 同時持有 news-sub、新聞接收｜PS／PC | 證明舊新角色確實共存；不代表所有成員配置已核清 |
| 其他 Bot／全部頻道覆寫／完整成員數 | 尚無最新完整快照 | 不可推斷已無依賴，亦不可安全刪除 no-news-sub |

建議先保留 no-news-sub，不批次取消／重派任何人的分類。需要遷移時由 06：

1. 在私有環境跑 `python scripts/audit_news_access.py --live --member-id <一般測試帳號> --member-id <Helper測試帳號> --include-member-counts`。它只 GET，輸出全頻道相關覆寫、onboarding 引用、角色人數、指定帳號角色與 64 組模型；不發訊息、不改角色、不執行 migration。不要把輸出貼到 Tester／公開 PR。
2. 離線也可用 `--snapshot /private/snapshot.json`。快照 schema 包含 guild、roles、channels、onboarding、members（選填）；Discord snowflake 全程使用原始十進位字串／Python int，禁止經 JS Number 重寫。
3. 核對其他 Bot 的 reaction roles、auto roles、問卷與整合設定；Discord GET 無法得知它們的外部設定。
4. 若有實際差異，逐項列出 channel ID、target ID、allow/deny before→after；只修正已確認錯誤 bit，保留其他 bits、排序、分類及成員選擇。先備份；套用前重新比對快照，變動就停止。
5. 不因分類清空而移除 no-news-sub，也不把 news-sub 一律轉成全選。沒有可靠個人意願時保持現狀。
6. 回復按同一覆寫的 before 值且只在 current==after 時執行；手動變更衝突就停止。角色不要刪除：刪除後無法復原原 role ID 及外部引用。日後若確定要淘汰，先停用依賴、保留角色觀察，再另案決定。

**本 PR 正式權限差異為空；沒有需要 Jeff 批准的新權限 grant，也不要求 Helper 全區權限。** 精確 live 差異尚未取得，不能虛構 before/after。05 提出的分類改名仍為獨立待決事項，並非本 PR 必要條件。

## Helper Dashboard 行為與資料界線

- 在原有 HelperPanel 加持久按鈕 `helper:plans:v1`，在原 embed 增加「待開局／招募未滿」欄位。沿用原 2 分鐘 refresh、原 channel/message ID、`message.edit`；沒有新增排程、DM、ping 或約局報告訊息。
- 共用約局欄只顯示可公開來源的合計數，不顯示遊戲自填文字、模式、頻道、成員、名單、提醒意願或其他隱藏來源的數目。
- 公開來源保守定義：@everyone 可 View＋History，且任何 role/member overwrite 均沒有這兩項 deny。私密 thread 排除。只因 Bot／Helper 看得到不算公開。既有共用文字／語音欄亦加同樣可見性限制（語音需 View＋Connect），因此受遊戲角色限制的活動可能從共用板減少；私人原權限不變。
- `open/due/gathering` 且未逾原 deadline → 待開局；`open/due/gathering/live`、明確 capacity > party+confirmed registered → 招募未滿。兩類可以重疊；capacity 未設定不猜缺額。取消、逾期、歷史、結束及未成功貼卡者不列入。報名與發起時已有的人數不等於到場數。
- 私人按鈕每次 fetch_member／fetch_channel 重驗 Dashboard 的 Helper／既有 Tester／Admin 資格及 View＋History，再逐局呼叫 03 `SquadPlans.member_status`。只讀結果；無 Helper 編輯、取消、加入或管理捷徑。回原卡做操作，由原 handler 再核權。
- 選擇／刷新使用同一私人回覆 `edit_original_response`；撤權、離群或 source 變動會清除舊 embed／原卡連結。面板綁擁有人，沒有可見約局時提供 `<id:customize>` 遊戲引導，不代派身份組。
- 私人每次按開始時間最多檢查 50 筆、顯示 10 筆；不展示隱藏／未掃描總數。大量活動時可能省略可見約局，原卡仍是完整入口。來源變更期間拒絕舊快照，不聲稱零延遲。
- 03 介面尚未部署時顯示「概覽暫未就緒」；不退回讀 raw 名單。05 與02改動可獨立整合；02僅在清空成功訊息補提示。
- 舊 Helper pulse 定時活動訊息本來已存在，本次 native UI 見到既有紀錄；本 PR 沒有增加、刪除或停用它。它的跨區發布政策是另一個既有風險，不應把原位 Dashboard 更新當成已清理整個頻道歷史／pulse。

## 實際帳號與唯讀驗收

本次在 Chrome 使用現有 jeff_drlecter session；只讀頻道／native profile，沒有按 Bot 功能產生測試回覆、沒有更改選擇或角色。

| 身份 | 實際帳號／角色 | 本次操作及結果 | 未驗證 |
|---|---|---|---|
| Admin／Owner | jeff_drlecter；Server Owner；Mod、Lv 15 活躍會員、off-topic、GTA、GTA-VI Player、語境偏好｜香港 | PS 固定卡可見，原三按鈕存在；可讀 Helper 頻道；native profile 核對角色 | 本 PR 尚未上線；本次未點 Bot 按鈕。Owner 可繞過限制，不代表普通成員 |
| Helper | jeff_con9sole；Helpers、Verified👤✅、🧪 Tester、news-sub、新聞接收｜PS／PC、語境偏好｜香港；另有 PS黨、EA FC、EA FC27 Player、GTA、GTA-VI Player、Lv 30 常駐會員、非直播、遊戲直播區、酒譜收藏家 | 由 Admin 唯讀檢視 native profile；未見 Xbox 分類或 no-news-sub | 未登入此帳號操作；不能當 Helper 實測通過；亦有 Tester，需另驗只有 Helper 的情境 |
| 一般成員 | 未提供／未登入獨立測試帳號 | 無實際操作；僅離線角色模型 | 全流程、零分類回復、iPhone 均未驗證 |

之前 #164 Admin 測試成功是歷史證據，不拿來替代本輪普通成員／Helper 驗收。正式 read-history、所有 legacy dependencies、目前 DB freshness、日排程首份摘要亦待 06 核對。

## 測試與 06 整合

- 獨立 main 基線：784 tests，OK，1 skipped（03 未合併；其真實 member_status 合約測試刻意跳過）。
- 測試涵蓋：64 種新聞角色組合、legacy View／History／member override 差異、Admin bypass、空分類恢復提示及區外重開、不改遊戲／舊角色、共用 hidden-source 排除、資料最小化、到場未知、撤權／角色移除／其他擁有人、API介面缺失、並發 source 變動，以及原 message.edit 不新增訊息。
- 本地整合 #165 `211cedb`＋#166 `5ca1a9c`：無合併衝突，798 tests 全部通過（沒有 skip）；包括真實 03 member_status 的唯讀／缺讀歷史／失去驗證拒絕。compileall 與 git diff --check 通過。本地整合分支只供測試，不會推 main 或部署。

06 部署前須重新核對三個 PR head SHA，跑完整整合測試；確認 `/data/news_channel_categories/applied.json` 仍存在且 migration no-op，並備份 helper DB、RSS 偏好及 03 指定資料／收據。記錄 Helper `dashboard_panel`、`dashboard_channel` 及原 embed/buttons。部署後只原位更新舊看板；缺 message ID／reserved／404 時停止並人工核對，勿清空狀態迫使重發。

回復：撤回02程式後沿用同一 message ID 更新為舊 embed／view，移除新按鈕。無資料庫 schema 變更、無角色回復；保留所有 RSS 偏好及03通知收據。短暫 Bot 重啟可能影響語音追蹤、持久按鈕重新註冊、短效私人面板；由06統一觀察，不能承諾零中斷。保守共用範圍回復會重新露出舊摘要政策，須明確評估。
