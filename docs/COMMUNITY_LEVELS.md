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

## Auditor 狀態（2026-11-06）

**NO-GO：未可正式取代 Amari。** 審核及未通過的驗收門檻見 [LEVEL_AUDIT.md](LEVEL_AUDIT.md)。`activate` 已有程式碼層封鎖，不能靠勾選兩個確認繞過；只匯入等級的 `commit:true` 同樣封鎖。

## 新版行為

沿用現有 Bartender／單一 Fly machine／持久卷，不需要 AI、第三方付費 API、額外主機或新資料庫服務。`/data/community_levels.sqlite3` 是獨立 SQLite 檔，透過共用資料目錄解析規則定位。DB 操作均在 worker thread；寫入交易串行化。

- 新部署預設 `off`，不讀取戰鬥內容、不計 XP、不派角色、不發公告。
- `/levels admin` 或管理工具「等級管理」提供「開始試行／暫停計分／重新整理」按鈕。只有管理伺服器／Administrator 可改設定，Helper 不會因此獲得改 XP 權限。
- `preview` 記錄獨立 XP；不修改 Amari、不派角色、不發升級公告。試行 XP 可在接管時保留。
- `active` 正式模式才派獎勵，但本版接管入口已鎖定。角色寫入串行，讀最新持久 XP 及真實 Discord 成員角色；暫停確認會等待正在執行的角色寫入結束。只在跨越獎勵階梯時公告，預設不 ping。公告持久水位防止延遲事件重發，失敗後在下一次核對重試；角色派發失敗不宣布已成為會員。
- 文字 1 XP／60 秒；Booster ×2。文字及互動**共用**冷卻，避免同時聊天及刷按鈕雙倍累積。
- Bot 活動每日最多 60 次；Booster 每次 2 XP，所以上限是次數而非 XP。可用 `/levels rates` 調整。
- 成功送出飲品（給操作人計）、成功訂閱開局通知可計互動；查看名單、Menu、取消訂閱、失敗操作不計。
- 同一 topic／同一玩家的訂閱只認一個事件 ID，7 天內反覆取消再登記不重複加分。
- Adventure Frontier：僅信任管理員明確指定的 Bot ID + 討論串 ID；排除 webhook。識別普通攻擊、寵物攻擊、死亡、護符救命與擊殺的公開結果。
- 玩家卡須有單一 Discord mention，且卡內帳戶名等於該成員當前 username。由此建立 hashed-name → Discord ID 對應；寵物卡只可沿用已確認對應。改名／對應不明時跳過，不能猜。
- 戰鬥以原訊息 ID 去重；冷卻內不加分的訊息也會標記，不能稍後編輯重領。只處理新卡及建立 120 秒內的更新，不掃歷史補分。這是結果歸屬，不是直接接收第三方按鈕事件。
- 語音需至少 2 位有效真人，排除 AFK channel、AFK、耳聾、舞台聽眾；self mute 仍可計（靜音參與亦屬在場）。每 5 分鐘 25 XP 是參照現有倍率 5 × 5 分鐘採用的新版設定，未宣稱量測 Amari 每輪實際入帳。
- 只重算真正改變合資格狀態的人；靜音、直播、鏡頭切換不重設全房時間。三人減至兩人保留餘下兩人的時間；不足兩人清除該房計時。Gateway 斷線／未 ready 不計分，恢復後重新開始，不追補未知離線時間。
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
| `/levels import_levels file [commit]` | 只准 CSV 預覽；等級寫入已被 auditor 封鎖 |
| `/levels activate ...` | 本版鎖定；未達無損搬遷及實測條件不能啟用 |

## 舊資料及上線步驟

**現時不可正式搬遷。** 只提供試行／預覽，不會自動將會員清零或拿走角色。

