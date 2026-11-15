> 本文是來源分支交接快照。06 整合修正、最新檢查及部署狀態見 [現行總表](CURRENT_INTEGRATION_STATUS.md)，不可將分支通過當作整合版通過。

# 05 新聞與直播交付狀態｜交 06

基線 main 15d8a97。Repository 沒有 AGENTS.md，依本次提供的專案指引。未合併、未部署、未改正式開關、未發送測試／公告；iPhone Mirroring 及實機按指示略過。

## 狀態定義與接口

RSSDelivery.health_snapshot() / StreamAlerts.health_snapshot() 是唯讀純資料接口，回傳 collection / preview / delivery、observations、read_error。RSS 額外 store_preview / store_delivery（永遠 false）。每個 observation 分開 attempt、obtained、delivered、result、failures、pending、last_failure。缺紀錄為未知，不把零當成功。attempting 不清除連敗；成功清目前連敗，保留最後故障時間。來源取得不是摘要交付，直播 API 成功不是每個帳號發卡成功。

結果：outside_window 未到窗口；empty 正常零內容；filtered_empty 有候選但未選出（含篩選／去重／優惠條件）；ready 可處理；sent 已取得並儲存發送收據；retry 等待既有退避；failed 確定失敗；uncertain／sending 結果待核對；receipt_write_failed 收據寫入失敗。health_write 另標示目前程序讀寫異常。舊收據沒有精確送出時間，不憑空補造。

觀測表與 digest_batches／去重收據分開；schedule_result 唯讀，零內容不建立 batch，窗口稍後到文仍可處理。429 的三次上限／退避及 timeout 不盲重試完全沿用。觀測寫入失敗不阻止既有發送決策；收據寫入失敗保留 sending 並需人工核對。

直播按帳號記錄故障與恢復；最近 API 查詢在重啟後可讀回，交付部分失敗不再冒充全面成功。每場一卡、原位更新、刪卡不補發、新增／恢復基準、API 失敗不當收台沿用原流程。deleted 卡不記新交付成功。

BotHealth 僅管理員新增詳細新聞／直播區；不向 Helper／Mod 擴展營運資料。04 已有開發分支介面 CommunityOutcomes.health_status：僅採 available、heartbeat、error 布林，絕不顯示原始錯誤／名單；未載入不猜測。06 整合 04 時保留此管理員邊界，避免其分支原有未分層欄位重複輸出。

## 啟用核對

fly.toml：RSS_PERSONAL_PUBLIC=1，RSS_CATEGORY_DELIVERY=1，sources=ps,xbox,4gamers；rss_production enabled=true / simulation=false / max_items=8。每日 19:00 不變。STORE_NEWS_CONFIG 已設、STORE_NEWS_PUBLIC=0；Steam/Epic 收集與既有測試預覽不等於正式商店推送。本次未讀取正式 Twitch roster 或 Fly DB，直播 runtime enabled 及目前交付狀態須由 06 唯讀核對，不能由程式載入推定。

## 相容／回復

在既有 RSS、分類 RSS、store_news、twitch_alerts SQLite 中按需新增 delivery_observations 表，沒有另造商店資料庫，不更改原表／偏好／角色。健康頁 mode=ro 不建立表。舊 store_snapshots checked 與 TTL 繼續作為內容新鮮度依據；新增觀測尚未產生時 UI 顯示未知。回復程式可保留附加表；先備份原 DB（含 WAL），不要清除收據或 pending 狀態。不可用刪表逼重送。狀態寫入失敗而同時 DB 不可寫時，讀寫異常只可留程序診斷；重啟後以持久收據待核對，不能保證故障紀錄本身落盤。

## 營運草稿（不發布）

未找到並核實唯一 Welcome／Guide 固定卡 message ID、頻道 ID、作者及當前內容。因此只交短修訂草稿，不補發：
「從『約一局』找隊友或查看現有約局。遊戲情報每日整理；『情報設定』分開管理新聞頻道顯示與個人篩選，手機提醒由 Discord 通知設定控制。」

跨遊戲小規模觀察表：觀察日期（香港）／遊戲／模式／入口／約局是否成局／真人到場數（可核實才填）／是否成功開啟新聞及通知入口／遇到阻礙／資料缺漏。只記必要匿名匯總，不推斷因果或流失。
三條回饋問題：①你有找到想參加的局嗎？②哪一步最難理解？③你分得清頻道顯示、個人篩選和手機通知嗎？
不聯絡主持、不建活動、不設定自動發布。

## 06 驗收與限制

跑完整 unittest、compileall、diff check；新增案例覆蓋重啟保留最後成功、零內容／故障／部分故障／過舊、窗口稍後到文、等待重試、timeout、收據寫入失敗、直播 API 成功但送卡失敗及恢復。現有 RSS／Steam／Epic TTL、429／直播基準與刪卡案例繼續使用。
未驗證正式網絡、Fly DB、新正式交付及真人操作。BotHealth 共用檔案可能與 04 衝突，06 必須核對只向管理員輸出新增詳細區，檢查 embed 欄位總數及長度。長診斷區顯示限 1000 字，純資料接口保留全量，待核對項目優先。不表示所有來源即時健康，也不表示可收回已顯示資料。
