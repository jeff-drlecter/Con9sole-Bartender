# 遊戲官方更新繁中翻譯

俱樂部助手以 [Apps Script 內置 LanguageApp](https://developers.google.com/apps-script/reference/language/language-app) 將官方更新譯成繁體中文。使用個人 Google 帳戶的 Apps Script 配額，毋須開通 Cloud Billing。Bot 直接在相同頻道回覆官方原帖，讀者可以從回覆跳回原文。一般長度直接顯示，超過 Discord 單則訊息長度的全文附為 UTF-8 文字檔。譯文靜音送出並停用提及。

## 啟用範圍

- 接收本伺服器九個遊戲官方更新頻道透過 Discord「追蹤公告頻道」收到的新轉發，涵蓋 GTA、EA SPORTS FC、NBA 2K、Delta Force、Helldivers 2、Monster Hunter、Battlefield 6、Where Winds Meet 及 Apex Legends。以 [頻道 ID 清單](../core/gta_translation.py) 判斷。翻譯帖內文字及預覽的標題、描述、欄位；純連結及純媒體會略過。Bot 會先移除公告標記，將原帖連結換成代號才送出翻譯，再將原網址放回相應位置。「立即收聽」可直接點擊。網址、附件及會員留言不會送往翻譯服務。
- 在獨立 Apps Script 專案部署 [Code.gs](../apps-script/gta-translation/Code.gs) 為 web app，以擁有者執行，允許任何人連線。用密碼學隨機數產生 32 bytes 的小寫 hex token；將其 64 字元 ASCII 字串的 SHA-256 hex 存入 Script Property `GTA_TOKEN_SHA256`。只有通過驗證的請求會使用翻譯配額。
- 將版本化部署的 `https://script.google.com/macros/s/…/exec` 及原 token 分別存入 Fly secrets `GTA_TRANSLATION_SCRIPT_URL`、`GTA_TRANSLATION_TOKEN`。兩項均未配置時模組停用。只向原端點 POST，Google 結果轉址只以無憑證 GET 讀取。Discord Bot 需要檢視頻道、讀歷史、發送訊息及附件權限。
- 只處理啟用後 Bot 實際收到的 Discord 新帖事件。已入列的工作在重啟後繼續；離線期間完全收不到的訊息及既有歷史不會掃描。

## 額度及送達

- 以香港時間每月 1 日零時換月，最多送出 450,000 個原文字元（Unicode code points，包括實際送出的空格及換行）。逐次在 SQLite 交易內先扣額再呼叫 Google，重試也計入，即使逾時亦保留該筆。所有頻道共用這 450,000 字元額度，同一 Google 帳戶的其他應用另計。
- Apps Script 亦會在同一個指令碼鎖內以香港月份獨立扣額，避免多個呼叫合計超過 450,000。整篇超出餘額就延至下月。遇到 Google 每日配額就保留工作，24 小時後重試。已翻好的帖子仍可發送。其他翻譯或送達的暫時錯誤每階段最多嘗試三次，相隔至少五分鐘。Discord 明確拒絕送出可重試；送出結果不明時留作人工核對，以免重複。
- 所有頻道以來源原帖 ID 去重。相同原帖重複轉發時只處理最先入列的一份，缺少來源 ID 時以本地訊息 ID 去重。每則回覆指定本地原帖及其接收頻道。原帖已刪除時不改為獨立訊息。GTA 試行期間已在討論串送達的收據繼續生效。成功後只保留收據，清除儲存的譯文。移除 secret 並於下次獲授權重載或部署時停用。請保留持久卷上的 `gta_translation.sqlite3`，讓額度及收據沿用。升級自動將舊收據歸入 GTA。回退至只支援 GTA 的版本前，先確認其他頻道沒有待處理工作或未確認送達的訊息，以免舊版用 GTA 頻道重試。

## 核對方法

離線執行 `python -m unittest discover -s tests -p test_gta_translation.py -v`。測試以合成公告、模擬 Google／Discord 及臨時 SQLite 驗證原生回覆、重複轉發、原帖被刪除、九個頻道的派送、併發額度、重啟及跨月。有 Node.js 時亦會執行原版 Code.gs 的驗證、翻譯分段及封頂測試。部署前先用合成英文短句呼叫實際 web app，核對繁中及其數字；只會扣 Apps Script 配額。

獲授權啟用後，以一則自然到達的遊戲官方更新核對 Bot 的唯一回覆指向同一頻道的原帖，並對照繁中內容與原文意思。可唯讀查核帳本：

```sql
SELECT month, characters FROM usage ORDER BY month DESC;
SELECT stage, COUNT(*) FROM posts GROUP BY stage;
SELECT message_id, stage, attempt FROM posts WHERE stage IN ('posting', 'failed');
```

持續停在 `posting` 的訊息要先查看原帖所在頻道，確認是否已有 Bot 回覆。若屬升級前的 GTA 工作，亦要查看原帖原有的討論串，舊版可能已在串內送達。`failed` 表示該階段已耗盡嘗試次數。診斷日誌只列訊息 ID、階段、次數、錯誤類型及可得的狀態碼。

## FC27 人工輸入更新

從 `/menu → 管理工具 → Update Publisher → FC27 官方更新` 開啟。只有本伺服器具 Administrator 或 Manage Server 權限的操作者可以建立草稿，只有開啟者可以校訂或確認。Bot 使用現有 Con9sole 助手身份，目的地固定為 FC 官方更新頻道。

1. 先在瀏覽器核對官方英文文章、署名及版本。填寫版本和一至兩條同版 EA FC27 News／英文 Game Info Hub 文章連結。引文出處放第一行。自行用英文概述改動，保留數值、單位、幅度、平台、限制與兩篇原文的差異。另選一句最多 25 詞的英文短引。原文連結讓讀者查看全文及文章內的圖像和影片。
2. 提交後，只會看到私人預覽。現有 Apps Script 分別翻譯摘要和短引。預覽同時顯示英文底稿，可校訂兩段繁中。請逐項核對專有名詞、單位、條件及免責條款。發布前程式會核對數值、正負號、百分比和小數精度。語意及來源真確性由操作者覆核。
3. 按「確認並由助手發布」才會送出一則藍色繁中主帖，並在附屬討論串送出紫色的英文短引、繁中對照及官方連結。兩則都靜音及停用提及。人工入口沒有自動輪詢、抓取全文、下載媒體或定時發送。
4. 中斷或重啟後，再次開啟相同入口，只填版本號，會載入持久化的確認稿。完成的版本會回傳原有兩條連結。已保存的訊息被刪除或內容不符時會停止。結果未明時，只有找到唯一、內容一致的助手訊息才會續傳。缺歷史、超過 1,000 則歷史檢查上限、已有其他作者的同版內容，或其他來源串內容無法辨識，均須先人工核對。未確認的預覽可以重新輸入，翻譯快取會沿用。

**用量。** 採用原有服務及同一個香港月份 450,000 字元帳本。每次送譯前先扣額，每篇主要來源每月最多 6,000 字元，同一來源的一段相同英文每月最多嘗試兩次，相隔至少 120 秒。成功譯文按來源及英文內容雜湊持久保存。重開預覽、校訂及續傳已確認稿均可重用譯文。無新付費服務，實際新增用量視提交次數而定。

**去重範圍。** SQLite 在送出前記錄每個 FC27 版本和兩個送出階段，確認稿包含其各篇來源。附屬討論串與主帖共用 Discord ID。可辨識的同版 Discord 轉發與人工入口以同一交易裁定由哪條路徑翻譯。轉發先到時保留原有原生回覆行為。人工稿先確認時，後來帶明確 FC27 版本或合規 EA 文章連結的轉發略過自動翻譯。Discord 自行顯示的轉發仍可見。無法識別版本、多版本混合或歷史帳本未記版本的轉發，不能保證跨路徑去重。Apex 的人工及轉發規則見下節，其餘七款遊戲沿用原有流程。

離線驗證執行 `python -m unittest discover -s tests -p test_fc27_publisher.py -v`。正式發布流程只接受 main。部署後可先用原有管理選單核對私人預覽和權限，真實試發另行授權。回退時先停止確認新稿，核對未完成或結果未明的收據，保留現有 SQLite 和備份。以 revert PR 經 main 的正常部署流程還原。舊版會忽略新增資料表，回退後需人工核對遲到的 FC 轉發。

## Apex 人工輸入更新

在 `/menu → 管理工具 → Update Publisher → Apex 官方更新` 輸入版本號；沒有官方版本號時使用文章標示的日期 `YYYY-MM-DD`。例如 2026 年 11 月 25 日的地圖更新可填 `2026-11-25`。只填同一識別碼可續傳已確認稿。FC27 及 Apex 的同一數字版本分開記錄。

操作者先核實正文和發布者。選用 [EA Apex News 的 Patch Notes](https://www.ea.com/games/apex-legends/apex-legends/news) 或 [EA Apex Game Info Hub 的官方修正](https://forums.ea.com/category/apex-legends-en/blog/apex-legends-game-info-hub-en/)。填寫一至兩篇同一次更新的英文官方文章，引文出處放首行。版本、署名、受影響平台、條件及「已修正」狀態由人核對。Trello 只供查閱追蹤進度，發布表格只接受 EA 文章。遇到同日多份無版本更新，先核對是否同一宗；已綁定的識別碼不會另開一帖。

私人校訂、確認、靜音主帖及雙語來源串沿用上節流程。目的地固定為現有 Apex 官方更新頻道 `1464858693014392924`。已有同版或同一官方文章的可辨識轉發會阻止重發，反向次序則略過相符轉發的翻譯。可辨識資料包括官方連結（論壇按文章 ID）、明示 Apex 的版本或不含歧義的日期。混合版本、無識別資料或不完整的舊帖需人工核對。助手掃描目的地歷史最多 1,000 則，超限或權限不足會停止發布。

沿用同一個香港月份 450,000 字元總額、每篇主要來源每月 6,000 字元上限及原有快取。每次全新預覽最多送譯兩段（自撰摘要和短引），未提交時零次。程式不輪詢 EA 或 Trello。離線使用 `python -m unittest discover -s tests -p 'test_*publisher.py' -v` 驗證兩款遊戲的入口、拒絕、重啟及續傳。

## 其他遊戲的人工發布

在管理工具的 Update Publisher 選「其他遊戲官方更新」，再揀遊戲。輸入官方版本或日期、原文標題、文章連結、自撰摘要及短引。先在官方文章核對平台、時間、模式、地區及例外。只有開啟面板且仍有管理權限的人可以確認。目的地取自現行官方更新頻道表。這個入口不會輪詢網站或自動發布。

| 選項及既有目的地 | 識別碼示例 | 官方來源及核對範圍 |
| --- | --- | --- |
| Battlefield 6 / REDSEC · 官方更新-bf6 | `2.1.2.5` | [Battlefield Game Update](https://www.ea.com/games/battlefield/battlefield-6/news/battlefield-6-game-update-2-1-2-5)。同一次更新一帖，在摘要分清 BF6 共通及 REDSEC 專屬項目。 |
| Helldivers 2 · 官方更新-hd2 | `7.2.0 / 原文範圍` | [Arrowhead Patch Notes](https://arrowhead.zendesk.com/hc/en-us/articles/31176395885596-Devoid-of-Liberty-7-2-0)。識別碼保留原版號及範圍。同一篇涵蓋多平台時一帖列明；只為個別平台另發的文章可分開。 |
| GTA Online 更新 · 官方更新-gta | `1.73` | [Rockstar Support](https://support.rockstargames.com/articles/4vRqEDvjUs9h7nqRUgc8YO/gtav-title-update-1-73-notes-ps5-ps4-xbox-series-x-or-s-xbox-one-pc-enhanced-legacy)。只摘錄 GTA Online 適用的平台和項目。 |
| GTA Online 每週活動 · 官方更新-gta | `2026-11-05 / 4k17a844oakk5o` | [Rockstar Newswire](https://www.rockstargames.com/newswire/article/4k17a844oakk5o/take-down-the-kortz-center-and-more-high-value-targets-in-this-week-s)。按文章發布日期及 ID 建立活動收據。摘要分清每週和整段活動的獎勵時間。 |
| Delta Force · 官方更新-df | `2026-11-10 / 跨平台` | [全球服 Season Aurora 改版](https://www.playdeltaforce.com/en/detail/news-major-update-season-aurora-is-coming.html)。核對生效日期，分別寫出 PC、主機、手機時段。 |
| Monster Hunter Wilds · 官方更新-mh | `1.042.00.03 / Steam` | [CAPCOM 官方 Steam 公告](https://store.steampowered.com/news/app/2246340/view/668380665149915562?l=english)。只收 App 2246340 的發行商 Update Summary，須輸入含對應版號的原標題。 |
| 燕雲十六聲（港澳台）· 官方更新-wwm | `2026-11-26` | [港澳台版更新](https://www.wherewindsmeetgame.com/hmt/news/official/1126update.html)。直接填寫人工繁中摘要及最多 60 字官方繁中短引。兩張卡均使用繁中，這條人工路徑的翻譯用量為零。 |
| NBA 2K27 · 官方更新-2k | `3.0` | [2K27 官方修正說明](https://nba.2k.com/2k27/patch-updates/)。官方會重用同一網址。核對頁內的版本標題和各平台推出日期，例如 v3.0 的 PS5／Xbox Series X\|S 為 18/11，Switch 2／PC 為 27/11。將兩批日期列在同一帖。 |

合規連結只識別來源，操作者仍須閱讀實際正文。若連結不屬已核實格式或目的地無法唯一識別，助手會停止。對沒有明示遊戲的 Newswire 網址、Delta Force 不透明文章 ID 等，需先由維護者在 `core/reviewed_games.py` 核對並登記；新宣傳頁、玩家討論、其他 Steam App、GTA VI 或其他地區不會因同一網域而獲准。

保留原生 Follow 的頻道，人工帖及可辨識轉發共用同一組送達收據。只有網址而沒有可譯文字的轉發也會記錄可辨識來源。舊版已送出的訊息另由目的地歷史檢查。Discord 自行送入的原生貼文仍然可見。純短網址、無標題或多項更新混合時，自動辨識有限；確認前須核對目的地。NBA 的共用頁連結本身無法識別哪一版。已確認稿沿用原來選單輸入相同識別碼即可載入或處理中斷的送達。每篇主要來源及所有遊戲仍共享既有翻譯服務的限制。

離線入口測試可用 `python -m unittest discover -s tests -p test_reviewed_games_publisher.py -v`。以 `python scripts/verify.py all` 完整驗證。回退前核對未完成收據，保留 SQLite；舊版不會辨識新遊戲的收據。
