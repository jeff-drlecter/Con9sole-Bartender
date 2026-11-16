> 本文是來源分支交接快照。06 整合修正、最新檢查及部署狀態見 [現行總表](CURRENT_INTEGRATION_STATUS.md)，不可將分支通過當作整合版通過。

# 02 → 03 / 06：私人操作權限與統一通知中心

狀態：02 程式與離線測試完成；Draft，**不可當作 03 已接通或可部署**。
未合併、未部署、未修改正式權限、未發 Discord 訊息。iPhone Mirroring／實機依 Jeff 指示略過。

## 核對基線與已完成項目

- 2026-11-15 UTC 再查 `main`：`15d8a9744ce5644e489db2a675b860a27dc78444`。
- [Fly deploy run 43696353088](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43696353088)：同 SHA，completed / success。這是部署工作流程證據，沒有另行登入 Fly 或驗證即時程序／Discord 畫面。
- 此 checkout / 上層沒有 `AGENTS.md`；沿用 Jeff 本輪提供的專案規則。
- 已核對 #172 / #173 與現有 `docs/COMMUNITY_ROUND2.md`、`APPROVED_COMMUNITY_POLICIES.md`。保留 Helper 後端授權、Tester 示範區隔離及停止一般活動流水；沒有重做該輪。
- 再查 open PR：#165–168 是前輪分支；未見本輪 03 個人提醒查詢／寫入服務。現有 `SquadPlans.member_status(guild,user_id,key)` 只有單局唯讀狀態，不能列出本人的約局或寫入同意；`ReminderView` 仍綁原頻道。

## 發現與修正

| 發現 | 本分支處理 | 限制 |
| --- | --- | --- |
| InterestRosterPages / ParticipantPages 翻頁沿用已載入資料 | 每次開啟、翻頁、刷新重新讀 REST 成員、角色、來源頻道／訊息；資料載入後再核對一次 | Discord 沒有跨請求的原子權限快照；無法收回先前已看見、截圖或快取的資料 |
| 單靠 gateway role cache 可沿用撤權前權限 | 在局部 guild snapshot 使用 REST roles + member + overwrites；不更改共用 gateway cache | REST 失敗即停止輸出；增加私人操作的 REST 請求量，正式延遲／限流未量測 |
| 私人討論串不能只看 parent View | 另驗證私人 thread membership；parent 亦重新讀取 | 無法查證即拒絕，沒有 Helper / Tester 特權旁路 |
| 名單成員離群、成為 Bot 或失去來源 View | 每次重新取成員及過濾；舊名稱不作成員身份依據 | 舊卡純文字參與名稱依既有規則保留並 escape，不推斷 ID |
| 通知混為單一遊戲訂閱清單 | 新私人通知中心分本局提醒 / 遊戲訂閱；單項管理、刷新、返回、原卡連結 | 本局提醒須等待下列 03 服務；沒有空清單假成功或 PlanBook fallback |
| 發送 receipt 混合 game + plan recipients | 新 receipt `origins` 記錄兩類來源；本人遊戲清單只納入 game 來源，uncertain 與 pending 分開 | 舊 receipt 無法追溯；見下方部署阻擋事項 |
| 遊戲取消原會 veto 合併 receipt 中的本局提醒 | 有來源證據的新 receipt 保留獨立 plan 候選；03 dispatcher 仍必須重查本局同意 | 不增加新發送通道／對象類型；不宣稱 03 完整交叉取消已驗收 |
| 無可用入口或約局功能未載入時只有錯誤文字 | 共用「選擇遊戲／求助或建議／先觀望／返回」；主選單及 FeatureButton 的 SquadCards / SquadPlans unavailable 路徑接入 | 03 內部 no-destination / paused 分支需由 03 接入；不修改其擁有檔案 |
| 私人新文案語言不完整 | HK / TW / 未選語言；未選語言與 TW 使用中性繁中，HK 使用廣東話；遊戲名／成員輸入不翻譯 | 不更動既有持久化機制或共用公開文案 |

原卡 persistent custom IDs 保留。舊主選單按鈕仍由 `SquadCards.menu_entry` 開新中心。舊 `SubscriptionView` 留相容類別，但呼叫者須明確提供 `channel_id` 才可操作；不能在第一次 callback 才推斷原來源。重啟前舊 ephemeral view 不保證繼續可按，應從原入口重開。

## 共用檔案方法範圍

`cogs/squad_cards.py` 只變更：

- `InterestRosterPages` / `ParticipantPages`：移至 `features/private_roster_views.py`，保留原 import 名稱。
- `FootprintView.show_participants` / `show_roster`：委派重新授權的私人 render。
- `FootprintView.toggle`：僅私人名單操作路徑，取得 consent lock 後重新核對來源，完成後重新載入私人名單。
- `SquadCards.menu_entry`：通知中心 UI 入口。