1. 可經審核部署 off／preview，Amari 仍是正式資料來源；不可同時讓兩個 Bot 派等級角色。
2. 指定真實 Bot + thread 白名單，讀取真實 gateway battle embeds，將去識別化樣本加入測試，完成實際玩家及寵物一次入帳驗收。
3. 完整匯出所有範圍內會員的 Discord ID、原始總 XP、等級、級內進度、週榜、獎勵角色；驗證人數、欄位語義及雜湊。當前帳戶 Developer Portal 顯示沒有 access，未取得此快照。
4. 新曲線依現行官方 [XP Info](https://amaribot.com/xp-info) 表：L=0 時 0；L≥1 時達級總 XP 為 `20 × (L−1)² + 35`。已核對 Lv.1–100 及 Lv.390–490 的表例子，包含所有現有獎勵最高 Lv.400（3,184,055 XP）。網站標註 estimated，仍需與真人 Amari rank／實際入帳做 runtime 對照。原型舊自訂曲線已移除。
5. 確立共同切換時間 T。試行是測試資料，不可把 T 時刻 Amari 全量快照直接加上 T 之前的試行文字／語音 XP；兩者已包含相同活動。需按來源及時間建立互斥遷移策略，測試不重複也不漏分。現有 ledger 沒有足夠逐筆金額來源供安全重建，因此舊等級寫入入口已封鎖。
6. 完成 ledger／設定／角色備份及還原演練，驗證停機、重啟、REST 403、資料庫失敗及切回 Amari 的 post-cutover XP 處理。
7. 核對全部 10 個角色、角色權限／排序、公告頻道權限及自訂公告；現時 generic milestone 公告尚未完整重現 Amari 的 10 個模板及其他公告模式。
8. Auditor 根據驗收證據批准後，才另行改程式解除接管封鎖；兩個布林確認不構成批准證據。

暫停只停止日後計分／角色操作，不等於還原已修改角色，也不會將新版 XP 同步回 Amari。不能將部署版本回滾當作資料／角色回滾。

## 驗證及限制

離線測試覆蓋並行去重、重啟冷卻、共用冷卻、活動上限、香港週界、來源隔離、Bot／webhook 排除、玩家／寵物歸屬、預覽不改角色、匯入去重及級別邊界；整個 repository suite 亦需通過。

尚未驗證：線上原始 Adventure Frontier Embed 是否完全符合 parser、全體 Amari 名單完整度、Fly 當前剩餘記憶體。公開頁面的文字可讀不等於 Discord gateway 已驗證。現有主機設定為 shared CPU ×1／256MB，有持久卷；低額外消耗是設計目標，不是實測帳單保證。

公告可靠性限制：成功送出後、寫入 notice 水位前若 process crash，Discord REST 與 SQLite 無法同一交易，仍有重發窗口。未宣稱 exactly-once。角色／公告的 HTTP 失敗目前在下一次合資格核對才重試，尚未有持久背景重試佇列。

## Follow-up compatibility update

The auditor-driven continuation supersedes prototype policy differences above where applicable:

- Defaults now follow the observed source: all-level announcements, ping on, ten original custom templates, leave-clears-XP on. `/levels announcements` edits templates/mode; `/levels leave_policy` can select retention.
- `/levels rank` includes personal total rank. `/levels leaderboard page:... period:YYYY-Www` supports pagination/history; `period:amari-legacy` preserves the imported source counter. `/levels winners` previews top3 and can publish in active mode; old counters are not deleted.
- Automatic persistent role/notice repair runs with backoff while ready/active. This supersedes the earlier next-interaction-only retry limitation. The crash-after-send-before-ack ambiguity still applies.
- Raw snapshot migration and recovery primitives now exist, with executable failure tests. They are offline-only and do not remove `REPLACEMENT_READY=False`. The level-only Discord import remains blocked.

Offline transfer commands (Bot must be stopped and feature off):

```bash
python scripts/level_transfer.py --db /data/community_levels.sqlite3 --guild GUILD_ID --offline backup --output /data/levels-before.sqlite3
python scripts/level_transfer.py --db /data/community_levels.sqlite3 --guild GUILD_ID --offline import-snapshot --snapshot /secure/amari.json --roster /secure/independent_ids.json --source-count SOURCE_COUNT --backup /data/levels-before-import.sqlite3
# Add --commit only after preview, authoritative source and cutoff evidence are reviewed.
python scripts/level_transfer.py --db /data/community_levels.sqlite3 --guild GUILD_ID --offline restore --backup /data/levels-before.sqlite3 --sha256 BACKUP_SHA --checkpoint /data/levels-before-restore.sqlite3
```

Snapshot schema1 requires `source:amari`, guild_id, UTC captured_at/cutover_at/source_frozen_at, explicit source weekly_period, and users containing user_id/total_xp/level/level_xp/weekly_xp. Source frozen_at must equal the common cutover timestamp. IDs/expected count are independently supplied; the snapshot cannot certify itself complete. The current tool imports XP/weekly counters only; settings/role snapshots must be separately reviewed and restored through a safe plan. A restored SQLite DB does not by itself restore Discord roles or write new XP back into Amari.

`/levels inspect ... raw_private:true` is a trusted-source-only Administrator diagnostic that returns the real embed schema privately. It does not credit XP or alter bindings. Default unsupported formats return structure-only metadata. Source allowlist and both channel/history read permissions are required before any content export. Review and sanitize captured fixtures before publishing them.

Live diagnostic UX correction: Discord's channel picker may omit old/unjoined threads. `/levels source_card message_link:...` derives the exact Bot+thread from an explicitly selected card, checks guild/user read permissions, and joins active threads without unarchiving old ones. `/levels inspect_link message_link:...` uses the same guarded lookup. Configured threads are joined when they become active; uncached edit events use a guarded fetch fallback. This avoids guessing a channel from picker defaults.
