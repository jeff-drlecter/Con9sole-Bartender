# Con9sole Bartender — Codex 協作規則

## 既有規則與授權

- 保留 `docs/OPERATIONS.md`、相關模組文件、`docs/APPROVED_COMMUNITY_POLICIES.md` 及 `.github/workflows/` 的現有規則；讀取時以本輪相關部分為限。歷史「已批准部署／apply」不是新一輪的授權。
- 預設交付為 branch + Draft PR。**未獲本輪額外明確授權，不得合併／push main、部署正式 Bot、改正式 Discord 設定或發布公告**；不得啟動第二個正式 Bot、發測試通知或聯絡成員。
- `main` push 會自動部署；不得為方便修改／繞過保護規則、必要 `validate` 檢查或既有 workflow。
- 不讀取／提交 `.env`、憑證、正式 `/data`、會員名單、私人訊息或 `migration_private/`；測試使用合成 fixture。若工作確需正式資料，先由主控釐清授權及最小範圍。
- 對使用者以香港繁體中文回覆。更深層 `AGENTS.md`（如日後新增）仍適用其工作目錄。

## 01 主控：按需求自動派工

主對話就是 01；不另外啟動 01。此檔明確要求主控在適合的需求上使用下列專屬 subagents，使用者毋須逐個 chat 指示。

| Agent name | 選用情況 | 模型／推理 |
| --- | --- | --- |
| `member_experience`（02） | 會員入口、身份組、權限、通知 | `gpt-6.2-astra` / `high` |
| `matchmaking`（03） | 約局、預約、招募卡、語音房 | `gpt-6.2-astra` / `high` |
| `growth`（04） | Ranking、EXP、獎勵、統計 | `gpt-6.2-sol` / `high` |
| `content`（05） | 文案、公告草稿、新聞及營運內容 | `gpt-6.2-sol` / `low` |
| `verification`（06） | 實作完成後的 PR／整合／安全／部署風險驗收 | `gpt-6.2-astra` / `xhigh` |

1. 先核對遠端最新 `main` SHA、工作樹狀態及適用規則；不覆蓋使用者未提交改動。先用檔名／符號搜尋定位，不把全庫或歷史聊天灌入上下文。
2. 判斷工作範圍、依賴、驗收條件及每個檔案唯一負責人。只啟動真正需要的角色；簡單問答／單字修正可由 01 完成。不為湊數啟動所有角色。配置變更由 01 實作、06 驗收。
3. 任一時間最多 **3 個 subagents**，包括驗收及診斷代理。剩餘工作排隊；釋放完成的代理後才啟動下一個。所有子代理不得再派工；控制權留在 01。
4. 優先按 TOML 的 `name` 使用客戶端的 custom-agent 選擇器。必須檢查工具回傳／執行 metadata 的實際 model 及 effort；不可把 prompt 或 agent 自述當證據。
5. 若客戶端只提供 `model`、`reasoning_effort` 的 spawn 介面（沒有 custom-agent 選擇器），讀取所需 TOML，以 **`fork_turns="none"`** 明確傳入相同 model/effort，並將該檔 `developer_instructions` 與最小派工合約交給 child。不得用 `fork_turns="all"` 代替，因為它可能繼承主控模型／歷史。這是有明確參數的相容模式，不可聲稱是 TOML 自動載入。
6. 若無法選指定模型／effort、無法取得可核實的 metadata、或本地配置未被載入，明確標記「未驗證／不支援」。不得靜默換模型。最接近替代方案：支援 explicit spawn 的客戶端；否則 01 串行處理並明示限制。更換指定模型須先取得使用者同意。

## 最小派工合約及檔案隔離

每次派工提供：任務／角色、實際 model/effort、base SHA、絕對 worktree 路徑及 branch、允許讀取／修改的精確檔案、必要直接依賴、輸入／輸出介面、完成條件、測試及禁止的外部動作。不要傳整段主對話。

- 每個可寫的跨模組子任務使用獨立 branch **及 worktree**，例如 `codex/<task>/02-member-experience`；worktree 放在 checkout 以外的同級專用目錄。單純切換 branch 不能隔離同一工作目錄。
- 先確認指派路徑存在、`git -C <path> rev-parse HEAD` 是指定基線及 branch 正確，才開始編輯。沒有獨立 checkout 能力時，寫入必須串行；不可假裝已隔離。
- 同一檔案只有一名寫入者。`bot.py`、`config.py`、`utils.py`、共用 menu／storage／UI、requirements、workflow 及 `.codex` 由 01 指派唯一責任人；其他人只回報建議 patch／介面需求。
- 候選模組路徑只用於導航，不等於授權整組讀取。超出合約的讀寫／依賴，先回報 01；01 可在已授權需求內縮小或擴充合約，不必再問使用者。
- 分支交付 commit 及 Draft PR（如已有主控整合 PR，可先交 commit 再由 01 統一建 Draft PR）；跨模組成果由 01 在獨立整合 branch/worktree 逐一整合。不得對 main 作整合，不作 force push。
- 回報摘要：完成行為、SHA／檔案、測試結果、依賴及未驗證項目。避免傳送大量原始 logs 或資料。

## 06 驗收閘門及 GitHub 流程

1. 所有相關實作完成、提交並停止寫入後，01 固定整合 SHA。列出需求、base/head SHA、完整 diff、各工作結果及測試，標記 `ready-for-verification`，才啟動 06。
2. 06 在該 SHA 做審查及離線驗證；不與仍在寫入相關成果的 agent 並行。審查期間新修改會使舊結論失效，須重新交接新 SHA。
3. 跑變更所需的針對性測試；保留現有 Python 3.11 `validate`：`python -m compileall -q .`、`python -m unittest discover -s tests -v`、locked dependency audit 及 container security。不要用本機不同 Python 版本冒充 Python 3.11／容器驗證；可由既有 GitHub Actions 提供證據。
4. Codex 配置另外跑 `python3 scripts/validate_codex_agents.py`；模型目錄及 TOML 靜態成功不等於模型已執行，依 `docs/CODEX_MULTI_AGENT.md` 驗證。
5. 01 彙總 06 問題、修復及 CI 結果後交付 Draft PR。若有測試／模型／真人 UI 未驗證，明確列出。不得將驗收通過解讀為發布授權。
