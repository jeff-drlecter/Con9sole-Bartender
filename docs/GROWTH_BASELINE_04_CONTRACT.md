# C9-GROWTH-04-BASELINE：最小基線實作交接

狀態：**06 階段 A 已交接及接受開發契約；04 最小實作完成，待固定整合 head 的 06 驗收。未合併、未部署。**

## 基準與證據界線

- main 基準：`9565192ac5d9027b1468b51efc7108a8f3c57388`；本輪開始 head：`f253d17d9a576c00d9733168ff954a97f2e20a48`（原 #193 的接口設計）。交付 commit 由 01 的固定整合交接記錄。
- 本輪按專屬 Growth 工作樹及 01 指定檔案範圍實作；不重放已整合的舊 Draft PR。
- 06 的 2026-11-17 公開 A 交接已確認 runtime、路由範圍、原始來源表及 REST 分頁證據足以開發。04 只讀公開交接，沒有讀正式資料或成員名單。
- A 解除了先前的實作等待，不代表本次新功能已通過 B 驗收。正式聚合、帳戶及頻道識別資料留在私人交接，不收錄本文件、PR 或 Actions。
- 仍沒有完整、經明確確認的自有測試帳名冊。非 Bot 帳戶不等於獨立真人；staff／Tester 角色不作 blanket exclusion。

## 已實作入口與介面

沿用 `CommunityOutcomes.menu_entry` 的私人統計選單，新增「成員／觀測基線」，不新增 slash command。原有約局成效及首次觀察／再次到場入口保留，沒有更改 EXP、Level、Ranking、角色、通知或既有持久 button IDs。

新增純聚合模組 `features/growth_baseline.py`：

| 介面 | 契約 |
| --- | --- |
| `enumerate_members(guild)` | 用 `guild.fetch_members(limit=None)` 正常耗盡 Discord REST 分頁；只在本次記憶體保留去重 IDs／Bot IDs，不讀 `guild.members` 作 fallback |
| `MemberSnapshot.aggregate(registry=None)` | 只輸出聚合及 capture metadata；缺失／失敗的確定總數為 null，局部集合另列 lower bound |
| `TestAccountRegistry(ids, provenance)` | 只供明確的私人確認子集；必須有確認來源，不持久化、不由角色推測。runtime 未接入任何名冊，維持 unverified／null |
| `windows(as_of)` | 最近 7／28 個完整香港日及獨立 `today_partial`，每段均為 `[start,end)` |
| `baseline(path, guild, as_of, membership, ...)` | 使用既有表，`mode=ro`、`query_only=ON`，同一 read transaction 完成所有窗口；回傳 aggregate schema v1，沒有玩家 IDs／名字 |
| `render(result, code)` | HK／TW／neutral 私人靜態文案；時間有 `+08:00`；只呈現 aggregate 與明確未知 |

日期採 Unix 秒供機器使用；顯示用帶時區 ISO。內部集合不匯出、不作公開榜單。

### 成員枚舉

Metadata 包括開始／結束時間、REST 方法、正常耗盡、完整性、重複 ID 數、`atomic=false`、前後 reported member count 及 drift。Reported count 明確標記為 Gateway `guild.member_count` 旁證，**不是另一個 REST census**，cache／角色人次／UI Members 不能取代正常耗盡的 REST 結果。

- REST 失敗、重複 ID、reported count 漂移或與去重集合不符，均不提供確定成員總數；只提供已枚舉下限及原因碼。
- 正常耗盡且唯一、無已知數量矛盾，才標記 enumeration complete。reported count 不可得時保留 null；不能補造對照數。
- 完整枚舉仍跨時間、非單點原子快照；不能證明獨立真人、即時語音 occupancy 或歷史離群。
- 自有測試帳名冊未供應，`confirmed_owned_test_accounts=null`、`test_account_registry=unverified`。若日後接入明確確認子集，仍不表示所有副帳已識別；確認來源不輸出。

### 完整香港日的觀測帳戶

- 7／28 日 `end=查詢當日 HK 00:00`，`start=end-days`；今天 `[HK 00:00,as_of)` 另列，不能混入完整日。
- `outcome_attendance` 與 `outcome_visits` 按實際 `first_seen`、guild、已儲存 linked／natural source、非測試 session、明確 excluded source／voice channel，以及已確認測試帳子集過濾，然後聯集按 user 去重。session 首次日期及 visits 的 day 字串不取代事件時間。
- 同局重入、跨日 visits、linked／natural 跨來源只計一個帳戶。RSVP、滿員、XP、獎勵、導航或管理查詢不計入。
- Bot 排除沿用 observer 在事件發生時的非 Bot 過濾證據，不由今天的角色／名稱補造歷史資格。
- 缺少／不合法來源、orphan event、無可用日期另列 unknown。未定日期不能分配到特定窗口，因此保守地在各窗標示不可歸期的未知，不重建歷史。
- 每窗 `observed_lower_bound` 是已記錄合資格帳戶的去重數；名冊未知時仍可能包含未識別副帳。DB 開始、coverage gap、未知來源／日期、名冊未核實均使 `distinct_accounts=null`；不能稱完整全群活躍數。
- 當前成員集合和觀測集合交集獨立呈現。只有完整枚舉及觀測契約無上述未知時才提供確定 intersection；否則只有已知交集下限，不能把未找到的帳戶當離群。
- 來源表缺失、不可讀或查詢失敗，整個報表回覆 unavailable，不能製造成 0。成功空查詢可列「已觀測下限 0」，並保留未知及限制。

