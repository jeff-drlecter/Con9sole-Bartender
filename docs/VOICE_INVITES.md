# 小隊房原生語音邀請

此版本是**預設關閉、只可精確範圍試行**的候選程式；未部署，候選真人 UI 驗收尚未完成。使用原有正式 Bot 的單一 process，不建立第二個 Bot、staging 服務、新資料庫、Fly secret 或部署環境參數。沒有全伺服器開放模式。

## 私人試行管理

管理員以 `/squad_invite_trial` 選擇 `configure`、`status` 或 `disable`。三種操作均先以 REST 重新確認管理伺服器／Administrator 權限，只作 ephemeral 回覆，不發公告或 ping。Helper 身份本身不足以管理試行。

啟用操作必須在指定目的**文字頻道內**使用，明確選擇該文字頻道、其所在分類，以及一至兩個使用者自有測試帳號。程式逐一重新取得指定分類／目的頻道及兩位被選帳號，不讀取會員名單；兩個頻道必須屬同一精確 guild/category，既有 SquadCards route 必須已指向同一 destination。名稱含「測試」、提供任意 URL 或選擇其他分類都不能代替授權；亦不修改 route 或 overwrite。

設定只保存於現有 `squad_cards.json` 的 optional `voice_invite_trial`（schema、enabled、guild/category/destination IDs、tester IDs、revision）。缺省、未知格式、缺欄位、錯誤型別、額外 broad 開關一律關閉。Repository 不包含任何 live ID 或啟用設定。每次設定建立新 revision，既有場次不可借新設定繼續舊分享意圖。

只有白名單內、目前位於指定分類小隊房的開房者或 server admin 可以主動分享；管理員亦不可繞過白名單。另一個帳號按原生 Join Voice 仍由 Discord 既有權限控制，程式不額外給權限。新按鈕只對符合已存範圍的 viewer 顯示；舊按鈕、直接 share／authorize／prepare、REST 後及 POST 前都重新核對範圍。顯示按鈕的 cache 檢查不取代 fresh REST audience／權限檢查。

`disable` 先持久保存關閉狀態，再撤銷已知本局邀請並只移除原訊息的邀請 URL，保留原 embed/view、舊語音入口、正常招募卡及通知政策。清理失敗沿60秒退避／5分鐘公開訊息截止保留私人待查；已知邀請持續嘗試撤銷直至成功或到期。設定漂移、移動分類、route 不符、revision 改變及重啟後失效亦會停止舊分享。不為停用補發卡片；同局停用後不重新建立另一個 invite，須由新的場次重新主動要求。已停止分享的邀請撤銷排程不會觸發普通卡片 render；公開訊息待查／退避亦不能被 dirty 或 roster 更新繞過。恢復頻道存取後，在原卡明確操作「招募設定」可於60秒退避後嘗試更新；成功後恢復正常名單／設定更新及既有通知流程，仍不恢復原生邀請。

## 試行中的會員入口

允許的 TempVC 私人房控顯示「📣 招人入隊」。白名單內、現時身處該房的開房者或 server admin 可以使用；保留加入、改名、改人數、刪房及返回吧枱。目的地沿用既有 SquadCards 分類 route；已綁約局則沿用 PlanBook 原訊息，不建立另一個 Plan。

按一次會儲存本局分享意圖，並顯示原有招募設定（遊戲、模式、缺額皆選填）。真人未連續留滿30秒時只儲存意圖／設定，私人回覆等候，不發卡、不建 invite、不提前通知。斷線／重啟仍重設未出卡計時。分享中的真人離房事件會保守重設尚未出卡的30秒計時（即使另有人仍留房），避免慢 REST 查詢掩蓋離房／重入。

達門檻後，Bot 為本局建立唯一、最多1小時的語音邀請（`unique=True`、不設使用次數上限、不自動續期）。邀請 URL 放在同一招募訊息的獨立文字行，保留原 embed 及 view；私人回覆亦提供 URL 及 canonical 訊息連結。重按只更新原訊息或取回同一連結，不另發招募卡。原卡被刪除則提示不可用，不用分享操作補發。沒有點過分享的 session 沿原有卡片流程。

