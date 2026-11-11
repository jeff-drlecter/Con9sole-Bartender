"""Copy-only changes for the known community onboarding prompts."""
from copy import deepcopy

LANGUAGE_TITLE = "你希望 Bot 使用哪種用語？（可隨時更改）"
LEGACY_LANGUAGE_TITLE = "Bot 想用邊種語境？／希望 Bot 使用哪種用語？"
TITLES = {
    "1363098911048339468": "你使用哪些遊戲平台？（必選，可複選）",
    "1279023252903301224": "你想加入哪些遊戲討論區？（可複選，也可略過）",
    "1426676369567387821": "你想加入綜合聊天區嗎？（可隨時更改）",
    "1426676369567387826": "你想顯示遊戲新聞頻道嗎？（可隨時更改）",
    "1424888824567173172": "你想如何參與直播區？（可隨時更改）",
    "1564483098668695614": "你想參與新功能測試嗎？（選填，可隨時取消）",
}
# Current/new titles map to the same text, so subsequent setup is a no-op.
OPTIONS = {
    "1426676369567387821": [
        (("加入公海", "加入綜合聊天區"), "加入綜合聊天區", "顯示綜合聊天及話題討論區，可隨時更改。"),
        (("暫時唔加入", "暫時不加入"), "暫時不加入", "隱藏綜合聊天區；日後可在「頻道與身分組」更改。"),
    ],
    "1426676369567387826": [
        (("顯示新聞區",), "顯示新聞區", "顯示遊戲新聞頻道，可隨時更改。"),
        (("暫時隱藏",), "暫時隱藏", "隱藏遊戲新聞頻道；日後可在「頻道與身分組」更改。"),
    ],
    "1424888824567173172": [
        (("開台兼睇台", "直播及觀看直播"), "直播及觀看直播", "顯示直播區，加入直播主及觀眾身份組。"),
        (("只開台", "只進行直播"), "只進行直播", "顯示直播區，加入直播主身份組。"),
        (("只睇台", "只觀看直播"), "只觀看直播", "顯示直播區，加入觀眾身份組。"),
        (("暫不參與",), "暫不參與", "暫時不加入直播區；日後可隨時更改。"),
    ],
    "1564483098668695614": [
        (("參與測試",), "參與測試", "加入測試成員身份組，試用新功能及回報問題；可隨時取消。"),
    ],
}
LANGUAGE_OPTIONS = [
    (("香港語境",), "香港語境", "廣東話及香港常用詞；只代表用語偏好。"),
    (("台灣語境",), "台灣語境", "台灣繁體中文常用詞；只代表用語偏好。"),
]


def neutralize_prompts(prompts):
    result = deepcopy(prompts)
    for prompt in result:
        pid = str(prompt["id"])
        options = OPTIONS.get(pid, [])
        if prompt["title"] in (LEGACY_LANGUAGE_TITLE, LANGUAGE_TITLE):
            prompt["title"] = LANGUAGE_TITLE
            options = LANGUAGE_OPTIONS
        elif pid in TITLES:
            prompt["title"] = TITLES[pid]
        for option in prompt["options"]:
            for aliases, title, description in options:
                if option["title"] in aliases:
                    option["title"] = title
                    option["description"] = description
                    break
    return result
