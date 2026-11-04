# Con9sole-Bartender 全功能審核 — 2026-11-04

## 本次整合實作狀態（PR #42）

本節優先於下面原始審核發現。下方保留問題形成時的證據；不代表仍全部未修。

| 項目 | 本次處理 | 邊界／保留 |
|---|---|---|
| F01 | 統計寫入改為有上限的非阻塞工作；主要查詢先回應並在 worker 執行；Role ID 查詢與單人操作先回應 | 個別歷史 UI 的同步讀取可再收口；沒有宣稱所有 I/O 均已背景化 |
| F02 | 告白檢查原頻道發言權；固定目的地失效不改往其他頻道 | 目的頻道實際權限需現場驗證 |
| F03 | 保留現有常用 account／Helper 用途 | 專屬 User ID 未提供，未猜測或重設授權 |
| F04 | guild 級序列鎖、防同名、名稱驗證、建立時私有覆寫、逐 Forum tags、本次新增資源 ID 錯誤回報 | 不自動刪除部分建立資源，避免誤刪使用中的內容；fallback 少用分支仍需現場驗收 |
| F05 | 收藏榜統一使用 drink_collection，保留 legacy 所有權 | 舊 event 不重寫 |
| F06 | schema 按實際 DB 檔案初始化一次；壞 cooldown 逐筆保留正常值並備份原檔；JSON 寫失敗清 temp | 未刪歷史 event；完整 JSON 寫入合併／過期 map 清理仍是後續效能項目 |
| F07 | 今日統計按香港午夜；最近七日標籤明確 | 每日任務保留 UTC，等待舊完成紀錄的轉換策略 |
| F08 | 活躍組隊卡 dirty 更新加入既有 sweeper 重試 | 不重複建立卡片 |
| F09 | 開房共用跨 Cog lock；舊 Cog 卸載後等待者停止開房 | 未自行設定新房數上限；已有在途 API 操作不強行取消 |
| F10 | 設定及暱稱變更加入 dirty/display 比較；成功 render 才清 dirty | ModePicker 的 Modal 路徑仍沿用現有鎖；頂層 schema 完整遷移尚未加入 |
| F11 | 排程用物件/ID 快照、不再依賴會移位的 index；刪除時段忽略；名稱/空星期/重複時段/時段數驗證 | 模糊網絡成功時不保證 exactly-once |
| F12 | Publisher 編輯/發佈/取消狀態與 revision；舊 Modal 拒絕；編輯長度再驗證；禁止通知；批量角色 slash 共用確認、名單變更重開預覽 | 草稿跨重啟保存未實作；確認後至批量完成間仍可能有新成員變動 |
| F13 | 串行發送及重連、最多100等待者、使用正確 connection 狀態、Unicode 位元組分段、正常日誌不記全文、未送出失敗解除去重 | 使用 TwitchIO 既有連線維護；部分分段成功後不自動重播以免重複 |
| F14 | 稀有度收藏加入前後分頁及頁碼 | 最近解鎖維持最近12款；沒有改酒譜、機率或稱號規則 |
| F15 | 核心模組缺失拒絕啟動/同步；production /data mount 檢查；CI job15分鐘/test120秒上限 | 真正 Discord readiness、Fly metrics、billing 與還原演練需要線上證據 |

新增15項行為回歸，連同原有測試共177項通過。機器 CPU/RAM、機器數及付費服務未增加。
這是整合修正版本，並非宣稱所有審核項目均已百分百關閉；需身份、產品遷移策略或線上權限的事項在上表明列。

## 範圍及結論

基準：已部署 main `23e2942`；另檢查待合併 PR #42 `43f9c27` 的恢復修正。
檢查範圍包括全部 18 個非空／相容 Cog、features、core、utils、config、選單 registry、資料清單、測試、Docker 及 GitHub/Fly 設定。這是源碼與離線驗證，不等同線上功能驗收。

結論：功能已相當完整，重點是統一回應時機、管理操作狀態及資料口徑。繼續沿用單機 SQLite；沒有證據支持加機、升 RAM 或引入外部資料庫。162 項現有測試通過，仍不能涵蓋以下全部邊界情況。

本報告一次過列出已知問題與方案；不以「測試全部通過」代表全部功能沒有問題。

## 全功能盤點

