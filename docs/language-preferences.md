# 香港／台灣語境偏好

- `/language` 或 `/menu → 更多玩法 → 資訊與設定 → 語境設定`。
- 香港預設。兩個零權限角色：`語境偏好｜香港`、`語境偏好｜台灣`，只代表用語偏好；不推測位置、國籍或 Discord 客戶端語言。
- 涵蓋主選單、分類選單、使用說明、自選頻道入口、會員卡導覽、訂閱確認、語音建立／控制面板及通用錯誤提示。私人回覆使用點擊者的偏好；公開招募／足跡卡及開局通知使用共通繁體中文。部分舊功能及深入管理工具尚未全面翻譯，詳見 Stage 3 紀錄。
- 固定字典，不呼叫 AI；切換不計 XP，不改經驗冷卻。
- 舊訊息不重寫；切換成功附上新選單。每次點選重新檢查角色零權限、沒有頻道 overwrite、Bot 排序可管理，使用個別 add/remove role API，保留其他身份組。
- 原生 onboarding 與日常選單使用相同角色作實際偏好來源。Bot 改角色不會改寫 Discord 顯示的歷史問卷答案；下次原生問卷重新選擇會按 Discord 原生角色更新生效。若兩角色同時存在，顯示香港預設；日常選單可修正為單一選擇。

## 管理員設定

`/language_onboarding_setup` 只限管理伺服器／Administrator，重新檢查實際成員權限。會建立缺少的零權限角色、新增可略過的單選入服題目；重複或有權限的同名角色中止。

Discord 入服前問題目前已滿四條，僅將已知的新聞區題目 `1426676369567387826` 改為入服後，不改原題目／答案 ID、角色、頻道 mappings 或預設頻道。其餘四題配置不符時中止。PATCH 前重新讀取並比較，原始 prompts 備份到持久資料目錄 `language-onboarding-before-*.json`，讀回確認，結果不明不自動重試。

discord.py 2.7.1 的 `Guild.edit_onboarding` 會重新編 prompt ID，且 option serializer 遺漏 option ID，因此此處僅用其 HTTP transport，明確傳入完整原有 ID。測試使用實際 discord.py prompt/option 物件，避免 mock 掩蓋型別差異。

## Onboarding 共用文字

Onboarding 在選擇語境前統一使用中性繁體中文。指定六個既有問題及語境問題，清除「咩、邊啲、唔、睇、開台」等地域口語；公海入口說明同步引用「綜合聊天區」。只改已知問題標題與已知選項的標題／說明，保留 IDs、emoji、roles、channels、required、single_select 及排序。重跑 `/language_onboarding_setup` 可更新現有題目文字，不重建語境問題。未知問題及遊戲名稱保持原樣。
