# C9-GROWTH-04-BASELINE：06 待確認接口設計

狀態：**讀碼／設計完成；等待 C9-GROWTH-06-VERIFY 階段 A 實際交接與接口確認。未實作、未驗收、未部署。**

## 基準與證據界線

- 開始時已 fetch 並核對 main：`9565192ac5d9027b1468b51efc7108a8f3c57388`。
- checkout 與已檢索的 /workspace 範圍未見 AGENTS.md；本輪遵守 Jeff 貼出的新版專案指引。
- #181–185、#187 的成果已由 #188 整合；部分來源 PR 仍 Draft 不代表功能尚未整合，不重放舊分支。
- 最新部署紀錄採 #192 的追加結果，runtime SHA 同上述 main；docs/CURRENT_INTEGRATION_STATUS.md 的早期段落是歷史快照。本輪未直接讀正式 runtime。
- Jeff 已提供 2026-11-17 香港的正式觀察：Members 213（Bot／測試副帳未核實）；01:28 returns 首次可用 0／沒有成熟分母、DB 自 11/15 04:04、coverage 49055 秒；上週新約局 1／成熟 1／未開局 1、6 筆無建立日期、6 次累計抽樣錯誤；本週至 01:32 新約局 0。這些不是完整成員枚舉或全群活動證據。
- 舊 FC 看板／語音日誌早於新觀測庫，不能作 collector 故障證據；Native Onboarding OFF 不等於 Bot 入會流程失效。
- GitHub Issues／PR／checkout 未找到本輪 Task ID 的階段 A 完成交接。以上部署／舊報表不能取代階段 A。本 PR 僅供接口確認，不是完成程式的交付。

## 06-A 必須補交的依賴（不要求先改設定）

| 證據 | 用途 |
|---|---|
| 查詢時間／runtime 完整 SHA／來源連結 | 確認當前執行程式與已提供正式數據的時間差 |
| 成員取得方法、分頁是否耗盡、錯誤／重複 ID、開始／結束時間及報告 member_count | 區分完整枚舉與 cache；不要求提供公開成員名單 |
| 已確認自有測試／副帳的精確排除 ID 與確認來源，或明示未核實 | 排除有證據帳戶；不猜多帳戶屬同一人，也不排除所有 staff／Tester |
| observer 路由／SquadCards 範圍與當下 session 狀態摘要 | 區分心跳、已追蹤範圍、waiting／unknown 與實際合資格到場 |
| DB／表可讀性、來源欄位／日期缺漏、有效時間範圍、coverage 區段及必要排除 | 決定 7／28 日可支持範圍，不能只交最近心跳或累計錯誤 |
| 不能讀取或未保存的項目 | 以 unknown 保留，不要求重建過往原因 |

沒有直接操作其他 Chat 的工具；本接口由 GitHub Draft PR 提供，不能把「已提交」寫成「06 已接收／確認」。

## 建議 v1 契約（待 06 確認）

所有輸出只含聚合，無玩家 ID／名字。內部集合只供本次去重與 membership intersection，不能成為公開榜單。日期輸出 Unix 秒或帶 +08:00 的 ISO 格式，禁止無時區時間。

```json
{
  "schema_version": 1,
  "as_of": "帶時區的查詢截止時間",
  "window": {"start": "HK 起點", "end": "HK 右端不含", "timezone": "Asia/Hong_Kong", "days": 7},
  "source": {"kind": "observed_voice", "origins": ["linked", "natural"], "scope": "recorded SquadCards sessions"},
  "distinct_accounts": null,
  "observed_lower_bound": null,
  "current_members_only": false,
  "completeness": {
    "status": "unknown",
    "membership_enumeration": "not_requested",
    "coverage": "unknown",
    "test_account_registry": "unverified"
  },
  "exclusions": {"bots": "observer-filtered where proven", "confirmed_test_accounts": 0, "test_sessions": 0, "channels": 0},
  "unknown_reason": ["stage_a_not_received"]
}
```

上例 null／0 是欄位格式示例，**不是正式數字**。實際來源未讀取／失敗的排除數必須 null，不能寫成 0；registry confirmed count=0 亦不表示全部副帳已清查。

### 成員快照

- 另含 `snapshot_started_at`、`snapshot_finished_at`、`enumeration_method`、`enumeration_complete`、`atomic=false`、`reported_member_count`、`enumerated_distinct_accounts`。
- 完整取得 REST 成員列表、分頁正常耗盡且 ID 唯一後，才提供枚舉期間的 total_accounts／bot_accounts／non_bot_accounts。同步進出群意味它不是單點原子快照；若數量漂移或列表不完整則明示，確定總數為 null，局部已觀察數另列 lower_bound。
- cache／角色人次／Discord UI Members 數只能作旁證，不冒充枚舉。非 Bot 帳戶不叫「已驗證獨立真人」，不以帳戶去重推算人口。
- confirmed_owned_test_accounts 是經 06／Jeff 明確確認的子集，另列、不推測其餘非 Bot 是否副帳。沒有確認名冊時保留 unverified，不自動使用 Tester 或 staff Role 作排除。
- 請求失敗時不能將 guild.members 的 cache 當成成功 fallback。報表不得把完整查詢錯誤呈現為總帳號 0。

