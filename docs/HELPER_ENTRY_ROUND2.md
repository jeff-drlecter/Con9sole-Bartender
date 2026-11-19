# 02 → 06：Helper 資料範圍、新人入口及測試區（第二輪）

> **2026-11-15 狀態校正：** Part 1 實作為 PR #172／1e39801；接手時 Draft、未部署。已完整納入本輪整合分支；當時「不合併／不部署」限制已由 Jeff 第二輪明確授權取代。正式角色／頻道／年齡限制仍未授權套用。 本輪完整現況／待決／驗收界線以 [COMMUNITY_ROUND2.md](COMMUNITY_ROUND2.md) 及整合 PR 的部署證據為準。

2026-11-15，Asia/Hong_Kong。基線／最新 main：`2922760653488f03eacc0b728476d575aa19fd66`。GitHub main Fly Deploy `43635343478` completed/success；未直接登入 Fly 程序／DB 驗證。獨立分支 `codex/helper-scope-entry-round2`；本輪**不合併、不部署、不發 Discord 訊息、不改正式角色／頻道／年齡限制**。

## 發現及修正

| 輸出／操作 | 基線來源與授權 | 本輪程式差異 |
|---|---|---|
| 共用 Dashboard | `core/helper_dashboard.py` 文字／語音，`core/helper_plans.py` 約局；有 public_source | 沿用保守公開規則，新增排除 NSFW。只原位 message.edit；缺原面板 ID 改為停止，不再補發。沒有成員名單 |
| 舊活動流水 | `cogs/helper_sandbox.py::publish_pulse`，遊戲分類＋名稱黑名單，沒有 public_source；跨角色遊戲摘要發往共用頻道 | 停止 pulse 啟動、事件入庫及所有 publisher 發送路徑。保留原 Discord 訊息及 SQLite，既有未送事件也不補送。聊天／語音只保留原看板 |
| 私人活動／待接應 | 多處僅用 cached member/channel；Tester 也可進入 | 每次取 fresh member、Dashboard 及來源；活動用 fetch_channels，原訊息／討論串另取來源與 parent。私密 thread／NSFW 不轉貼。求助及招募在私人待接應入口；不自動發通知 |
| 求助跟進按鈕 | owner/admin 狀態轉換；來源權限原先用 cache | 選取及執行均重核來源；原訊息 fetch 後再驗 member/source；撤權／讀取失敗不改狀態，清除該次私人卡片。不新增取消／管理約局權限 |
| 約局詳情 | 上輪 03 member_status 逐局授權已完成 | 不重做約局；只將 Dashboard 前置資格改用統一 Helper/Admin 檢查，保留 03 的來源檢查 |
| 正式 Bot 授權 | Helper OR Tester OR Administrator | Helper（設定 ID）OR Administrator；須有 Dashboard View＋History。Tester-only 即使暫時仍看得到正式頻道，也不可使用正式資料／操作 |
| 原示範區 | 舊持久按鈕仍可能存在 | 原區只接受 `helper:sandbox:create:v1` 顯示虛構 Overview，不附真實返回／跟進按鈕；其他舊按鈕拒絕。Tester、Helper、Admin 仍需該區 View＋History |
| 新人固定入口 | 4 按鈕；無遊戲時只說「向 Helper 查詢」 | 保留舊 custom IDs，新增「求助／建議」「先觀望」。舊「選擇遊戲」私人回覆也提供兩項，可不等更新固定卡使用 |

公開資料規則：@everyone 可 View＋History（語音 View＋Connect），且任何 role/member 覆寫沒有相應 deny；排除 thread／NSFW。這是保守範圍，不因 Helper／Tester 有特殊身分而放寬。其他共用輸出已退役，無第二套活動廣播政策。舊訊息保留，不聲稱歷史暴露已消失。

私人列表有限量：待接應最多核對 20 候選、8 則；招募／新人最多掃 50 筆、8 行；約局沿用上輪 50／10。活動數由 Bot 啟動後觀察，無資料不代表沒有活動。Discord API 無跨多請求的原子權限快照，不能承諾撤權零延遲；每次重新操作會重驗。已顯示的私人訊息不會自動遠端收回。

## 新人三條路線