| 模組 | 檢查內容 | 結果／關聯項目 |
|---|---|---|
| menu | slash、提及、舊按鈕、快捷／主頁／管理頁、身份隱藏、缺 Cog 回應 | 路由有測試；F01、F13 |
| drink | 自飲、賜酒、選人、機率、冷卻、發送後記錄 | 發送失敗不扣冷卻；F01、F05、F06 |
| 收藏、里程碑、主題（Drink 支援功能） | 所有權、舊資料補計、3 張主題酒單、私人通知、追蹤、稱號、稀有度、最近收藏 | 交易及稱號所有權有測試；F05、F06、F14 |
| cheers | 自己／指定人、冷卻、重複請求、任務完成 | 真人驗證與送出鎖存在；F01、F07 |
| daily_bar | 任務分配、完成紀錄、日期、按鈕路由 | 日期設計按 UTC；F07 |
| confession | 投稿、並發、防通知、成功確認、目的頻道 | PR #41 改善重複投稿；F02 |
| teams | 人數、加入／遲到／退出、修改、結束、6 小時到期、重啟恢復 | 有鎖與回復；F08 |
| tempvc | 手動／入口開房、排隊、重用、改名、上限、空房刪除、管理刪房 | 有追蹤 ID、排隊及權限驗證；F09 |
| squad_cards | 路線、1 人 1 分鐘、首次通知、快捷人數、FC／2K 模式、足跡、重啟 | PR #42 隔離個別場次失敗；F10 |
| activity_reminder | 星期／時間、增刪時段、5 分鐘前及準時提醒、補發、舊資料轉換 | PR #41/#42 有備份及補發；F11 |
| role | 單人／批量加減、角色階級、Helper 對 Mod 規則 | Bot 層級有檢查；F03、F12 |
| Role Tools（Menu 支援功能） | 選人、User ID、選角色、預覽、確認、撤銷權限後操作 | 選單有確認與身份重驗；F01、F03、F12 |
| duplicate | 新遊戲、版本 Forum、角色映射、頻道／標籤複製、待公告 | F04 |
| update_publisher | 草稿、補錄 Forum／角色、預覽、編輯、發佈、取消、重複發佈 | 成功後有記憶；F12 |
| twitch_relay | 雙向映射、去重、防迴圈、通知限制、重連、卸載 | 通知限制已部署；F13 |
| welcome_log | 加入／離開、歡迎、暱稱／角色、ban／unban | 發送錯誤有日誌；需現場確認頻道權限 |
| role_channel_emoji_log | 角色／頻道／emoji 建立、刪除、改名 | 有事件紀錄；不是所有權限變更的審計系統 |
| reload | 指定／全部模組、載入失敗、同步指令、權限 | F03、F15 |
| ping | Gateway 延遲 | 有指令；不能單獨證明 Twitch、資料寫入或排程健康 |
| role_channel_factory | 舊功能相容空 Cog | 無有效建立功能；避免當作另一套 Game Tools |

其餘 core 的權限、操作鎖、互動錯誤回覆、JSON/SQLite、路徑及 logging 已納入跨功能檢查。

## 已知問題及完整解法

優先：高＝權限邊界／管理誤操作／資料風險；中＝正常用量或故障時可能失效；改善＝產品口徑或觀測能力。除明列離線重現外，其餘是由實際控制流程確認的缺口，並非線上事故紀錄。

### F01　中：共用互動回應時機仍不一致

證據：`features/menu_actions.py`、`features/admin_actions.py`、`features/role_tools.py`、`cogs/drink.py`、`cogs/daily_bar.py`。部分入口先 await 統計或 fetch member，再作首次回應；部分收藏／排行榜同步查詢 SQLite。menu_stats 背景 worker 令 event loop 不阻塞，但呼叫者仍等寫入完成，不能保證操作及時確認。

方案：先分類「開 Modal」與「顯示／執行操作」。Modal 路徑立即開 Modal；其他需 I/O 路徑先 defer。統計放回應之後，查詢及寫入用受控 worker；不可全域一律 defer，否則會令 Modal 無法開啟。統一 SafeView/SafeModal 錯誤提示及過期按鈕處理。

驗證：鎖住 SQLite、延遲 fetch，確認先回應；所有 Modal 仍可開啟；失敗不留 thinking 狀態。

### F02　高：告白可繞過原頻道發言限制

離線重現：interaction.permissions.send_messages=False，submit_confession 仍呼叫 channel.send 一次。`cogs/confession.py` 沒有 require_public_send。若設定的目的頻道不在 cache，亦會退回目前頻道。

方案：採用與調酒／組隊相同的發言權限檢查；若有固定投稿頻道，應 fetch 並確認 guild/type，失效時報錯，不能靜默改目的地。匿名只代表公開訊息不顯示作者，不應描述為對所有系統絕對匿名。

驗證：唯讀頻道、thread、無 guild、目的頻道刪除／缺權限、正常投稿及重複投稿。

