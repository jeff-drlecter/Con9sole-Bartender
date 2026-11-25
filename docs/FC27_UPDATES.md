# FC 27 官方更新直收試作

預設私人預覽重現 2026-11-25 [FC27 v1.3.0 Pitch Notes](https://www.ea.com/games/ea-sports-fc/fc-27/news/update-v1-3-pitch-notes) 的版面。藍色主帖放繁中全文，主帖下的「🟪 English Original」討論串按原來次序放英文。範例中的雙語正文均為自撰演練文字。程式只在本機組裝訊息，正式 Bot 沒有載入收集器或全文發送端。現行九個遊戲頻道的原生回覆見[操作文件](GTA_TRANSLATION.md)。

## 來源及啟用阻塞

2026-11-26 核對了[EA SPORTS FC 27 News](https://www.ea.com/games/ea-sports-fc/fc-27/news)及[英文 Game Info Hub](https://forums.ea.com/category/ea-sports-fc-en/blog/ea-sports-fc-game-info-hub-en)。兩邊都有 Title Update。Hub 的官方原帖由 EA_Vendcera 發表，原帖署名帶有 Community Manager 身份。留言、會員討論、精選列表內其他連結均不能作為官方證據。

EA 在 [www.ea.com 的 robots.txt](https://www.ea.com/robots.txt) 明示自動擷取須取得書面授權。[Forums 的 robots.txt](https://forums.ea.com/robots.txt) 另有限制部分 RSS 路徑。已找到的[官方 RSS](https://news.ea.com/media-resources/rss-feeds/default.aspx)列的是新聞稿，未核實能涵蓋以上兩個索引或完整 Patch Notes。今版沒有 EA HTTP adapter、HTML 擷取、搜尋代抓或 Discord 發送端。

正式啟用前，有四項驗收仍待完成。

1. **來源與再發布權利。** 核實可自動讀取的 EA 英文來源，以及可在 Discord 重刊整篇英文、發布整篇繁中譯文、引用圖說及連回多媒體的權利與條款。可瀏覽或訂閱只證明讀取途徑。
2. **實際文章讀取。** 用獲准來源核對遊戲及英文版、原帖署名與版主身份、章節與正文邊界、清單、表格、圖說、原始網址及跨站去重，另驗分頁、水位、限流與恢復。
3. **完整翻譯。** 接駁現有翻譯服務前，驗證分段送譯與逐段對應、段落重試、原始連結還原及語意。整篇實際送譯字元必須計入九個頻道共用的 450,000 月額。遇到欠段或額度不足時標示待譯並暫停全文版。舊摘要流程的 174 字元樣本不能推算全文成本。
4. **Discord 送達。** 要有逐篇／逐段的持久送達收據，並驗證唯一主帖和英文討論串、重啟後續傳、結果不明時防重，以及與舊 relay 的切換。用獲准測試區核對權限、兩色顯示、文字附件、清單／表格在桌面及手機的顯示、來源連結與播放器可用性。

預覽的作者名稱／職級來自經人手核對的 fixture。將任意輸入填上相同字串不足以驗證作者。真實來源的流量、429 的 Retry-After 及斷線行為仍待量度。

## 私人預覽

在 repository 根目錄用 Python 3.11 執行：

```sh
python scripts/preview_fc27_updates.py --metrics
python scripts/preview_fc27_updates.py --json
python scripts/preview_fc27_updates.py --case illustrated-table --metrics
python scripts/preview_fc27_updates.py --source-only
python scripts/preview_fc27_updates.py --receipt-demo --metrics
python -m unittest discover -s tests -p test_fc27_updates.py -v
python -m unittest discover -s tests -p test_gta_translation.py -v
python scripts/verify.py all
```

預設輸出可儲存成私人 Markdown，`--json` 會顯示主帖、討論串所屬主帖、每個 embed 的實際色值，以及需要時的文字附件。`--source-only` 在全文模式以退出碼 2 指出缺譯，兩個訊息位置均無輸出。

**11 月 25 日主例。** 按該期文章的閱讀結構手動建立樣本：開首四段、封面位置、五組巢狀目錄、五個主題、十九個副題、合共四十個正文段落、四個文內示範、兩段示範圖說及結語署名。自撰段落按原文大約篇幅配置。圖文順序由逐段測試固定；封面連回原文頂部，控球、近柱、身體對抗、攔截四個示範連回 EA 原文相關位置。文字引用保留原有目的地及出現次序。未驗證直接影片網址或播放，預覽不載入媒體。原頁的共用導覽及網站頁尾不屬於正文。

主例的繁中全文在同一則主帖兩個藍色 embed 內讀完，英文分為四則紫色訊息。額外的 illustrated-table 範例才有表格，含 150 列資料、圖說、超長段落及影片網址。超出單一主帖的 embed 合計上限時，主帖提供開首及同帖完整 UTF-8 Markdown 附件，明確標示全文位置。英文討論串依序續頁。超長連結無法原樣放入 embed 時亦保留全文附件；若完整附件超出預覽限制，會明確中止。[Discord 訊息及 embed 限制](https://docs.discord.com/developers/resources/message#embed-limits)

**舊收據測試。** 明確加上 `--receipt-demo` 才會進入舊的短摘要及額度測試。首個完整快照把 v1.2 記為基線。下一輪讀入 v1.3，第三輪重播同一批。結果應有兩張預覽卡。網址指向英文官網或從原帖署名核對的官方論壇；示範連結用原文實際存在、靠近示範的文字定位。客戶端不支援文字定位時，仍能打開文章。整個預覽不讀取任何影音。

- [v1.2 官網](https://www.ea.com/games/ea-sports-fc/fc-27/news/fc27-title-update-v1-2-0)及[論壇](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-2/13860352)標題分別寫 v1.2.0 及 v1.2。同一款遊戲、完整標題類型及版本構成同一收據。
- [v1.3 Pitch Notes 官網](https://www.ea.com/games/ea-sports-fc/fc-27/news/update-v1-3-pitch-notes)及[論壇鏡像](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-3-0-pitch-notes/13897390)共用一張卡。官網遲到時更新已存原文連結，不會重新扣額。[同版完整 Patch Notes](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-3-0/13897645)有獨立收據。論壇文章 ID、已核實的官網原文與完整標題類型都會連到同一張持久收據。其他論壇標題須有已核實的官網對應原文。無法確認、或新資料指向互相矛盾的歷史收據時，整輪回滾並報錯。
- 任一索引缺失、為空、超過 100 項、內容無效或身份有疑問，兩邊都不入帳。第一輪不補發歷史。每個串流最多讀 2 MiB，每次讀取逾時 15 秒。連線或逾時失敗最多重試兩次，分別等 1、2 秒，耗盡後傳回錯誤。每輪只可在持久時鐘上認領一次，下一輪相隔至少 60 分鐘。
- 每篇先以 SQLite 交易認領，再從原有香港月份帳本扣去實際送翻譯的短摘要字元。額度不足就直接保留原文連結。翻譯替身失敗或認領後程序中止，卡仍提供原文；逾時結果不會覆寫。此處沒有真實翻譯或 Discord 送達收據。

## Discord 先到和後到

本 Draft 的直收輸出只在本機。Discord 先到或後到，都只有現行 relay 能向頻道發出 Bot 回覆。若源頭一直沒有 Publish，正式環境仍然收不到該篇。其他八個遊戲繼續沿用既有程式。

日後接上獲准來源時，需要一次切換 FC27 出帖責任。上線前要排清既有 FC 待翻譯、待送達及不確定收據，訂明新來源的起始水位。切換後，同一篇 relay 先到須先擋在翻譯扣額之前，官方先到則用官方文章收據阻止後來的 relay 再翻譯。來源中斷時不自動改走 Discord。兩種次序都要用實際 adapter 與 Bot listener 離線整合驗證，並另行核准發送。這份 Draft 不能保證把兩個發送流程同時啟用仍可去重。Discord Follow 本身顯示的轉發並非 Bot 可自行抑制的貼文。

## 成本

| 項目 | 數值及依據 |
| --- | --- |
| 授權來源接通後的基本請求 | 兩個索引每 60 分鐘各一次，48 次／日，30 日 1,440 次。正文與有限重試另計。 |
| 全文排版樣本 | 74 個有序區塊，繁中 5,070、英文 12,627 個 UTF-16 單位（含連結及排版字元）；本機約 4–5 ms。預算未扣額，沒有呼叫翻譯服務。 |
| 舊收據測試一次 | Python 3.11／macOS，全流程三輪；兩張卡、翻譯替身兩次，共 174 個原文字元。實測資料處理約 8–11 ms，tracemalloc 約 32 KB，連 Python 解譯器的程序記憶體峰值約 30.5 MB。 |
| 網絡 | 預覽 0 HTTP 請求、0 bytes。一次性的兩個 robots.txt 回應正文合共 2,391 bytes。沒有獲准的正式來源樣本，實際每次索引／正文的 HTTP request bytes、回應 bytes、網絡延遲與 Fly 記憶體增量均未量度。 |
| 服務費 | 本版無新套件、服務、付費 API 或正式用量。日後沿用現有 Bot 與 Apps Script，共享每月 450,000 字元；新增月費目標 HK$0，實際流量及環境配額仍待量度。 |
| 維護 | 接上真實來源才需要監看格式、索引分頁、官方發帖者／身份改動及連結漂移，並用一篇同時見於兩站的更新重驗。 |
