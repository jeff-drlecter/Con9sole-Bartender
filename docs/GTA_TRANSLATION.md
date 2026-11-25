# GTA 官方更新繁中翻譯試行

俱樂部助手以 [Apps Script 內置 LanguageApp](https://developers.google.com/apps-script/reference/language/language-app) 將官方更新譯成繁體中文。使用個人 Google 帳戶的 Apps Script 配額，毋須開通 Cloud Billing。GTA 官方原帖保留在原頻道，譯文放在該帖的公開討論串內。一般長度直接顯示，超過 Discord 單則訊息長度的全文附為 UTF-8 文字檔。譯文靜音送出並停用提及。

## 啟用範圍

- 只接收本伺服器 `#官方更新-gta📢`（`1460576839385743493`）透過 Discord「追蹤公告頻道」收到的新轉發。翻譯帖內文字及預覽的標題、描述、欄位；純連結及純媒體會略過。網址、附件及會員留言不會送往翻譯服務。
- 在獨立 Apps Script 專案部署 [Code.gs](../apps-script/gta-translation/Code.gs) 為 web app，以擁有者執行，允許任何人連線。用密碼學隨機數產生 32 bytes 的小寫 hex token；將其 64 字元 ASCII 字串的 SHA-256 hex 存入 Script Property `GTA_TOKEN_SHA256`。只有通過驗證的請求會使用翻譯配額。
- 將版本化部署的 `https://script.google.com/macros/s/…/exec` 及原 token 分別存入 Fly secrets `GTA_TRANSLATION_SCRIPT_URL`、`GTA_TRANSLATION_TOKEN`。兩項均未配置時模組停用。只向原端點 POST，Google 結果轉址只以無憑證 GET 讀取。Discord Bot 需要檢視頻道、讀歷史、開公開討論串、串內發文及附件權限。
- 只處理啟用後 Bot 實際收到的 Discord 新帖事件。已入列的工作在重啟後繼續；離線期間完全收不到的訊息及既有歷史不會掃描。

## 額度及送達

- 以香港時間每月 1 日零時換月，最多送出 450,000 個原文字元（Unicode code points，包括實際送出的空格及換行）。逐次在 SQLite 交易內先扣額再呼叫 Google，重試也計入，即使逾時亦保留該筆。此上限涵蓋本試行，不包括同一 Google 帳戶的其他應用。
- Apps Script 亦會在同一個指令碼鎖內以香港月份獨立扣額，避免多個呼叫合計超過 450,000。整篇超出餘額就延至下月。遇到 Google 每日配額就保留工作，24 小時後重試。已翻好的帖子仍可發送。其他翻譯或取得討論串的暫時錯誤每階段最多嘗試三次，相隔至少五分鐘。Discord 明確拒絕送出可重試；送出結果不明時留作人工核對，以免重複。
- 以來源原帖 ID 去重，沒有來源 ID 時使用本地訊息 ID；已存在的附屬討論串會沿用。成功後只保留收據，清除儲存的譯文。移除 secret 並於下次獲授權重載或部署時停用。請保留持久卷上的 `gta_translation.sqlite3`，讓額度及收據沿用。

## 核對方法

離線執行 `python -m unittest discover -s tests -p test_gta_translation.py -v`。測試以合成公告、模擬 Google／Discord 及臨時 SQLite 驗證重複轉發、既有討論串、併發額度、重啟及跨月。有 Node.js 時亦會執行原版 Code.gs 的驗證、翻譯分段及封頂測試。部署前先用合成英文短句呼叫實際 web app，核對繁中及其數字；只會扣 Apps Script 配額。

獲授權啟用後，以一則自然到達的 Rockstar 更新核對原帖下只有一個討論串、繁中內容及原文意思。可唯讀查核帳本：

```sql
SELECT month, characters FROM usage ORDER BY month DESC;
SELECT stage, COUNT(*) FROM posts GROUP BY stage;
SELECT message_id, stage, attempt FROM posts WHERE stage IN ('posting', 'failed');
```

持續停在 `posting` 的訊息要先查看原帖的討論串確認有沒有送達；`failed` 表示該階段已耗盡嘗試次數。診斷日誌只列訊息 ID、階段、次數、錯誤類型及可得的狀態碼。