### F03　設計決策：Owner 常用 account 與一般 Helper

已知用途：Owner account 留作重要設定，iOS 日常 account 透過 Bot 管理。現行 helpers 身份共同授權多種管理功能；只對 Mod 做特別限制。這是需要分層的既有管理設計，不應直接把 Jeff 的日常功能全部關閉。

方案：固定 User ID 的個人管理授權 + Helper 能力清單；日常 account 不需要 Discord Administrator。只對指定操作授權，批量／破壞性操作有預覽及確認，紀錄 actor/targets/result。未取得常用 account 準確 User ID 前不能自行猜測或指派。可保留現有權限直至切換方案確定。

驗證：Owner／常用 account／Helper／普通會員／事後被移除角色，各自走 slash、選單及已打開的舊確認頁。

### F04　高：建立遊戲專區缺少完整的操作保護

證據：`cogs/duplicate.py` 新 Category 先建立、再 edit 權限，兩步之間可能繼承較廣權限；add_new_game 無同名 Category 防重與操作鎖；建立到一半失敗只回報 exception，已有角色／頻道可能保留。多 Forum 模板只在迴圈後將第一個來源的 tags 套用到最後一個 Forum。

方案：建立前驗證名稱／來源／可用權限與重複；每 guild 使用序列鎖；create_category 時直接帶 overwrites；每個 Forum 各自複製 tags；保存本次新增資源 ID 和步驟，失敗明確回報已建立項目與安全續作方案。回復只能處理本次新建、未被使用的資源，不能刪除重用角色。

驗證：同時雙按、同名、第二個頻道故意失敗、來源無權限、兩個不同 tags 的 Forum，及已有同名角色。

### F05　中：收藏榜與收藏頁使用不同資料口徑

離線重現：drink_collection 有一款 legacy 收藏、沒有對應收酒 event，收藏頁為 1，fetch_top_collectors 回傳空榜。`features/drink_leaderboard.py` 用自飲／收酒事件重算；collection_milestones 則保留舊贈酒者的歷史收藏。

方案：收藏頁、數量及收藏榜一律用 drink_collection 所有權表；自飲／贈酒／收酒榜仍按事件表。保留舊資料，不重寫歷史。

驗證：舊賜酒者、新賜酒者、新收酒者、同款多次、跨 guild、同分排序。

### F06　中：調酒／收藏查詢仍有同步重複初始化與長大風險

證據：`features/drink_storage.py` 每個查詢都執行 schema 初始化；紀錄頁一次會有多個查詢。collection_snapshot/theme_snapshot 讀頁亦會開寫交易 reconcile。`features/drink_state.py` 每次冷卻及最近紀錄各寫一次完整 JSON；冷卻字典未清除過期使用者。cooldown 值轉 float 缺乏 schema 驗證，錯誤值可能令模組載入失敗。

方案：初始化集中一次並支援 reload／測試路徑；將查詢及寫入逐步收口到同一受控 DB 層；避免為展示重複 reconcile。限制 recent history、定期清過期冷卻，合併同一次叫酒的 JSON 寫入。舊資料錯誤逐筆隔離與備份。沒有量度之前不刪歷史 drink_events，亦不新增 Redis/Postgres。

驗證：資料庫鎖、磁碟失敗、壞 cooldown 值、大量 event 的查詢時間、冷卻及收藏跨重啟保留。

### F07　產品口徑：每日任務 UTC 換日；「今日」統計是滾動 24 小時

離線重現：香港 2026-11-04 00:30（UTC 11-03 16:30），daily_bar 日期為 11-03。現有 footer 明寫 UTC，因此是與香港社群使用習慣的設計差異，不應假裝資料已錯亂。menu_stats 的 days=1 實際為最近 24 小時，與「今日」標籤不同。

方案：統一 Asia/Hong_Kong 產品日期；資料 timestamp 保留 UTC。轉換每日完成紀錄時先備份，定義過渡日完成次數與舊日期呈現；不要只改 now() 令既有完成紀錄失效。統計 today 從香港午夜開始，week 清楚標示最近 7 日或本週。

驗證：香港 23:59/00:00/07:59/08:00、帶 timezone 的測試日期、轉換日前後不重複獎勵。

### F08　中：手動組隊畫面更新失敗後缺少自動追平

證據：`cogs/teams.py` refresh 與 EditTeamModal 保存成功、message.edit 失敗時只回覆畫面未更新；sweeper 只處理結束／到期卡，未補刷新活躍卡。