**未改** `_notify_interested_locked` / `notify_interested` / reconcile、約局卡狀態或任何 `cogs/squad_plans.py` / `features/squad_plans.py` 內容。03 合併時按上述方法範圍處理，不整檔覆蓋。

`features/squad_interest.py` 共用變更：`initialize` 增加 `origins TEXT NOT NULL DEFAULT '{}'`；`reserve` 在原交易內記錄 game/plan provenance；`delivery_users` 遊戲 withdrawal 不 veto 有證據的獨立 plan 候選；`own_preferences` 僅分類可證實 game 來源；新增唯讀 `unattributed_deliveries`。沒有寫入 PlanBook、建立新同意、重播 uncertain 或回填舊同意。

## 03 依賴：尚未收到的服務合約

以下為 **02 提議的 adapter 合約，不是聲稱 03 已提供**。03 可確認此合約，或提供真正合約後只改 `features/plan_reminder_client.py` 適配。缺失或版本不合時 UI 顯示「本局提醒服務暫未可用；這不代表你沒有提醒」。不得直接搬用 ReminderView 或讀寫 PlanBook / JSON / SQL。

```python
# bot.get_cog('SquadPlans').personal_reminders_v1
version = 1

async def list_for_member(guild, actor_id) -> dict:
    return {"complete": True, "rows": [
        {"id": "plan id", "game": "原遊戲名", "start": 1790000000,
         "status": "due", "enabled": False,
         "can_enable": True, "can_disable": False,
         "version": "opaque registration epoch + plan/consent revision",
         "url": "https://discord.com/channels/guild/channel/message"}
    ]}

async def set_for_member(guild, actor_id, plan_id, *, enabled, expected_version):
    return {"status": "updated"}  # or conflict / denied / unavailable
```

合約責任：

1. 03 每次 query / set 重新核對本人、guild、來源、最新成員與權限；只有本人報名且允許讀取的列可返回。不能帶其他成員名單；隱藏來源不回傳名稱／時間／連結。服務失敗不得以 `complete=True, rows=[]` 掩蓋。
2. `status` 可用 open / due / gathering / live / ended / cancelled / expired / unconfirmed / withdrawn；未知狀態 UI 保守顯示未確認。
3. `enabled`、`can_enable`、`can_disable` 是獨立明確 bool；對已開局、退出、改期需重確認及失權的限制由 03 決定並再次強制執行，不只依賴 UI disabled。
4. `version` 必須包含報名世代及同意版本；在同一鎖／交易中 compare-and-set。退出重報、改期、並發撤回、原卡操作或重啟，不可讓舊面板的 enable 復活舊同意。
5. 02 只 forward 原始 opaque version。錯誤／不確定寫入不自動重試，清除舊結果並提供重新整理。
6. `url` 只能是本次已授權來源卡；02 再限制 Discord 同 guild 卡片 URL 格式。隱藏來源的網址不可由服務送來。
7. Query 不可偷開提醒；set 不可寫遊戲訂閱。兩類同意的聯合發送檢查亦需獨立。

共用引導入口（已實作，可由 03 接入）：

```python
from core.newcomer_routes import show_next_steps
await show_next_steps(interaction, reason='no_destination')
# 功能暫停：reason='unavailable'
# 已 defer 可直接使用；替換既有私人面板時 replace=True。
# return_to=async_callback 可返回原私人流程；該 callback 自己仍須逐次授權。
```

不配置任何新頻道／角色。求助只會導向 `config.SUPPORT_CHANNEL_ID`，並重查 View、Read History、Send 及非 NSFW；沒有可證實入口便只提供選擇遊戲／先觀望／返回。選擇遊戲沿用 Discord `<id:customize>`，Bot 不代加角色。

## 06 部署前阻擋事項：舊 receipt 與 03 dispatcher

新 receipts 能區分來源；舊 `origins={}` 無法推斷是已消耗一次遊戲訂閱、單獨 plan reminder 或兩者。UI 只報未確認，不把它列成 game，也不回填同意。

**舊 receipt 的取消仍沿用原 veto；因此不能聲稱舊混合待發紀錄已具完整取消隔離。** 06 須在正式只讀盤點後，確認沒有活躍的未分類待發紀錄，或與 03 提供經驗證的遷移／隔離方案，再開放整合。不得猜測重建、重送 uncertain 或刪除歷史。此輪未查正式資料庫，不能宣稱數量為零。

原基線可用的唯讀盤點 SQL（在有授權的正式只讀連線執行；此分支未執行）：

```sql
SELECT d.state, COUNT(*) AS batches
FROM squad_interest_delivery d
WHERE d.state IN ('pending','uncertain')
AND NOT EXISTS (SELECT 1 FROM squad_ended_sessions e WHERE e.session_id=d.session_id)
GROUP BY d.state;
```

已升級 schema 時加 `AND d.origins='{}'` 查未分類 batch；這是 batch 數，不是成員數，無需輸出名單。