### 7／28 日觀測帳戶

- 建議採最近 7／28 **已完成香港日**，`end=查詢當日 00:00`、`start=end-days`；今日未完結部分若需要應獨立列「今日截至 as_of」，不偷換同一標籤。此日界方案待 06 確認。
- `outcome_attendance` 與 `outcome_visits` 合併按實際時間過濾，再按 guild/user 去重；linked/natural 先聯集，不能把兩類帳戶數相加。同局重入／跨日觀測也不能增加獨立帳戶數。
- `current_members_only=false` 為期間被觀察到的帳戶；true 為同批帳戶與完整當前成員集合的交集。兩者獨立呈現。當前集合不完整時 intersection 只能提供已知 lower_bound，不能把未找到的帳戶判定已離群。
- 新觀測有事件時的 Bot 過濾證據；舊資料沒有來源／日期／可核實資格時另列 unknown，不根據現在頻道名字補歷史。經確認測試帳戶、已知測試局、既有明確排除來源一律按證據排除。
- 本輪最小基線只計已有可核實到場。XP import／adjustment、邀請／任務獎勵、導航與管理查詢不計活動。不以 XP 總額推算遊玩。若 06-A 證明可讀的 text 事件具備有效來源、成功計分與排除證據，再另列有效文字來源，不將它暗中混入語音獨立帳戶。
- 觀測窗超出 DB 起點、coverage 有缺漏、來源／排除未核實時，顯示已觀察下限及 unknown_reason，不叫完整 7／28 日活躍人數。

### 心跳、追蹤範圍與資格（不得混合）

| 層次 | 目前程式可支持／未支持 |
|---|---|
| 心跳 | 成功 `_observe()` 即可寫成功區段，包括沒有任何合資格 session 的情況。不能解讀為全 server 正在被完整追蹤 |
| 已追蹤範圍 | `_observe()` 只巡 `SquadCards.state['sessions']`，不是遍歷全群所有語音並建場。路由／來源範圍需 06-A 確認 |
| 合資格到場 | linked 需要 plan/guild/session 一致及 live；natural 需要 session id + message。ended、waiting、unknown、AFK、找不到 channel 會略過；不能把略過的 members 填成到場 |
| 略過原因 | 舊程式未持久保存逐原因歷史；本輪不可補造。可提供**當下診斷快照**的 reason code 聚合及時間，不能叫歷史統計。是否需要新 additive 診斷由 06 確認，預設不新增持久追蹤 |

建議原因碼：member_list_incomplete、membership_read_failed、account_registry_unverified、source_unknown、date_unknown、coverage_gap、before_observation_start、no_eligible_session、waiting、link_mismatch、ended、afk、channel_unavailable、query_failed。沒有歷史證據的原因統一 historical_reason_not_recorded。

## 現有行為保留／非本輪範圍

保留首次觀察非入會日期、D0／D7／D28 香港日界成熟分母、coverage 缺漏不提供確定率、舊約局缺 created_at 不補填。沒有成熟樣本不能說零留存。雙人 120 秒仍為局數證據，不推算個人達標。

不改 EXP／Level／Ranking、角色、回鍋重置、03 路由／session／卡片生產、預約／Events／通知、正式開關或品牌。若 06-A 發現路由／生產問題，附唯讀重現交 01 協調 03，04 不擅改。

## 待開發路徑、測試及回復

- 範圍：原私人入口增「成員／觀測基線」，新增純聚合查詢；保留持久 button IDs，生成前後沿用 fresh Admin 驗證、ephemeral、無 DM／tag，私人靜態文案按 HK/TW/neutral。
- 規劃中的檔案：cogs/community_outcomes.py、features/community_outcomes.py／observed_returns.py 或小型專用聚合模組、scripts/inventory_outcomes.py、相應 tests。features/community_levels.py 僅作資料研究，不改獎勵邏輯。
- 測試矩陣：空庫／讀取失敗、不完整分頁／cache、Bot／已確認測試帳戶排除、跨來源聯集去重、HK 日界及 D7/D28 未成熟、缺來源／日期、有心跳無 session、waiting/unknown 略過、staff/Tester 正常活動仍計、Admin 允許／Helper 普通會員拒絕／途中撤權、查詢不修改 XP 或發額外訊息。
- 設計預設不需 migration：使用既有來源／visits／coverage 表與記憶體快照，無歷史回填。若 06-A 確認需要 additive 索引／診斷表，另列精確 migration、可重跑及回復方案再實作。
- 本設計 PR 的 diff 僅新增此文件，無程式／schema／設定變更。回復只需 revert 文件 commit；不能回復任何現行 DB／收據。
- 尚未執行新功能測試；文件檢查不能當成程式測試通過。正式資料、真人帳號與新功能均未驗證；iPhone Mirroring 按指示略過。

06 收件項目：先補階段 A 證據／確認上述契約，再由 04 實作與完整回歸，最後提交可驗收的開發 head。現時任務狀態是**阻塞／待 06-A；接口設計已準備**，不是「開發完成」或「已部署」。