## 心跳、coverage、session 範圍分開

- Heartbeat 輸出最近成功、全庫累計 failures、最新 run 的開始／成功／failures 及當下 cog availability。Observer run 表沒有 guild 欄位，明示全庫；累計 failures 不叫 observer exception 次數，沒有個別失敗時間就不作歸因。
- Coverage 只合併、裁切該 guild／窗口的已儲存 intervals，以聯集秒數及 complete／gap 呈現。不能用較早的 DB lifetime 作 uptime 分母。
- `baseline_scope` 僅檢查當下 `SquadCards.state['sessions']`：linked／natural、waiting、unknown、ended、AFK、channel unavailable。附 snapshot 時間，沒有掃描全 server 補建 session，沒有歷史 skipped-reason collection。
- 成功空 observer scan 仍可有 heartbeat；有心跳不代表有合資格 session 或到場。範圍只屬已記錄的 SquadCards sessions，不是全群 census。
- 合資格到場仍不等於個人達標、共同遊玩 120 秒或完成遊戲；既有 co-play 及 return-cohort 邏輯沒有改動。

## 私人 UI／權限

- 沿用 fresh REST member／role 授權，只准本 configured guild 的非 Bot Admin／manage_guild 成員；Helper、Tester 或普通會員不因角色名稱獲權。
- 選單生成前／送出前核權。新報表讀取前及每次 aggregate output 送出前 fresh 核權；讀取中撤權就不送出統計。
- 選單按鈕綁定開啟者及 guild；不允許另一使用者或另一 guild 重用。
- 所有新回覆 ephemeral、`AllowedMentions.none()`，不 DM、不 tag、不改角色／XP、不發額外通知。超過訊息限制按靜態行分段，下一段再核權；不附原始 IDs／例外文字。

## 測試及回復

本機環境：hash-locked 依賴，Python **3.14.8**；不是 Python 3.11／容器驗證。針對性測試命令：

```sh
/private/tmp/con9sole-validation-venv/bin/python -m unittest discover -s tests -p 'test_growth_baseline.py' -v
```

目前 17 個新測試通過，涵蓋：完整 HK 日／跨年／邊界、actual timestamp union、visits／跨來源去重、guild／test／channel／Bot 排除、staff 活動不 blanket exclude、名冊未知及確認子集、不完整 membership intersection、缺日期／來源／orphan、心跳與 coverage 分離、缺表／讀取失敗、live WAL 不修改 DB／WAL 及重跑一致、HK／TW／neutral、真實 discord.Member fixture fresh 角色授權、撤權、owner／guild 綁定、每段核權及私人輸出。

同一環境另已通過：

```sh
/private/tmp/con9sole-validation-venv/bin/python -m compileall -q .
/private/tmp/con9sole-validation-venv/bin/python -m unittest discover -s tests -v

git diff --check
```

完整回歸 **1,001 tests passed**；`compileall` 及 diff whitespace check 通過。既有 `observed_returns` 測試保留 D0／D7／D28 maturity、首次觀察非入會日及 coverage unknown 規則。命令 lifecycle 仍維持原命令總數，baseline 只用既有私人選單按鈕。

沒有 migration、新索引、診斷表、歷史回填或新增 persisted config。重跑只有查詢；fixture 證實既有 DB／WAL bytes 不變。回復為 revert 本次 code／test／doc commit，保留所有正式 DB、XP、角色及通知收據；未執行 runtime rollback，也沒有聲稱已建立或驗證正式備份。

## 未驗證及明確 pending

- 未用正式 Bot、Discord GET、真人帳號或正式資料執行本次新入口；本輪只有離線合成 fixture。Admin／Helper／Tester／普通會員真人 UI 及 iPhone Mirroring 未驗證。
- Python 3.11、locked dependency audit、容器 security 及 GitHub CI 由 01／06 在固定整合版本驗證；本機 3.14 成功不替代它們。
- 歷史 Gateway 漏接、未配置路由、未知來源／日期／副帳均維持未知；沒有 collector-loss verdict 或歷史重建。
- 05「invite-join cohort → 加入後七日首次 observed qualifying attendance」**仍 pending，沒有 endpoint**。此 HK calendar baseline 不能替代 rolling join-cohort，不能推論首次遊戲、獨立真人或宣傳因果。
- 待 01 固定完整 base／head／diff／測試證據，再由 06 驗收；通過驗收也不是本輪發布授權。