方案：保存成功即標記 dirty；有上限及退避的 sweeper 只重試 dirty 卡，成功清除、NotFound 清理追蹤、Forbidden 提示管理員。不要重複建立新卡或重複加人。

驗證：第一次 edit 失敗、下一次成功、期間再加入／退出、訊息刪除、過期與 finish 交錯。

### F09　中：臨時語音房的排隊生命週期及上限

已改善：Bot 建立房間有 ID/creator 追蹤；只清理已記錄 ID，改名不影響；空房倒數／重啟 sweeper／開房排隊有測試。尚需覆核：等鎖期間 reload，新的 Cog 鎖與舊事件工作同時存在；creation handler 非 Cog 持有 task，cog_unload 沒有追蹤這些等待者。多人反覆開房也沒有 guild 級房間數量上限。

方案：共用 creation coordinator（reload 不重設），追蹤與停止等待工作，維持每人一房及可設定 guild 上限；API 失敗有明確回覆。實際權限與單人刪房的瞬時加入競態需線上驗證。

驗證：多人排隊期間 reload、離開入口再入、同時手動及入口開房、房數上限、move 失敗。

### F10　中：自動語音卡設定／畫面一致性

PR #42 已隔離個別 session render 錯誤，不能當作其他問題均已解決。`reconcile` 只以 member ID roster 決定是否更新，改 display name 未必刷新；UI 編輯先保存、render 失敗時沒有 dirty 標記，名單不變下可能不會追平。ModePicker 等會在取得共用鎖後才作首次回應，其他場次慢 API 可能拖延操作。state 的 settings/sessions 缺完整 schema 驗證。

方案：以完整 card state revision 決定 dirty，成功 render 後才 ack revision；設定操作與背景 tick 共用相同重試機制。UI 一般操作先 defer；開 Modal 的路徑不等待全域長鎖。資料逐筆驗證及備份，避免一筆格式錯誤令整個 Cog 載入失敗。

驗證：只改暱稱、render 失敗後無人進出、跨兩場慢 API、重啟時缺欄位、舊 Modal 提交。

### F11　中：活動提醒仍需處理資料與編輯交錯

已改善：時段 ID、兩分鐘 lookback、備份轉換；PR #42 改延遲分鐘及指定角色通知。尚需：_tick 在 await send 期間，管理員可移除／改時段；傳遞 schedule_idx 在下次迴圈可能指向不同時段或 IndexError。活動名稱／時段數沒有合理上限，過長名稱可令訊息發不出去。

方案：以不可變 schedule ID/快照傳入 send，發送前核對仍啟用，避免 index 依賴；每活動隔離錯誤；驗證名稱長度、時段重複、空 weekdays。跨重啟的模糊網絡成功狀態無法只靠 retry 保證 exactly-once，需明確界定去重策略。

驗證：send 暫停時刪除／改時段、極長名稱、重複時段、23:58 的預告與翌日活動、磁碟失敗。

### F12　高：管理確認頁、Modal 與執行狀態未完全同步

離線重現：DraftReviewView.publishing=True 時按取消，仍回覆「已取消草稿，未有發佈」。實際 send 可以繼續，令用戶誤判。EditDraftModal 提交亦未檢查草稿已取消／正在發佈／已發佈；編輯後沒有重跑初始 2,000 字預覽限制。發佈正文亦未明確限制 allowed_mentions。

方案：草稿使用明確 draft/publishing/published/cancelled 狀態及 revision；編輯／取消／發佈全部按同一狀態機驗證；Modal 提交重驗 owner、權限、revision、長度；公開發佈明確控制通知。可考慮保存 draft/message ID 方便重啟後查重。Role Tools 選單已有確認，但 slash role_grant/revoke 直接執行；若目標是防誤操作，批量 slash 亦應導向相同確認流程。執行時成員名單與預覽有變需重新確認。

驗證：發佈途中取消／編輯、兩個開啟中的 Modal、權限被移除、過長編輯、發佈成功但紀錄或確認失敗、批量角色前後名單變動。

### F13　中：Twitch 重連、長訊息及可觀測性

證據：`cogs/twitch_relay.py` 每則 Discord message 發現 websocket 關閉都可呼叫 connect，沒有統一 reconnect lock；訊息直接加前綴轉發，沒有長訊息分段。去重 cache 在發送前標記，send 失敗沒有清掉。正常 INFO log 含完整兩邊訊息內容。

方案：單一連線監督工作、退避重連、有上限的發送 queue；按實際平台限制分段，保留來源 ID 防迴圈；以成功發送標記或可重試失敗狀態去重；正常日誌只留 channel/message ID、長度、結果，錯誤亦不輸出 token／聊天全文。

