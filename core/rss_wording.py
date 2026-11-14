"""RSS interface copy; source titles and member keywords are never translated."""
from features.language_preferences import language

COPY = {
    'saved': ('✅ 已儲存。按「查看我的情報」查看結果。', '✅ 已儲存。按「查看我的情報」睇效果。'),
    'preferences': ('選擇後會自動儲存；關鍵字可留空，只影響你的私人結果。', '揀完會自動儲存；關鍵字可留空，只影響你嘅私人結果。'),
    'include': ('想看的字（任一符合；逗號分隔）', '想睇嘅字（任一符合；逗號分隔）'),
    'exclude': ('不想看的字（排除優先；逗號分隔）', '唔想睇嘅字（排除優先；逗號分隔）'),
    'own': ('請開啟自己的「調整偏好」。', '請開啟自己嘅「調整偏好」。'),
    'empty': ('目前沒有符合偏好的內容，可調整篩選。', '目前冇符合偏好嘅內容，可以調整篩選。'),
    'fixture': ('虛構資料，只供測試，不是真實優惠。', '虛構資料，只供測試，唔係真實優惠。'),
    'scope': ('最近 24 小時｜按平台文字線索分類，可能漏收。有效優惠另外列出；只標示已核實優惠。', '最近 24 小時｜按平台文字線索分類，可能漏收。有效優惠另外列出；只標示已核實優惠。'),
    'featured': ('已按你儲存的偏好篩選。', '已按你儲存嘅偏好篩選。'),
    'entry': ('🎮 遊戲情報・公開試用\n查看情報或調整偏好；結果只對你顯示，設定會保留。\n來源：PS、Xbox、4Gamers；熱門為 Steam 榜單。', '🎮 遊戲情報・公開試用\n查看情報或調整偏好；結果只畀你睇，設定會保留。\n來源：PS、Xbox、4Gamers；熱門係 Steam 榜單。'),
    'unavailable': ('請在本社群內你有權查看的頻道使用；情報功能可能暫未開放。', '請喺本社群內你有權睇嘅頻道使用；情報功能可能暫未開放。'),
}

def rss_text(member, key):
    neutral, hk = COPY[key]
    return hk if language(member) == 'hk' else neutral
