# 已批准改善：參與觀測、通知 EXP、正式入口與必要權限

2026-11-15，Asia/Hong_Kong。Jeff 已批准第二輪五項建議，要求依次處理、權限與問題回報先核現況、測試後部署、不發公告。本文件接續 `COMMUNITY_ROUND2.md`，該文件內「未批准／未啟用」均是 PR #173 當時的歷史狀態。

## 基線與保留成果

基線 main `36ec2450c05a65a4276d564f8183dca52e5e59c2`，PR #173；部署 [43671748200](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43671748200) 成功，834 tests。Part 1 PR #172 的 head `1e39801` 已包含於 #173，原 Draft 已以整合完成關閉。保留 Helper 共用摘要／逐次來源核權／私人細節／Tester 虛構示範／新人三路線及全部舊按鈕、訂閱、通知收據。

隔離分支 `codex/approved-community-policies`。main push 仍會自動部署；先完成 PR CI 再合併。未修改其他 Dependabot PR 或舊工作目錄。

## 程式行為

- **共同參與**：同一 session、同一房間、同一對非 Bot 真人累積 120 秒有效觀測區段；不是報名、滿員、完成遊戲或語音 EXP。5 秒抽樣及既有 Gateway 事件；相鄰樣本最多 10 秒。任一人短斷線最多 30 秒可暫停延續，缺席區段及重入首段不計；另一人須仍在房內。跨房、兩人都離開、超過寬限、樣本缺漏、時鐘倒退、Gateway 斷線、Bot 重啟或讀取錯誤都清除未完成時間。抽樣間未觀察到的極短進出仍可能漏接。
- 只有已確認達標存進 `outcome_coplay`，以 `(guild,session)` 去重；已達標在重啟後保留。`coplay_since` 是新觀測起點，無歷史回填。管理員私人報表分約局與自然語音；同一約局多個場次只算一局。沿用測試排除及香港日期邊界，其餘局標示未知／尚未觀察達標。未納入 SquadCards 的語音房仍不涵蓋。
- **通知偏好 EXP**：按鈕不再 dispatch `interest:`；事件 listener 及 Ledger 亦拒絕舊／排隊中的偏好事件。新增、取消、once/always 切換都不計。其他活動、語音、每日任務、每週榜、邀請、稱號與等級不改；沒有追扣歷史 EXP，也沒有實際刷分的證據。原有通知同意、退出、撤回、一次性與長期分離、去重保持。
- 管理規則及個人會員卡加上「調整通知偏好不計 EXP」。共用文字中性繁中，沿用原個人語言入口與持久偏好。

## 正式設定：先核現況，再最小修改

`Approved community maintenance` 是手動 workflow，不隨啟動自動修改 Discord。僅 main／production 可執行；使用部署機既有 Bot 身份，不抽出憑證，不開第二個 Bot。

1. 新聞分類僅 `name`：`即時情報站` → `遊戲情報站`，保留裝飾、排序、子頻道與權限。
2. 新聞固定卡只依正式 panels DB 的 message ID，核對 Bot 作者與原 custom IDs，原位更新摘要時段／每類 8 篇／篩選與手機推播的區別，保留原按鈕 IDs。
3. GUIDE／Welcome／Tester 示例只改唯一可辨識的自有固定卡；Welcome 限置頂且無個人 mentions。查最近 100 則及前 50 個 pins；pins 不完整或無唯一目標便不修改。缺卡不補發、不修改歷史個人 Welcome。Tester 保留虛構示例，移除正式資料入口。
4. 正式 Dashboard 僅移除唯一 `🧪 Tester` channel overwrite 的 View＋History allow；deny 及其他位元原封保留。先計算 Tester／Verified+Tester／Helper+Tester 前提；若 Helper 會失去可見性，該項停止。這是權限模型，不是實際登入帳號驗收。
5. 問題回報須為唯一名稱匹配；若 topic 明示成人用途則停止該項。確認一般求助用途後只改 `nsfw=false`。SUPPORT 另外檢查 Verified 無遊戲身份：必要時只增加 View／History／Send 並移除這三個 deny，其他位元不變，不開放未驗證新人。若仍有年齡門檻，先解除後重審，不能盲目合併權限修改。

每次 audit 私下保存快照和候選動作（`/data/approved_community_20261115/`，目錄 0700、檔案 0600），公開 workflow log 只有去識別的操作結果及布林檢查。閱讀 audit 後以精確 SHA256 digest 在 30 分鐘內 apply；先 fresh 比對角色及目標原值，每次寫入前持久記錄 uncertain，成功後讀回並驗證未改無關欄位。漂移則阻擋該項；模糊寫入不自動重試，以 status 查 journal，再重新 audit。禁止 POST、DELETE、新訊息、tag、角色指派、整批覆寫及分類同步。

訊息更新遵循 Discord [Edit Message / Get Channel Pins](https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx)，明確傳空 allowed_mentions；頻道與 overwrite 使用 [Channel API](https://github.com/discord/discord-api-docs/blob/main/developers/resources/channel.mdx)。原訊息／覆寫快照不提交 GitHub。

## 部署、回復與驗收

部署前仍使用現有 SQLite online backup／JSON 快照及還原檢查；不是跨 store 全域交易。單機更新可能短暫斷線；未完成共同參與計時重置，已確認里程碑及所有既有資料保留。部署後核對 image、machine、新聞／Helper／直播 verifier，以及 outcome heartbeat／新共同參與表。

程式回復以 #173 為保留 Part 1 的安全基線，但不要直接恢復舊通知偏好派分；優先針對故障模組 revert／fix。新增表可由舊碼忽略，不刪資料、不恢復過時 XP 或通知收據。Discord 回復須從私有快照逐項比對「目前仍等於本次 after」才恢復該單一欄位／overwrite／自有卡；不要整批覆蓋快照或重開 Tester 的已知過廣可見性。未提供自動全量 rollback。

CI 必須涵蓋 Python 3.11 全套、pip-audit、容器私檔排除及非 root。新增行為測試覆蓋同對／重入／跨房／缺樣／斷線／重啟／重複里程碑、通知 EXP 拒絕但訂閱保存、正式修改漂移／作者／唯一性／最小位元／讀回／先寫 journal。原測試持續涵蓋提醒、語言、私人權限、新聞、直播與 EXP。

目前沒有可用的真人 Discord UI session；普通成員、Helper、Tester 的 live click 驗收不能由管理員或 REST 權限模型冒充。**iPhone 實機驗收：按 Jeff 指示，本輪略過。** 不發公告、Tester 通知、公開測試訊息或聯絡成員。

下一個完整觀察週：2026-11-16 00:00 至 11-23 00:00 香港時間（若部署晚於週開始則順延）。查看同批到期約局的開局／取消／未知、共同參與達標、自然語音分列、觀測起點／漏接、退出撤回與去重、三條新人路線阻力。新門檻沒有歷史可比基線；私人樣本數尚未核實，不能聲稱提升或設定成功率目標。小規模真實約局仍只保留上輪方案，不代約日期或聯絡主持。

## 發布記錄

待本 PR CI、部署與正式 audit/apply 完成後，更新 PR body 及本地 release evidence，填入精確 SHA／run／image／backup／實際修改與未驗證項目；提交前不預稱已部署或已改正式權限。