2026-11-19 程式更新：下表保留第二輪的入口紀錄。新版歡迎及指南卡提供「選擇遊戲」、「開主選單」和「搵 Helper」，並保留規則連結。新發出嘅個人歡迎卡另有「我是活人」。新人完成 Discord 守則確認後，可以喺自己嘅歡迎卡取得 Verified，解鎖完整會員功能。Helper 可用 `/撤回會員驗證` 停用該成員嘅自助驗證。未 Verified 嘅求助目的地係打招呼區（`1010456227769229355`），Verified 會員則去站務意見箱（`1364215234717548594`）。每次按下「搵 Helper」會核對當事人在來源及求助頻道的權限，確認可以留言才私下顯示頻道連結，由本人決定是否前往留言。無法確認時會提示查看入群步驟，並提供原生遊戲選擇入口。已發布六掣卡仍可使用。

| 路線 | 入口與條件 | 本輪狀態 |
|---|---|---|
| 有遊戲 → 組隊 | 原「選擇遊戲」→ `<id:customize>` →「約一局」；沿用 03 verified／可寫目標頻道檢查 | 程式測試；沒有代派角色或繞過加入權限 |
| 沒有合適遊戲 → 求助／建議 | 只用 config.SUPPORT_CHANNEL_ID `1362781427287986407`；fetch_member＋fetch_channel，須同 guild、Text/Forum、View＋History＋Send、非 NSFW | 取得實際權限前不宣稱新人成員可達。不可用就不輸出隱藏頻道連結，顯示短提示及原生自選入口；不搜尋／猜測新頻道、不新增頻道 |
| 先觀望 → 自選內容 → 日後返回遊戲 | 「先觀望」短回覆連 `<id:customize>`；可選聊天、新聞、直播，日後同一路徑選遊戲 | 不改原 onboarding 選項／預設；手機 UI及未完成入群審核帳號待驗 |

已知入口：Welcome `1010456227769229355`；設定 GUIDE_CHANNEL_ID `1279074807685578885`。本次未確認這兩個頻道及 SUPPORT 對無遊戲、未 Verified 新人的實際 effective permissions。無法由 Admin 可見推論。

固定已發布卡片不會僅因重啟新增按鈕：06 如獲准更新，只 edit 已確認 Bot 自己的既有卡片；缺 ID／找不到卡片時停止，不執行會補發新卡的 install fallback。Welcome 後續沿用原加入事件，沒有新增通知類型／對象。本輪沒有執行任何入口發布或更新。

## 正式權限及年齡限制差異方案（未套用）

| 對象 | 精確範圍／擬議變動 | 尚欠證據 |
|---|---|---|
| Helpers | role `1279071042249162856`；正式 Dashboard `1570639281225994301`；保留原 View／History，不授任何額外遊戲／新聞權限 | fresh live snapshot／Helper-only 角色實測 |
| 🧪 Tester | 正式 Dashboard 的此 role overwrite：`allow_after = allow_before & ~(1024 | 65536)`；deny 完全保留，其他 allow bits 完全保留；不刪 role、不改全伺服器權限、不 sync category | Tester role ID、before allow/deny 尚未 fresh 讀到。不能用名稱猜 ID；若有其他角色／member grant，移除此 grant 不等於已關閉頻道，須另列差異 |
| Helper＋Tester | Bot 按 Helper 授權；不要新增 Tester View deny 企圖阻擋所有雙角色成員 | 用完整角色／member overwrites 再算 effective permissions |
| 既有示範區 | 歷史 identity `1570093470666854411`；保留原 Tester view/history；不新增身份組、頻道或 grant。Bot 只顯示虛構示例 | 06 必須核對此 ID 仍為既有示範區、Bot 原卡 custom ID 及成員實際可見；未核實不投放入口 |
| 「問題回報」 | 只在核對唯一正確 channel ID、現值 nsfw=true，且 Jeff 確認不需年齡限制後：PATCH body **僅** `{"nsfw": false}` | channel ID／current flag／設定意圖未驗證。程式只在 duplicate 複製設定時涉及 nsfw，不能當作刻意或不必要的證據 |

**正式權限本輪實際差異：空。** Bot 授權改動只在分支，尚未上線。年齡限制亦未套用；沒有以「大概無必要」作判斷。

