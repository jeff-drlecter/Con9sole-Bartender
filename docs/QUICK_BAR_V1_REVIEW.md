# Quick Bar v1 — Review 指南

狀態：只供 review；此分支未 merge、未 deploy。

## 用戶會見到甚麼

`/menu` 或單獨 @酒保：

```text
🍸 Con9sole 吧枱
飲杯嘢，定搵人開局？

[🍹 飲一杯] [🥂 請人飲]
[👥 搵人玩] [🎧 小隊 call]
[🍸 更多]
```

`/menu` 私下打開；@mention 回覆一張公開、可重用嘅輕量吧枱。選人、設定面板只畀本人睇；飲品、打氣及組隊結果公開。唔再每次選單上傳酒保圖片。

| 功能 | 第一版流程 |
|---|---|
| 飲一杯 | 一撳即出飲品；新酒款提示；收藏、請人飲、返回吧枱放結果下面。冇連續重抽按鈕。 |
| 請人飲 | 私人 Discord 選人器，揀真人會員就送出；唔使另外發訊息 tag 人。Slash 同按鈕共用對象／cooldown 驗證。 |
| 搵人玩 | 從 `*-專區` Forum／thread，或名稱與遊戲 role 相符嘅 Category 帶入遊戲；揀差 1／2／3 人即公開招募。一般頻道先問遊戲；自訂遊戲／模式及 1–16 人仍可用。 |
| 小隊 call | 用設定預設值（目前 32 人）直接開房，或重用自己已開嘅房；已喺房內則打開控制。私人結果提供加入連結。改名／人數／刪房放第二層並檢查權限。 |
| 更多 | 收藏、小任務、打氣、幫人打氣、探索公海、邀請／社交／幫助；管理入口只向有權限嘅成員顯示，callback 仍重新檢查授權。 |

收藏保留稀有度頁、最近解鎖、統計及排行榜。今次冇加入貨幣、季度養成、預約組隊、個人名片、AI 或未完成嘅佔位按鈕。

## 同步修好嘅流程問題

- 共用操作鎖擋住送酒、打氣、開房嘅並行重複請求；雙擊唔會排隊再做一次。
- 送酒先 acknowledge，再讀資料／fetch member；成功送出後先寫 cooldown、抽酒歷史及事件。事件寫入失敗會 log，並私下通知。
- 公開送酒／打氣／招募會檢查使用者喺頻道／thread 嘅發言權限；限制 mentions，更新名單唔會重新 ping 全隊。
- 選人面板限本人、可取消、到期有重開提示；更新 ephemeral 面板用原本 interaction message。
- 新組隊卡保存到 SQLite，restart／reload 後按 message ID 註冊 view；每張卡有鎖，避免最後一個名額超收。儲存失敗會還原名單；同一召集人每個 server 一個活躍招募。招募六小時後結束，唔會因不停撳而延長。
- VC 用持久化 channel／creator IDs 追蹤，唔再靠房名授權刪房。改名唔會失去追蹤；API 刪除失敗保留紀錄；sweep 唔會重設已開始嘅空房倒數；reload 後唔使等新 ready event 都會重啟清理。
- SQLite `with` 區塊 commit／rollback 後會明確 close connection。
- 舊 Menu custom IDs 保留路由；舊訊息仍可使用現有入口。

## 資料及首次推出前要處理嘅遷移

現有 stats database 新增 `team_cards` 及 `temp_voice_channels` 兩張表；原本飲品／歷史表及 JSON 格式保留。Docker image 排除 runtime SQLite／JSON，繼續包含 `data/` 嘅 Python 內容。

**日後正式推出前，先檢查舊版已存在嘅臨時房。** 如要繼續管理，將經確認嘅 channel IDs 填入 `TEMP_VC_LEGACY_CHANNEL_IDS`，推出後清空遷移清單。預設為空；同名格式唔會自動被採納／刪除。遷移房唔會假設房主，故房主限定改名要先明確補上 owner；管理員控制仍適用。

舊版組隊冇保存資料，所以現存舊卡無法恢復；新建立嘅卡先有 restart recovery。

## 驗證

本地 Python 3.14.8／discord.py 2.7.1：100 個測試通過。包括隔離 subprocess 真實載入全部 17 個 extensions、檢查 registry 路由及 25 個 guild commands、reload Menu／Teams／TempVC。冇 login 或真正 sync 去 Discord。GitHub 分支／PR 另跑 repository 原有 Python 3.11 checks，結果見 PR。

測試覆蓋：發送失敗、bot／自己作對象、開選人器期間 cooldown 改變、雙擊、最後名額同時加入、寫入失敗、組隊恢復、唯讀頻道、VC 重用／刪除失敗／房主恢復／重複遷移／倒數穩定、ready 狀態 reload，以及 SQLite commit／rollback／close。

## 真實 Discord 驗收仍需做

先用獨立測試 application／server：

1. 手機／電腦檢查 Quick Bar、「更多」及管理入口顯示。
2. 賜酒選人、取消、到期；確認結果公開而選人仍私人，只提及預期收酒者。
3. 從遊戲 Forum thread／一般頻道開組隊，加入／退出／修改／結束；restart 後用原卡，確認冇多餘 ping。
4. 預設開房、重複撳、加入、改名／人數、空房清理；已 ready 時 reload，確認普通同名房唔會被刪。
5. 移除 bot 相關權限，檢查錯誤提示及資源冇重複建立。

開發期間冇操作 production Discord、發訊息、真正 slash sync 或 deploy。

## 另行處理嘅審查項目

早前提出嘅 Role Tools 授權政策、Update Publisher 去重、Game Tools 失敗復原／onboarding 整合、告白目的地、依賴鎖版及全面監控，唔屬於今次會員流程第一版；此分支唔代表已修好整份 repository audit。
