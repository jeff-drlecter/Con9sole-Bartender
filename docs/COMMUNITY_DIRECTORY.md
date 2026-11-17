# 公會目錄／公會卡

同一 Discord 伺服器內的長期公會目錄。指令只註冊在 `config.GUILD_ID`；所有回覆皆 ephemeral、禁止 mentions 通知。沒有公開發帖或會員名冊。

- `/community list [page]`：每頁 10 個，列出固定公會代碼、遊戲、招募狀態及可點擊且不 ping 的 PIC（在服狀態請開公會卡確認）。
- `/community show key`：一張公會卡，包含名稱、遊戲、公開簡介、招募狀態及可點開的 Discord 聯絡 PIC。
- 管理員 `/community create key name game pic [notes] [status]` 建立；`edit key` 更新名稱、遊戲、PIC、公開簡介或招募狀態。省略欄位即保留；`clear_notes:true` 清空簡介，不可同時填 notes。
- 管理員 `/community archive key` 封存，從會員目錄移除；`list archived:true` 查看封存資料；`restore key` 使用原代碼還原。還原前確認 PIC 仍在服且非 Bot，否則先 `edit` 交接。

已驗證會員及 Server Admin 可查閱有效公會；只有現有 Server Admin（administrator 或 manage_guild）可管理／查閱封存公會。Helper、Tester、PIC 標示本身不賦予管理權。每次操作重新透過 REST 查伺服器角色及操作人身份；公開資料不是私人／個人備註，勿填私人資訊。一個 PIC 可聯絡多個公會。PIC 只要求目前在服的非 Bot 成員；查閱時已離服或 Discord 查詢失敗會明確標示，保留公會資料，管理員可交接。

代碼為 1–32 個小寫英數、底線或連字號（首字英數），建立後固定；名稱 1–80 字，遊戲 1–80 字，公開簡介最多 700 字。名稱不分英文大小寫，與代碼都須唯一，包含封存項目；同名分隊須加分隊名稱。文字拒絕控制／方向字元並轉義 Markdown／輸入 mentions；PIC 欄位保留可點擊 mention，但不 ping。總上限 500 張（包括封存），最多 50 頁。

儲存於既有 `DATA_DIR/community_directory.json`，使用既有原子 JSON 寫入；單一 Bot 程序內寫入不跨 await。缺檔可建立空目錄；損壞、不完整、重複鍵或不符伺服器／版本的檔案原位保留並拒絕讀寫，須維護人員先備份再處理，不自動重置。沒有資料遷移或啟動時寫入。讀卡／還原在外部等待後比對原資料，避免併發封存或 PIC 交接發出舊卡／還原未驗證聯絡人。

離線驗證：`tests/test_community_directory.py` 使用合成資料測試真實權限函式及 command callbacks、不同公會同 PIC、交接重啟、封存還原、失敗保留、無 ping、輸入限制與翻頁；`tests/test_quick_bar_lifecycle.py` 實際載入／重載 extension 並核對 guild group 六個子命令。無登入 Discord、正式資料或真人 UI 驗證。
