# Con9sole 會員等級 v1

## 現有 Amari 實測設定

2026-11-06 香港時間 23:04–23:08，在「🔑admins-指令」使用唯讀查詢：
`settings`、`multiplier show`、`rewards show`、`announce custom`、`announce level show`。
逐頁讀取了 10 個自訂等級公告。沒有改動 Amari 設定。

| 設定 | 實際結果 |
| --- | --- |
| Prefix | `:?` |
| 角色模式 | Replace 開、Accumulate 關 |
| 加入角色 | 無 |
| 離開清分 | 開 |
| 公告頻道 | 家用夠の成員等級日誌🎖️ |
| 公告 mention | 開 |
| Weekly Points | 開；未查得自動結算排程，不等於已自動每週重設 |
| 全服倍率 | 1 |
| 身份組倍率 | Server Booster ×2 |
| 頻道倍率 | 無 |
| 排除角色／頻道 | 兩者皆無 |
| 文字冷卻 | 60 秒 |
| 語音 XP | 開 |
| 語音倍率 | 5 |
| 語音結算 | 5 分鐘 |
| 語音最低人數 | 2 |
| 通用公告 | 恭喜 {user.ping} 升級! 依家你係 等級{level} |

| 等級 | 獎勵 | 自訂公告原文 |
| --- | --- | --- |
| 5 | 註冊會員 | 👋 {user} 升至 Lv.{level}，成為【註冊會員】！正式開展你嘅會員旅程啦～ |
| 15 | 活躍會員 | ✨ {user} 達到 Lv.{level}，升為【活躍會員】！繼續保持好表現！ |
| 30 | 常駐會員 | 💬 {user} 升到 Lv.{level}，晉升【常駐會員】，你已成為群內熟悉的存在～ |
| 50 | 高級會員 | 📈 {user} 成功達成 Lv.{level}，晉身【高級會員】行列，邁向社群中層！ |
| 75 | 資深會員 | 🛡️ {user} 獲得 Lv.{level} 成就，晉升為【資深會員】！長期守候有目共睹！ |
| 100 | 核心會員 | 🎯 {user} 升至 Lv.{level}，正式踏入【核心會員】階層，歡迎加入主力陣線！ |
| 150 | 白金會員 | 💎 {user} 現已晉升 Lv.{level}，榮獲【白金會員】稱號！高活躍代表！ |
| 200 | 黑金會員 | 🔥 {user} 升至 Lv.{level}，解鎖尊貴角色【黑金會員】！實至名歸！ |
| 300 | 榮譽會員 | 🏅 {user} 成為 Lv.{level} 的《榮譽會員》！你嘅持續參與係社群中不可多得！ |
| 400 | 傳奇會員 | 🎉 {user} 達成 Lv.{level}！正式晉升為【傳奇會員】👑 無人能及，傳奇由你創！ |

**範圍限制：**上述為 Amari 公開查詢回傳的伺服器設定；未取得內部資料庫、全體 XP 匯出、升級公式、公告全部等級／只限獎勵的隱藏開關，亦未實測語音靜音／AFK 排除細則。不宣稱取得未公開欄位。個人等級卡外觀不是伺服器設定。

## 新版行為

沿用現有 Bartender／單一 Fly machine／持久卷，不需要 AI、第三方付費 API、額外主機或新資料庫服務。`/data/community_levels.sqlite3` 是獨立 SQLite 檔，透過共用資料目錄解析規則定位。DB 操作均在 worker thread；寫入交易串行化。

- 新部署預設 `off`，不讀取戰鬥內容、不計 XP、不派角色、不發公告。
- `/levels admin` 或管理工具「等級管理」提供「開始試行／暫停計分／重新整理」按鈕。只有管理伺服器／Administrator 可改設定，Helper 不會因此獲得改 XP 權限。
- `preview` 記錄獨立 XP；不修改 Amari、不派角色、不發升級公告。試行 XP 可在接管時保留。
- `active` 正式模式才派獎勵；只保留最高合資格角色。只在跨越獎勵階梯時公告，預設不 ping。
- 文字 1 XP／60 秒；Booster ×2。文字及互動**共用**冷卻，避免同時聊天及刷按鈕雙倍累積。
- Bot 活動每日最多 60 次；Booster 每次 2 XP，所以上限是次數而非 XP。可用 `/levels rates` 調整。
- 成功送出飲品（給操作人計）、成功訂閱開局通知可計互動；查看名單、Menu、取消訂閱、失敗操作不計。
- 同一 topic／同一玩家的訂閱只認一個事件 ID，7 天內反覆取消再登記不重複加分。
- Adventure Frontier：僅信任管理員明確指定的 Bot ID + 討論串 ID；排除 webhook。識別普通攻擊、寵物攻擊、死亡、護符救命與擊殺的公開結果。
- 玩家卡須有單一 Discord mention，且卡內帳戶名等於該成員當前 username。由此建立 hashed-name → Discord ID 對應；寵物卡只可沿用已確認對應。改名／對應不明時跳過，不能猜。
- 戰鬥以原訊息 ID 去重；冷卻內不加分的訊息也會標記，不能稍後編輯重領。只處理新卡及建立 120 秒內的更新，不掃歷史補分。這是結果歸屬，不是直接接收第三方按鈕事件。
- 語音需至少 2 位有效真人，排除 AFK channel、AFK、耳聾、舞台聽眾；self mute 仍可計（靜音參與亦屬在場）。每 5 分鐘 25 XP 是參照現有倍率 5 × 5 分鐘採用的新版設定，未宣稱量測 Amari 每輪實際入帳。
- 語音狀態改變會保守重算該房的連續時間；不足 2 人不累積；重啟不追補停機時間。
- 總 XP 分文字／互動／語音／匯入基準；`/levels rank` 或主頁「會員等級」查看。
- `/levels leaderboard weekly:true` 使用香港時間星期一 00:00 的 ISO 週，無需手動重設。舊週紀錄保留；調整／匯入不進每週榜。
- 離開伺服器保留 XP；不刪除舊 Amari 資料。
- 持久化 XP、每週彙總、冷卻、7 天事件 ID、hash 對應；不保存原始聊天／戰鬥內容或明文 username。管理調整原因保留作審計，不能填 token 等機密。