## 權限及通知

每次主動分享，以及建立邀請／定期核對時，以 REST 重新取得 Guild（含角色）、兩位成員（發起者及 Bot）、語音房及目的文字頻道。Gateway 只提供目前在房狀態；斷線期間拒絕分享。雙方需有語音查看、連接、建立邀請及目的頻道查看／發送權限；Bot 另需嵌入連結、讀取歷史。房滿、離房、權限不足及不存在均私人回覆，不修改任何 overwrite。

語音 audience 必須涵蓋文字目的地的可見 audience。程式按完整角色／member overwrite 權限條件檢查充分條件：先證明文字可見者亦可見語音，再證明這些可見者可以連接：每個所需權限要麼對相關 audience 開放，要麼與目的地查看權限條件完全相同。私房的 @everyone 缺少 View 時，Discord 會隱含清除 effective Connect；程式在已證明 View 條件後，使用原始 Connect 位元及完整 deny 檢查，避免錯誤拒絕相同私人 audience。無法證明相容的私人配置保守拒絕，不能用成員 cache 樣本代替證明。活躍邀請最少每60秒重新核對，名單／設定更新亦會核對；失去可分享條件則移除 URL 並撤銷已知邀請。

既有30秒開局門檻、首位玩家一次 tag、遊戲訂閱、Plan 報名／退出及提醒去重均保留。分享及招募設定不派新增 EXP。邀請是 Bot 建立，不讀取、借用或撤銷會員個人推薦碼；既有推薦獎勵已排除 Bot inviter。

## 持久化、競態及失敗

只有單一 Bot instance；沿用 `squad_cards.json` 及既有卡片 journal。所有分享與 sweeper 共用 SquadCards lock；每個 session 的 `voice_invite` 保存 requester、voice、狀態、已知 code、建立者、最遲到期時間及撤銷退避時間。

- 等候 route／global gate 後，在唯一 POST 前才保存 `uncertain`，成功才保存 code。Timeout、取消、5xx、reset、redirect 或結果不明不重試建立；明確4xx拒絕可由本人再次按分享重試。有效429另存 `rate_limited` 及 `retry_after` 截止，只容許到時由本人重按，不在同次請求重送。未知 code 不掃描／猜測／刪除其他邀請；Discord 的 `max_age=3600` 限制從伺服器建立時起算。本地未知結果的清理時間使用「POST開始＋30秒請求上限＋1小時」保守估計，不聲稱知道精確伺服器到期時間；散場後保留於 `voice_invite_uncertain`。
- 卡片發送沿用先持久化 journal。未知發送不重播；已知成功但 session JSON 未保存時採納 journal message ID。未知發送若實際成功但未取得 message ID，不能安全修改該未知訊息；散場仍撤銷已知 invite，保留既有待查紀錄供管理員核對。
- 已出卡 session 保留既有30秒空房寬限；刪房立即走結束流程。撤銷邀請與公開訊息收尾獨立處理：只撤銷本局成功建立、code／Bot inviter／voice ID 全吻合的邀請，再移除可存取原卡的公開 URL／舊加入入口及依原規則整理足跡。
- 撤銷失敗保存 session，每60秒重試，直到成功或已過保守有效期。重啟會繼續；不會因重按或未知結果建立替代 invite。Discord 未回傳可驗證身份時同樣保守保留至到期。
- 訊息收尾另存 `voice_cleanup`：開始前記錄60秒退避；一般失敗最多處理5分鐘，明確403則立即轉待查。邀請已撤銷／到期後可移走 live session，保留 `voice_invite_cleanup_pending` 私人證據（原訊息位置、終止時間、錯誤類型及嘗試次數），不會每5秒撞同一403或重發卡／足跡。這些待查訊息需管理員恢復存取後人工核對；程式不掃描其他訊息或補發。
- 綁約局沿用 PlanView、報名資料及原訊息；終態 Plan 更新亦移除本功能的 URL 行。沒有為展示原生卡而額外發送第二則公開訊息。

## 傳送介面維護

