# FC 27 官方更新直收試作

私人預覽以 EA 公開文章的標題、網址及自撰短摘要重播。執行時只會讀寫臨時 SQLite 及印出結果。正式 Bot 沒有載入這個收集器，也沒有可打開它的環境變數。現行九個頻道的 Discord 原生回覆流程見[操作文件](GTA_TRANSLATION.md)。

## 來源及啟用阻塞

2026-11-26 核對了[EA SPORTS FC 27 News](https://www.ea.com/games/ea-sports-fc/fc-27/news)及[英文 Game Info Hub](https://forums.ea.com/category/ea-sports-fc-en/blog/ea-sports-fc-game-info-hub-en)。兩邊都有 Title Update。Hub 的官方原帖由 EA_Vendcera 發表，原帖署名帶有 Community Manager 身份。留言、會員討論、精選列表內其他連結均不能作為官方證據。

EA 在 [www.ea.com 的 robots.txt](https://www.ea.com/robots.txt) 明示自動擷取須取得書面授權。[Forums 的 robots.txt](https://forums.ea.com/robots.txt) 另有限制部分 RSS 路徑。已找到的[官方 RSS](https://news.ea.com/media-resources/rss-feeds/default.aspx)列的是新聞稿，未核實能涵蓋以上兩個索引或完整 Patch Notes。今版沒有 EA HTTP adapter、HTML 擷取、搜尋代抓或 Discord 發送端。

啟用前要取得可合法自動訂閱及轉述的官方來源，並用實際結構核對文章的遊戲、英文版、原帖署名與版主身份、來源完整性、重複文章關係，以及官方資料產生短摘要的方式。預覽的作者名稱／職級來自經人手核對的 fixture。將任意輸入填上相同字串不足以驗證作者。取得來源後，還要驗證斷線恢復、分頁、水位、429 的 Retry-After、實際流量及私下驗收。

## 私人預覽

在 repository 根目錄用 Python 3.11 執行：

```sh
python scripts/preview_fc27_updates.py --metrics
python scripts/preview_fc27_updates.py --source-only
python -m unittest discover -s tests -p test_fc27_updates.py -v
python -m unittest discover -s tests -p test_gta_translation.py -v
python scripts/verify.py all
```

首個完整快照把 v1.2 記為基線。下一輪讀入 v1.3，第三輪重播同一批。結果應有兩張預覽卡。網址指向英文官網或從原帖署名核對的官方論壇；示範連結用原文實際存在、靠近示範的文字定位。客戶端不支援文字定位時，仍能打開文章。整個預覽不讀取任何影音。

- [v1.2 官網](https://www.ea.com/games/ea-sports-fc/fc-27/news/fc27-title-update-v1-2-0)及[論壇](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-2/13860352)標題分別寫 v1.2.0 及 v1.2。同一款遊戲、完整標題類型及版本構成同一收據。
- [v1.3 Pitch Notes 官網](https://www.ea.com/games/ea-sports-fc/fc-27/news/update-v1-3-pitch-notes)及[論壇鏡像](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-3-0-pitch-notes/13897390)共用一張卡。官網遲到時更新已存原文連結，不會重新扣額。[同版完整 Patch Notes](https://forums.ea.com/blog/ea-sports-fc-game-info-hub-en/ea-sports-fc%E2%84%A2-27--title-update-v1-3-0/13897645)有獨立收據。其他論壇標題須有已核實的官網對應原文，未能確認時整輪報錯。
- 任一索引缺失、為空、超過 100 項、內容無效或身份有疑問，兩邊都不入帳。第一輪不補發歷史。每個串流最多讀 2 MiB，每次讀取逾時 15 秒。連線或逾時失敗最多重試兩次，分別等 1、2 秒，耗盡後傳回錯誤。每輪只可在持久時鐘上認領一次，下一輪相隔至少 60 分鐘。
- 每篇先以 SQLite 交易認領，再從原有香港月份帳本扣去實際送翻譯的短摘要字元。額度不足就直接保留原文連結。翻譯替身失敗或認領後程序中止，卡仍提供原文；逾時結果不會覆寫。此處沒有真實翻譯或 Discord 送達收據。

## Discord 先到和後到

本 Draft 的直收輸出只在本機。Discord 先到或後到，都只有現行 relay 能向頻道發出 Bot 回覆。若源頭一直沒有 Publish，正式環境仍然收不到該篇。其他八個遊戲繼續沿用既有程式。

日後接上獲准來源時，需要一次切換 FC27 出帖責任。上線前要排清既有 FC 待翻譯、待送達及不確定收據，訂明新來源的起始水位。切換後，同一篇 relay 先到須先擋在翻譯扣額之前，官方先到則用官方文章收據阻止後來的 relay 再翻譯。來源中斷時不自動改走 Discord。兩種次序都要用實際 adapter 與 Bot listener 離線整合驗證，並另行核准發送。這份 Draft 不能保證把兩個發送流程同時啟用仍可去重。Discord Follow 本身顯示的轉發並非 Bot 可自行抑制的貼文。

## 成本

| 項目 | 數值及依據 |
| --- | --- |
| 授權來源接通後的基本請求 | 兩個索引每 60 分鐘各一次，48 次／日，30 日 1,440 次。正文與有限重試另計。 |
| 本機重播一次 | Python 3.11／macOS，全流程三輪；兩張卡、翻譯替身兩次，共 174 個原文字元。實測資料處理約 11 ms，tracemalloc 約 32 KB，連 Python 解譯器的程序記憶體峰值約 30.4 MB。 |
| 網絡 | 預覽 0 HTTP 請求、0 bytes。一次性的兩個 robots.txt 回應正文合共 2,391 bytes。沒有獲准的正式來源樣本，實際每次索引／正文的 HTTP request bytes、回應 bytes、網絡延遲與 Fly 記憶體增量均未量度。 |
| 服務費 | 本版無新套件、服務、付費 API 或正式用量。日後沿用現有 Bot 與 Apps Script，共享每月 450,000 字元；新增月費目標 HK$0，實際流量及環境配額仍待量度。 |
| 維護 | 接上真實來源才需要監看格式、索引分頁、官方發帖者／身份改動及連結漂移，並用一篇同時見於兩站的更新重驗。 |