## 指令

| 指令 | 用途 |
| --- | --- |
| `/levels rank [member]` | 私人等級卡及來源明細 |
| `/levels leaderboard [weekly]` | 私人 Top 10 |
| `/levels admin` | 設定摘要及試行按鈕 |
| `/levels source bot channel [remove]` | Adventure Frontier 來源白名單，需選討論串 |
| `/levels inspect channel message_id` | 只讀診斷白名單戰鬥卡格式，不建立對應／不計 XP |
| `/levels rates` | 冷卻、每日互動次數、語音分鐘／XP |
| `/levels exclude [channel/role] [remove]` | 排除頻道／分類／forum／身份組，thread 繼承 parent 排除 |
| `/levels reward level role [remove]` | 明確設定獎勵角色，不猜角色名稱／ID |
| `/levels adjust member delta reason` | 管理調整並保存原因，不進週榜 |
| `/levels import_levels file [commit]` | CSV 預覽或一次性匯入已確認等級基準 |
| `/levels activate ...` | 確認基準已核對、Amari 派角色已停用後正式接管 |

## 舊資料及上線步驟

**這不是無損 Amari XP 搬遷。** 目前沒有可靠的全體 XP 匯出及官方公式，因此不能擅自把所有人設為 0，也不能聲稱原 XP 及級內進度已保留。

1. 經測試／審核部署程式，預設仍為 off。
2. 管理員設定 Adventure Frontier 的實際 Bot + thread 白名單。
3. 用 `/levels inspect` 對現有玩家卡及寵物卡做唯讀診斷，然後開始試行；真人實際操作一次確認 XP 與歸屬。這一步尚未在線上驗證。
4. 用 `/levels exclude` 排除管理、log、測試、公告等不應賺分的位置（目前 Amari 沒有排除頻道，不自動猜哪些應排除）。
5. 準備已核對的 `user_id,level` CSV（不可用只有角色推定出的級別假裝完整等級）。`commit:false` 預覽無寫入；`commit:true` 一次性加入等級基準，保留已賺試行 XP。禁止第二次匯入與 active 模式匯入。
6. 新版採**明確獨立曲線**：達到 L 級總基準 `50 × L × (L+1)`；這不是 Amari 公式。CSV 保留等級基準，**不保留 Amari 級內進度**。如要完整進度，必須先取得官方原始資料／公式並追加驗證後才接管。
7. `/levels reward` 配置上述 10 個已核對獎勵角色，Bot 角色需較高且有 Manage Roles。程式不建立／提升角色權限。
8. 停用 Amari 的等級角色派發（這次尚未操作），核對資料及計分速度，才執行 `/levels activate amari_rewards_disabled:true baseline_verified:true announcement:...`。
9. 啟用後在下一次合資格 XP 更新時同步最高等級角色；沒有全員批量剝除／重派。

若不接受損失 Amari 級內進度，保持 preview，等無損搬遷方法確認後再接管。停用新版可在管理面板按「暫停計分」；不刪庫、不重設會員。

## 驗證及限制

離線測試覆蓋並行去重、重啟冷卻、共用冷卻、活動上限、香港週界、來源隔離、Bot／webhook 排除、玩家／寵物歸屬、預覽不改角色、匯入去重及級別邊界；整個 repository suite 亦需通過。

尚未驗證：線上原始 Adventure Frontier Embed 是否完全符合 parser、全體 Amari 名單完整度、Fly 當前剩餘記憶體。公開頁面的文字可讀不等於 Discord gateway 已驗證。現有主機設定為 shared CPU ×1／256MB，有持久卷；低額外消耗是設計目標，不是實測帳單保證。