06 在私有環境執行 `python scripts/audit_helper_entry.py --live --member-id <普通成員> --member-id <Helper> --member-id <Tester>`；只 GET，不發訊息／改權限。或 `--snapshot /private/snapshot.json`，schema 沿用新聞 audit（guild/roles/channels/onboarding/members）。輸出：精確 role/channel、before→after overwrite、變更前後模擬矩陣、實際帳號角色／有效權限、問題回報單一欄位方案。多個同名 Tester 或多個「問題回報」時不猜 ID。輸出含內部角色／頻道映射，請勿貼到公開 PR／Tester 區。

拿到輸出後須補齊精確 ID／before/after 才可交 Jeff 決定：① Tester 是否退出正式 Dashboard、只留原示範；② 問題回報是否確定不需要年齡限制。若移除 Tester grant 後仍有其他 grants，不得順便擴大清理；列為新差異。無遊戲新人 SUPPORT 不可達時也需先提出該頻道最小 grant 方案，不能只改文案便稱路線已完成。

## 驗收矩陣與現場證據

| 身份 | 正式 Bot 功能 | 原示範 create | 原來源不可讀／無遊戲 | 本輪實測證據 |
|---|---|---|---|---|
| 普通新人／Verified 成員 | 拒絕 | 拒絕 | 求助連結逐次核權；不能用 Bot 加入隱藏遊戲 | 離線模型；真人未驗 |
| Helper-only | Dashboard View＋History 才可用 | 原區可讀才可看虛構卡 | 不顯示來源、不能跟進；原生遊戲選擇引導 | 模擬 fresh API／撤權測試；真人未驗 |
| Tester-only | 拒絕，即使頻道仍可見 | 原區 View＋History 才可看虛構卡 | 無真實資料／跟進返回入口 | 模擬舊按鈕路由；真人未驗 |
| Helper＋Tester | 按 Helper 規則 | 同上 | 不因 Tester 擴權 | 模擬測試；真人未驗 |
| Admin／Owner | 須於正確入口；Discord admin bypass 原生限制 | 可用；內容仍為虛構 | 不當成普通成員驗收替代 | 本輪亦未操作 Bot |

本輪 browser 新核對分頁只到 Discord「Choose an account」，jeff_drlecter／jeff_con9sole 均顯示「Please log in again」。沒有登入、切換角色、點 Bot 功能、發訊息或更改任何設定；舊 tab 被其他 session 佔用，未接管。上輪帳號角色是歷史資料，不拿來當作本輪有效角色證據。

## 測試、部署及回復

- 本地 Python 3.11.18、鎖定 requirements：826 tests 全部通過，無 skip；compileall／git diff --check 通過。CI 結果見 PR。新增覆蓋角色矩陣、舊按鈕拒絕、cached Helper 已撤權、來源在 fetch_message 後撤權不寫 DB、NSFW／private thread 排除、權限失敗不回傳求助連結、原位更新缺面板停止、舊 pulse 零發送／零 claim 且保留歷史，以及逐 bit 差異與多義目標阻擋。
- 06 整合前重新核對 main／本分支 head；完整測試。備份 helper_sandbox.sqlite3（SQLite backup API）、helper_pulse.sqlite3 與原 Dashboard message ID。沒有 schema migration；不碰03約局／提醒收據。
- 重啟可能影響暫存活動起點／私人短效卡；持久 IDs 保留。`verify_helper_sandbox.py` 不再要求 Tester 正式可見，改核對停用 pulse marker。程序觀察至少跨兩個原 pulse 週期：只有 Dashboard edit、沒有新流水，不要為驗收發測試訊息。
- 程式回復：優先 revert 個別入口／私人視圖修改，**保留停用 pulse 及 Helper-only gate**，避免重新洩漏／追加流水。若要整體退回舊版，須明確接受其舊共享政策並另行審核，不應當作無風險 rollback。DB／Discord 歷史保留，不重置面板 ID、不補發。
- 未來正式 overwrite 回復：僅當 current==after 時還原保存的 before，否則停止；不覆蓋期間人工更改。NSFW 回復僅 `{"nsfw": true}`（且原值確為 true）；不動其餘欄位。原生年齡限制變更是否引致平台日誌／通知須由06現場核對。
