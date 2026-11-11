# Twitch 直播通知

## 管理

在 Bot 管理工具按「直播名單」，或用 `/stream_admin`。
只有本伺服器 Administrator / Manage Server 可查看及修改；每次按鈕及表單提交都重新核對權限。

- 新增：貼 Twitch 帳號／網址，選成員或友台。先經 Twitch API 驗證。
- 下拉名單選直播主，再啟用／停用、轉換類別或移除（需二次按鈕確認）。
- 成員每 5 分鐘；友台預設每 30 分鐘，可選 60 或 120 分鐘。
- 成員開台可 tag 原有觀眾 Role，管理介面可關閉；友台永不 tag，訊息使用 silent。
- `/stream_channels` 更改兩類通知目的地。當前直播原卡留在原頻道，下一場使用新頻道。
- `/stream_panel` 可在非公開管理頻道放置永久管理入口。

## 減少洗版

每場直播只有一張卡；不定時更新標題／遊戲，不另發收台訊息。收台更新原卡及匹配當場 VOD（如有）。
收台時間只表示檢查確認，不能當成精確下播時間。刪除的通知卡不補發。
新增、首次切換、停用再啟用時只建立當前基準，已開台的場次不補發；其收台亦不新發卡。
API 錯誤不當收台，未到期友台不當收台。斷線重開且 Twitch stream ID 變更視作新場次。

## 資源

沿用現有 aiohttp、discord.py 與 /data，無新常駐服務或依賴。
只有到期帳號入批量查詢（最多 100），明確 first=100，讀完分頁才更新狀態；分頁失敗／重複／超出安全上限則保留原狀。
OAuth 快取按 expires_in 更新；每小時驗證；401 最多刷新一次，429 尊重 cooldown。
不逐輪查頭像，不下載圖片／直播影片；預覽圖由 Discord 客戶端/CDN 讀取。
現有 4 位成員維持每日約 288 輪檢查；有直播時可能需要額外分頁請求。友台由 15 改 30 分鐘主要減少處理資料量，
因同批查詢，並不會令總 request 數減半。另有每小時 token validation、開台/收台的 Discord API 及按需 VOD 請求。

## 持久化與切換

SQLite `/data/twitch_alerts.sqlite3` 保存名單、頻率、啟用狀態、直播 ID、訊息 ID 及 pending 發送。
新安裝預設暫停；`TWITCH_ALERT_BOOTSTRAP` 只在首次建立資料庫時匯入，之後名單以 Bot 為準。
憑證只用 Fly secrets `TWITCH_CLIENT_ID`、`TWITCH_CLIENT_SECRET`。不需要複製舊 Webhook。
發卡前保存 pending，重啟／發送結果不明時先查本 Bot 歷史 marker，再決定是否重試。
超過安全歷史掃描界限時暫停該次發送而非重複出卡；不能保證所有網絡／刪卡競態下的嚴格 exactly-once。
資料庫讀取失敗會停止模組載入，不以空白狀態重發。

切換順序：部署（暫停）→核對 15 人及 API/頻道權限→停用 Apps Script 觸發器→Bot 恢復通知→核對首次基準及資源。
回復：先暫停 Bot 通知，再恢復舊 Script 觸發器；先更新舊 Sheet 當前狀態，否則可能重發。
保留舊 Script 及 Sheet 作參考，不再作現行名單來源。

檢查：`python scripts/verify_stream_alerts.py`（在 Fly 容器內執行，只讀，不派送）。

## 沙盤示範

在「測試公告」執行 `/stream_demo`，會建立成員／友台兩張明確標示模擬資料的卡及一個控制面板。
按「重複檢查」驗證不新增卡；按「模擬收台」驗證更新原來兩張卡，再檢查亦不新增。
示範沿用正式 send_live/end_card/transition 路徑，但名單、狀態只在獨立記憶體，目的地鎖定測試公告。
兩類示範均禁止 tag 並 silent，Twitch API 呼叫為零，圖片不載入真實直播預覽。
測試按鈕有效 20 分鐘；Bot 重啟後可重新執行指令。示範不驗證正式觀眾 Role 是否實際收到推送。