另須由 03 修正／核實 dispatcher 的交叉撤回邏輯：基線 `_notify_interested_locked` 在 plan user 退出／撤回時可能直接排除整個合併候選，包括仍有效的 game 訂閱。02 沒有越過檔案分工更改該方法。新的 receipt game-cancel 隔離測試不能替代這一反向案例的 03 端整合驗收。

## 權限與驗收矩陣

以下是離線 fixture／模擬，**沒有實際 Discord 帳號登入或點按**。不是 Admin 代替普通成員通過。

| 身份 | 測試身份／角色 | 操作與結果 | 正式帳號驗收 |
| --- | --- | --- | --- |
| 普通成員 | fixture user 10，無管理權；另用真實 discord.py Member + role 77（Member）物件 | 唯讀來源（Send=False）可開私人中心；撤 View / History、REST role 撤權、換 guild/channel、來源刪除即停止新資料 | 未驗證，沒有可記錄的真實帳號 ID／角色清單 |
| Helper | fixture user 10 + Helpers 名稱，無 Admin | 來源失權同樣拒絕；不因 Helper 放寬。保留上一輪 Helper 授權測試 | 未驗證，沒有使用 Helper 帳號 |
| Tester | fixture user 10 + Tester 名稱，無 Admin | 來源失權同樣拒絕；保留正式 Helper 工具拒絕／示範區測試 | 未驗證，沒有使用 Tester 帳號 |
| 其他人 | fixture user 11 | 無法操作 user 10 的私人名單、引導／通知中心 | 未驗證 |

沒有正式角色／頻道權限差異需要套用：本 PR 改動數為零。若正常成員沒有既有可見入口，須由 06 根據真正帳號權限另列精確差異交 Jeff；不可用 Bot 繞過。

## 測試命令與證據

Python 3.12.14，本地依鎖檔 `--require-hashes` 安裝；GitHub CI 使用 repository 既定 Python 3.11，結果以 PR checks 為準。

```sh
python -m pip install --require-hashes -r requirements.txt
python -m compileall -q core features cogs tests
python -m unittest discover -s tests -p 'test_private_notification_center.py' -v
python -m unittest discover -s tests -v
git diff --check
```

新測試檔 17 項；完整 suite **877 tests / OK**。既有套件輸出包含既有 deprecation warnings 與刻意失敗的錯誤處理日誌，並非額外驗收。

| 驗收項目 | 證據 | 結論 |
| --- | --- | --- |
| 開名單 → 撤權 → 翻頁／刷新 | `test_both_rosters_revoke_then_move_and_refresh_never_emit_old_snapshot`、REST-role、source deletion / private-thread tests | 程式測試通過；新輸出清空，不聲稱撤回舊資料 |
| 當前名單重新過濾 | departed / hidden / bot / changed display name fixtures | 通過 |
| 四種提醒／訂閱組合 | `test_four_consent_combinations...`、`test_reserved_plan_only_game_only_both_and_neither_are_separate` | UI 與真實本地 receipt store 通過；03 查詢用 fake，不能當真服務通過 |
| 各自取消不改對方 | fake 03 stale-version forward + 本地 receipt game-cancel / retry 測試 | 02 邊界通過；反向聯合發送及舊 receipt 阻擋見上 |
| 原卡／中心交替、重啟、舊同意不復活 | 既有 `test_squad_integration` withdrawal / retry / resubscribe、`test_signup_start` 生命週期回歸 | 原功能回歸通過；真實新 03 服務 CAS / 改期 / 並發整合未驗證 |
| 無遊戲、不可見求助、功能暫停及返回 | next-steps / paused-feature fixtures + helper/server-entry 回歸 | 通過；03 內部分支接入待 03 |
| HK / TW / 未選語言 | copy keys、實際 plans / route UI、遊戲原名及 mentions escaping | 通過；Discord 手機／電腦排版未實測 |
| Helper / Tester 隔離 | `test_helper_round2`、後端 staff policy 回歸 | 程式測試通過；不代表真帳號驗收 |

本輪沒有執行正式帳號操作、正式 API 寫入、真實通知／DM、EXP 修改、實機測試或任何部署。

## 回復與整合

- 分支 `codex/private-rosters-notification-center`，精確 commit 以 Draft PR head / 交付回覆為準。
- 06 只整合此 commit 的方法範圍；先解決 03 合約、dispatcher 反向隔離及未分類 receipts，再做非 Admin 身份驗收。
- 程式回復用 `git revert <此 PR commit>`（本輪未執行）。不用 restore 舊資料庫、舊 JSON 或成員偏好；不可藉回復復活舊同意。
- `origins` 是加欄位；舊程式可忽略，回復不用 DROP／覆寫資料。保留 pending / uncertain / cancellation evidence。回復會恢復基線已知私人頁面快照缺陷及混合取消語意，06 不應把回復當作安全驗收通過。
- 重啟可能令既有 ephemeral view 失效；持久原卡入口與資料不刪除。若要部署，語音、現有卡片、約局及通知的即時影響由 06 實際評估，沒有無中斷保證。