驗證：斷線時多人同時發文、超長 Unicode、相同內容不同作者、失敗再試、echo、防通知、reload 清理。實際 Twitch token scope 與頻道權限未取得，不能聲稱現場已通。

### F14　改善：資料展示與測試規模

庫內酒譜 2,102 款，主題 3 張。稀有度頁目前只顯示前 COLLECTION_PAGE_LIMIT 款，其餘提示未顯示，沒有翻頁；catalog 全量與主題 frozen v1 有意分開，不可擅自合併改抽中機率。部分成就／稀有度展示多次查詢；未做線上流量或 256MB peak RSS 量測。

方案：收藏頁加分頁及清楚排序；保持 ownership、manifest、概率與舊資料策略不變。測試完整酒譜下 embed 長度、25 項 select 上限、跨頁更換 target、稱號僅本人可改、舊通知只本人確認。先量度再決定是否快取或調整記憶體。

### F15　高：部署成功不等同 Discord 所有功能健康

證據：bot.setup_hook 捕捉 load_extension 失敗後仍同步 slash 指令，個別模組可以消失而主程式繼續；Fly workflow 最後只執行 flyctl status，沒有解析 started 狀態／Discord readiness。CI 沒有明確 job/test timeout，PR #42 的 PR run 長時間未完成；相同 head 分支 run 已成功。

方案：列出核心／可選模組，核心缺失就部署失敗，可選功能顯示 unavailable；先確認核心模組完整才同步命令。部署驗證 machine 狀態、最新 release、Discord ready 與核心 task 狀態，最後一組人工 smoke test。CI 加合理 timeout，失敗後依日誌判斷 retry；不能只為取得綠燈略過有問題的測試。

驗證：故意令一個核心 Cog import 失敗、Discord token 無效、volume 不可寫、排程停止、機器 started 但未 ready。

## 成本及恢復邊界

- 實際已知：上期帳單 US$3.03，該期電郵獲 100% 減免。不是永久免費承諾。
- Repo 設定：sin、shared 1 CPU、256MB、/data volume。設定檔不能證明線上只開了一台或 volume 實際容量。
- 目前沒有 Fly billing／machine inventory／metrics 的讀取結果，不能拆解 3.03 或保證下期低於 5。
- 控制方案：保留現有規格，核對額外 machines、未用 volumes、專用 IP、egress／snapshots；先量度記憶體、DB 大小及事件量。減輪詢主要改善效能，不保證固定機器月費下降。
- 建議預警 4 美元，目標低於 5 美元；需取得帳單資料才可可靠實作。此報告未建立自動化，也未修改付費配置。
- /data 掛載失敗時 storage_paths 可退回 image 內 data；production 應明確檢查 persistent mount 可寫後才啟動，避免誤把暫存資料當永久資料。
- JSON atomic replace 及 corrupt backup 已有；PR #42 補讀取／備份失敗保護。SQLite WAL 不等於備份，不能直接只複製正在寫入的 .sqlite3；應採一致性 backup 並做一次還原演練。

## 一次過整合的修正方案及驗收

1. 互動與管理操作：統一回應策略（保留 Modal 即時入口）、告白權限、Publisher 狀態機、Game Tools 預檢與序列鎖、批量角色確認。保留 Jeff 常用 account 的管理用途；個人 ID 與 Helper 分權需要準確 ID。
2. 資料與排程：同一收藏來源、香港日期過渡策略、逐筆 schema 驗證、dirty card 重試、schedule 快照、reload 可清理的開房 coordinator、受控 DB worker。
3. 維運與成本：核心模組啟動檢查、production persistent mount 檢查、完整 readiness、CI timeout、備份／還原；讀取實際 billing/inventory 後再做資源調整。

以上是同一份完整 backlog，應按風險組成一個協調的修正版本及回歸套件，不要求用戶每發現兩三個問題就再批准一輪。涉及角色授權對象或日期／舊獎勵策略的決策要明列，不能在修 bug 時偷偷改產品規則。

整體驗收需覆蓋：普通會員／Helper／日常管理 account、所有 slash/menu/舊按鈕、兩人並發、thread/唯讀頻道、重啟/reload、刪訊息/缺頻道/權限改變、DB 鎖/磁碟失敗、跨午夜、Twitch 中斷。

## 未取得的線上證據

Discord 現場點擊、實際 guild 角色排序與覆寫、常用 account ID、Fly 日誌與資源明細、billing、Twitch scopes、資料庫實際大小／流量。沒有來源支持的部分沒有標記「已通過」；目前程式測試涵蓋率亦未量測成百分比。
