# Codex 專屬協作配置

## 使用

在 Codex 開啟包含此配置的 Repository checkout，確認信任此專案，開新主對話後直接輸入需求，例如：

> 改善約局候補通知，保留退出設定，完成測試後開 Draft PR。

01 會按 `AGENTS.md` 選擇 02／03 等所需角色，最多同時三個；實作完成後才交 06 驗收。只需一個主對話。配置尚在 Draft PR 時，要開啟 PR 分支才有新設定；main 不會提前取得它。

## 配置及執行邊界

- `.codex/agents/*.toml` 是官方 standalone custom-agent 格式，`name` 是選擇名稱。01 是主對話，不另設 agent 檔。
- 各檔同時設定 `model`、`model_reasoning_effort`；06 的 Extra High 對應 `xhigh`。
- `.codex/config.toml` 只開啟 agents 並把 spawned threads 上限設為 3（不含主控），不改主控模型、權限、provider 或使用者設定。
- 主控按需求決定是否派工；不是啟動時自動運行全部 agent。細小工作可以零 subagents。
- 寫入任務在獨立 branch + worktree，整合由 01 負責。06 只接收已完成並固定 SHA 的成果；修正後必須重驗。
- 範圍限制、禁止發布及 06 不改檔是協作規則，**不是獨立 OS 安全沙箱**。子代理繼承父對話的權限。GitHub 分支保護及平台權限仍須保留。
- 已存在的舊對話不保證熱載入新設定；未信任專案會略過 project `.codex`。不要修改全域 trust／關閉沙箱來掩蓋問題。

## 模型驗證：不可只看 prompt

分開記錄三種證據：

1. **靜態配置**：`python3 scripts/validate_codex_agents.py` 檢查 TOML、必要欄位、模型／effort 及併發上限；GitHub 既有 `validate` job 同樣執行它。
2. **客戶端支援**：`codex --version`；支援此命令的客戶端可將 `codex debug models --bundled` 輸出至臨時 JSON，再執行 `python3 scripts/validate_codex_agents.py --model-catalog <JSON>`。bundled catalog 只證明客戶端認得該組合，不保證帳戶 entitlement 或服務端實際路由。
3. **實際執行**：在受信任 checkout 開新對話，檢查 custom-agent 名稱可選、effective agents cap 為 3；對每個角色作一次最小只讀 smoke check（分批，最多三個）。記錄平台回傳的 agent/thread ID、model、effort 及成功完成狀態。可用平台的 thread metadata／session `turn_context` 或受支援的診斷介面核對；不要把 assistant 自述、檔案內容或成功建立 thread 當模型證據。

初次配置／升級時才需要測齊五個角色；一般工作只核對本輪真正啟動的角色。驗收時記錄實際證據，若介面不公開 model/effort，清楚標記「runtime 未獨立驗證」，不可聲稱五個模型已確認生效。

### 相容模式

本輪主對話的 `collaboration.spawn_agent` 有 `model`、`reasoning_effort`、`fork_turns`，沒有 custom-agent name 選擇器。因此可由 01 讀取所選 TOML，使用明確 model/effort + `fork_turns="none"`，再傳角色指令與最小任務合約；這由工具參數設定模型，不靠 prompt 切換。

這個介面不代表 `.codex/agents` 自動載入，也不能證明 project 的 cap 在目前已開啟對話生效。此時由 01 額外維持最多三個子代理、禁止子代理再派工。若不能取得 metadata，仍保留 runtime 未驗證標記。

若客戶端既不支援 custom agents，也沒有明確 model/effort 的 spawn 參數，最接近替代是使用支援的 Codex 客戶端，或暫由 01 串行處理；不得靜默把 Astra 換成 Sol、忽略 effort 或宣稱已啟用相同配置。更換模型須另獲使用者同意。

## 本輪基線與證據

- 2026-11-17（Asia/Hong_Kong）核對遠端 main：`9565192ac5d9027b1468b51efc7108a8f3c57388`。
- 該基線沒有 `AGENTS.md`、`.codex/` 或 `.agents/`；已閱讀 Operations、已批准社群政策及 CI／部署流程。未覆蓋既有 Codex 配置。
- main 受保護，必要 status check 是 `validate`；main push 會觸發 Fly Deploy。此配置只交 Draft PR，不合併／部署／改正式 Discord／發公告。
- 本機 CLI：`0.169.0-alpha.11.1`。bundled catalog 包含 `gpt-6-astra` 的 high/xhigh 及 `gpt-6.1-sol` 的 high/low。`--strict-config ... app-server --print-startup-config` 可成功解析。
- 本機 app-server `config/read` 找到本專案的 agents layer，但以「專案未信任」停用；effective agents 為空。因此本輪沒有聲稱本地 TOML 自動載入或配置的併發上限已在該 CLI 啟用。未修改使用者全域信任設定。使用者須在實際使用的 checkout 完成正常專案信任，重新開對話後核對。
- 02–05 已以本輪支援的 explicit spawn 介面、指定模型／effort、`fork_turns="none"` 分批完成最小只讀檢查；不是僅在 prompt 宣稱換模型。但工具回傳不公開 resolved model/effort，故仍不能當作獨立 runtime metadata 證據。06 於成果固定後作獨立驗收，同樣明示此限制。
- 執行測試及限制的最終結果見本 PR body；靜態成功不等於所有 runtime metadata 已核實。

## 官方依據（2026-11-17 核對）

- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)：standalone TOML、模型及 effort、按專案指令派工、併發上限與父權限繼承。
- [Config basics](https://learn.chatgpt.com/docs/config-file/config-basic)：trusted project、配置優先級。
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)：客戶端與託管環境配置範圍。
