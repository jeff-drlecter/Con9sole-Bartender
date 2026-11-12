# 社群日誌 v2

2026-11-12 核對及替換：Carl-bot 原本將訊息編輯／刪除／批次刪除送到 message-log、成員資料及離開送到 member-log、語音出入送到 voice-log。Carl 的加入、伺服器、身份組結構及討論串事件當時未開啟。Bartender 的 WelcomeLog、TempVC、RoleChannelEmojiLog 又將成員／角色／語音／結構事件直接送到 server-log，存在重複與分散。舊 send_log 無持久佇列，送出失敗只寫執行日誌。

## 現行分工

| 類別 | 頻道 | 內容 |
| --- | --- | --- |
| server | 1401346745346297966 | 頻道、討論串、身份組、表情符號、伺服器設定；另列官方審核事件的操作者、對象 ID、原因及可取得的主要差異 |
| message | 1421103987599610018 | 編輯前後節錄、刪除、批次刪除；訊息／頻道 ID |
| member | 1421128161491419186 | 加入、離開、暱稱、身份組、帳戶名稱／頭像、禁言、封鎖／解除 |
| voice | 1421143797571784895 | 加入、離開、轉房、伺服器靜音／拒聽、直播／視訊；同一程序觀察到的頻道停留秒數 |

由 `CommunityAudit` 單一接管。WelcomeLog 保留公開歡迎訊息，TempVC 保留語音房生命週期，但不再各自送重複日誌。Carl Logging 需在四路實際派送驗收通過後關閉原已啟用事件；保留頻道路由，方便回復。Carl 的其他模組及 Discord 原生 AutoMod 不變。不要移除 Carl 原本供其他功能使用的權限。

## 可靠性及成本

- 使用既有 Gateway 事件；沒有逐事件輪詢審核 REST API，沒有額外外部服務或付費 API。
- 每 3 秒檢查本地 SQLite 待送佇列；各類每次最多 5 個 embed，整批不超過 5,500 字元，沒有事件時不呼叫 Discord。所有日誌 `silent=True`、`AllowedMentions.none()`。
- `/data/community_audit.sqlite3` 使用 WAL。事件編號可對照本地狀態及 Discord footer；支援確定性事件去重、重啟接續待送、403 等明確拒絕後退避重試。缺頻道／權限每 60 秒再試，保留待送。
- 網絡／5xx 結果不明或派送途中重啟，標記 `uncertain`，不自動重發以免重複。`/logging action:retry event:<完整ID>` 在人工核對原頻道後重試；`ack` 代表人工結案，不宣稱已成功派送。操作另寫日誌。
- 已送／已人工結案的本地事件保留最多 30 日；總量上限 20,000，滿額優先清理已解決事件。未解決紀錄不自動刪除；若全是未解決而滿額，拒絕新增並於執行日誌及狀態面板報錯。Discord 上已發日誌及歷史內容不定時刪除。

## 明確限制

- 不記語音內容。自我靜音／拒聽不記，以降低噪音；伺服器靜音／拒聽會記。
- 不下載附件，刪除只保留附件數。一般訊息原文不另建資料庫，只在編輯／刪除事件節錄目前快取最多 850 字元；年齡限制頻道只記資料，不複製原文。日誌頻道及舊 chatroom-logging 排除，已知 Bot／webhook 訊息不記。
- 無快取原文／作者會明示未知，不抓取或推算。批次刪除每批一筆，只列最多 40 個訊息 ID，不補存整批內容。
- 官方審核是獨立證據，不將最近一次審核操作者猜配到某條刪除訊息。一般離開不推斷為被踢。
- Gateway 斷線或 Bot 離線期間不能完整補記；會記錄恢復。程序重啟／斷線前的語音時間明示未知。需既有 View Audit Log 權限接收官方審核事件。
- 不改原頻道受眾。派送前要求目的地為本伺服器文字頻道、@everyone 不可見、Bot 可檢視／發訊息／embed；不向其他頻道 fallback。

## 操作及驗收

管理工具 → 系統狀態 → 社群日誌，或 `/logging`：檢查路由權限、Gateway、Intent、派送循環、佇列及最近錯誤。只有管理伺服器／管理員可操作，伺服器及每次權限均重查。

`/logging action:test` 向四路排入清楚標示的測試事件。必須在各實際頻道看到相符事件 ID，才可視為路由功能測試通過。這不等同真人加入／封鎖／轉房等事件的完整線上測試。離線測試涵蓋原文缺失、NSFW、不迴圈、去重、重啟未明狀態、重試、私有路由及訊息長度限制。

Carl 切換前開啟項目備份：Deleted messages、Edited messages、Purged messages、Members leaving、Member Role updates、Name changes、Avatar changes、Member bans、Member unbans、Member timeout、Member remove timeout、Join voice channel、Move between voice channels、Leave voice channel。其他 Logging 事件當時已關閉。
