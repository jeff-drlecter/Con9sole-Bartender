# 頻道尾部 emoji

Jeff 在頻道建議及各遊戲「吹水組隊 💬」討論後授權 apply。只改既有文字／公告及已列明論壇的名稱，不改分類、排序、權限、成員、訊息、通知對象或內容。

- 各遊戲 `…-吹水組隊` 保留遊戲前綴，在尾部加一個 💬；已是正確名稱便不寫入。語音房、模板與已辨識存檔／隱藏分類排除。
- 固定頻道依對話建議表移除兩端裝飾，保留文字並加一個指定用途 emoji；見 `scripts/apply_channel_emojis.py::PROPOSED`。既有設定 ID 優先核對；其他須唯一匹配。缺失、同名歧義、ID 不符或超長均停止該項，不猜測、不建立新頻道。
- `chats` 與 `all` 是明確獨立維護範圍；apply 必須與該次 audit 的 scope 和 digest 完全相符，不因有程式能力就代表兩個範圍均已套用。

相容修正：約局入口及分類排序接受原名與 💬 尾綴；GUIDE 接受舊 ✅／新 🧭；測試區體驗交流接受 💬；rules／game-tag 的邀請來源標籤保留舊新映射。未改遊戲模板或自動建立頻道規則，未來模板複製仍接受原名稱。

手動 `Channel emoji names` workflow：main-only、production，部署後先 audit，檢閱去識別候選摘要，再於 30 分鐘內套用精確 digest。原頻道及覆寫快照留 `/data/channel_emoji_suffixes/`（0700／0600）。角色與分類先 fresh 比對，逐頻道比較原值；只 PATCH name，寫前 journal、寫後 GET 確認其他欄位不變。未知寫入不重播，需 status／重新 audit。沒有任意 API 或 shell 輸入。

若需回復，從私有快照取原 name，先確認現在仍為這次 after，再只還原 name；不得整批覆蓋權限或重建頻道。持久按鈕、排程、卡片、訂閱及訊息連結仍按原 channel ID 運作。main 合併前完整 CI，部署仍經現有資料備份及健康檢查。最終 commit、CI、部署與 audit/apply 證據更新於本次 PR body 及本地交接紀錄。

正式 audit 顯示「站務-意見箱」與 `config.SUPPORT_CHANNEL_ID` 不同；兩者不能當同一入口。意見箱依唯一原名確認，保留設定中的求助入口名稱及所有權限。
