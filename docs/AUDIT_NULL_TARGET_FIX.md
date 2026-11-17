# Audit null target 修復（候選，未部署）

來源：#195 的離線 SDK 重現；執行／清理紀錄：#197。

`discord.py==2.7.1` 在 channel-target audit entry 的 `target_id` 為 null／缺失時，
可能於 `entry.target` 解析內建立 `Object(id=None)` 而拋出 TypeError；外層 getattr 的 default 無法處理。

listener 現在只對已知 `_target_id is None` 的 TypeError 保留「對象未提供」，繼續輸出已知操作者、
動作、原因、審核編號及欄位變更；不推測目標、不補造頻道 ID。不吞掉非 null target 的轉換錯誤。
日誌路由、權限、佇列去重、mentions 限制與既有資料格式不變。

合成 action 11 僅用於重現，不代表正式失敗事件的 action 已被確認。沒有證據把這個日誌錯誤等同出席漏收。
測試使用真正 SDK AuditLogEntry，涵蓋 null／缺失 target、欄位保留及非 null 錯誤不被吞掉。
全套及 CI 結果見修復 PR；不以合成測試冒充真人驗收或正式部署。

不需要 migration；如將來獲授權發布後要回復，只回復此 listener 程式，保留全部現行日誌／EXP／通知收據。