`features/voice_invite_transport.py` 只處理建立邀請 POST，不修改訊息 send、HTTPClient 全域行為或其他端點。固定配合 **discord.py 2.7.1／aiohttp 3.14.5**；沿用 runtime session、認證、proxy、route bucket 及 global gate，禁止 redirect，請求總時限最多30秒。discord.py 的一般 request 會重試部分5xx及連線 reset，因此本端點使用單次網絡請求。POST 不屬於此 aiohttp 版本的自動重試方法。

此 adapter 使用 HTTPClient／Ratelimit 私有介面，版本不符便拒絕建立，不能靜默回退 SDK 的重試路徑。升級依賴前須重新檢視 bucket／global 行為、aiohttp POST retry／redirect 規則及完整 transport 回歸。參考 Discord 官方 [Create Channel Invite](https://github.com/discord/discord-api-docs/blob/main/developers/resources/channel.mdx#create-channel-invite)（獨立 `unique` 邀請，未提供 idempotency 欄位）及 [Rate Limits](https://github.com/discord/discord-api-docs/blob/main/developers/topics/rate-limits.mdx)（route/global 與 retry_after）。

語音／連線 listener 在等待 SquadCards lock 前記錄事件 epoch；每次外部 await 返回及邀請 POST／招募 send 前重新驗證。真人已離房重入而最終 cache 又有人，亦不能沿用舊的連續在場起點。已完成請求的 code／message ID 先寫入 journal，才讓後續 epoch 檢查停止公開或通知步驟；POST 尚未開始的卡片 claim，無論因在場檢查、scope drift 或其他發送前錯誤中止，均標記 rejected；範圍恢復及重啟後可按正常門檻出卡。真正呼叫 send 後結果未知的 claim 仍保持 uncertain，不盲目重送。

## 驗證及受控試行 UI 閘門

離線 synthetic tests：`python -m unittest discover -s tests -p 'test_voice_invite*.py' -v`。涵蓋同時按鈕／30秒 sweeper、未出卡設定、已出卡重按、未知建立／發送與重載、權限拒絕／變更、私房 audience、邀請到期、空房寬限、刪房、撤銷退避、只撤銷本局 Bot code、Plan 原訊息及原房控。另以真實 HTTPClient bucket＋synthetic wire 核實5xx／reset／timeout／cancel／redirect僅一個 POST、429及global gate；慢查詢離房重入／斷線重連、cache預先更新、卡片claim前後競態、403收尾及重啟退避截止亦有回歸。

2026-11-18 主控於限定測試區的真人 UI 基線觀察（既有部署版本＋人手邀請，**不是候選程式 UI 驗收**）：

- 人手純 URL 訊息顯示原生房名、在房成員、時長及綠色 Join Voice；此伺服器當時未見 banner。
- 第二個使用者自有帳號（Helper、非 Owner，並非純一般會員）點 Join Voice 成功進同一測試房。
- 原有 `/vc_new` 重用同一房；改名後原生卡同步房名；原房控改人數成功。
- 兩個測試帳號離房後，既有30秒空房寬限及招募卡轉足跡可見；主控已移除唯一手動測試訊息的邀請 URL，測試房亦由既有空房機制自動刪除。

**尚未驗證**：候選 Bot 的同訊息 `content URL + embed + view` 原生預覽、候選新按鈕的真人流程、純一般會員及手機 UI。Draft PR 不代表已部署。交付次序是「只限測試區受控試行 → 真人驗收 → 另行廣泛開放」；經審查後只可先部署預設關閉的程式，再由管理員在指定測試區精確啟用。候選按鈕及 Bot 同訊息組合需在該試行範圍完成真人驗收；此版本沒有直接廣泛開放開關，日後擴大範圍需另行授權與實作。若 Discord 不顯示原生預覽，保留同一 canonical 卡及私人 URL，不能為美觀無追蹤多發一次。邀請可以透過私人回覆取得，原卡語音入口仍可使用。


試行 scope 回歸另包括缺省關閉、未知 schema、guild/category/destination/user 越界、舊按鈕／直接 handler、fresh REST 與 cache 不同、rate gate 等候途中停用、重啟／route drift／revision、fresh admin 及私人 configure/status/disable、撤銷與去 URL 不補發卡，並繼續跑原有30秒／通知去重及房控測試。
