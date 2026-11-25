"""Hand-reviewed topology of the 25 Nov Pitch Notes, with independently authored paired prose."""
from urllib.parse import quote

from core.fc27_layout import Block
from core.fc27_updates import NEWS

PITCH = NEWS + "update-v1-3-pitch-notes"
# Approximate English paragraph lengths from the published reading view. No EA body text.
# Entries are (stable key, independent English/Chinese topic labels, paragraph lengths).
OUTLINE = (
    (("gameplay", "Gameplay", "球場玩法", (300,)), (
        ("dribbling", "Control on the ball", "持球控制", (247, 140)),
        ("near-post", "Finishing at the near post", "近柱射門", (355, 284)),
        ("physicality", "Strength in contact", "身體對抗", (399,)),
        ("shoulder", "Shoulder contact", "肩部碰撞", (327,)),
        ("flick", "Flicks while dribbling", "挑球盤帶", (320,)),
        ("fouls", "Decisions on fouls", "犯規判定", (226, 215)),
        ("tackling", "Automatic challenges", "自動搶截", (354,)),
        ("loose-ball", "Receiving loose balls", "控制自由球", (282,)),
        ("reach", "Interception reach", "攔截範圍", (236,)),
        ("recovery", "Control after an interception", "攔截後的控球", (328,)),
        ("midfield", "Defensive midfield positions", "防守中場站位", (118,)),
        ("clipping", "Ball and boot contact", "球與球鞋的接觸", (136,)),
        ("fullbacks", "Fullback positioning outlook", "邊後衛站位展望", (246,)),
    )),
    (("grounds", "The Grounds", "The Grounds", (148,)), (
        ("matchmaking", "Matching players", "玩家配對", (270,)),
        ("amps", "Amps in small teams", "小隊賽中的 Amps", (275,)),
        ("facilities", "Clubs facilities", "Clubs 設施", (340,)),
    )),
    (("career", "Manager and player careers", "領隊與球員生涯", (175,)), (
        ("general", "Season administration", "賽季管理", (210, 160, 182)),
        ("transfers", "Deals, loans and negotiations", "轉會、租借與合約", (278, 154, 200, 177, 188)),
        ("management", "Squad management", "球隊管理", (128,)),
    )),
    (("tribute", "Remembering John Motson", "紀念 John Motson", (167, 430, 25)), ()),
    (("feedback", "Where to give feedback", "提供意見", (290, 250)), ()),
)

# Only original destinations for text references. Viewing the preview never opens them.
NOV = NEWS + "fc27-november-gameplay-developer-notes"
QNA = "https://discord.com/channels/1164979454557290546/1570826004010766447"
PREVIOUS = NEWS + "update-v1-2-pitch-notes"
REFERENCES = {
    ("opening", 2): (("Previous notes", "上期筆記", PREVIOUS),),
    ("opening", 3): (("Developer notes", "開發筆記", NOV), ("Q&A", "問答", QNA),
                     ("Broadcast", "節目", "https://www.twitch.tv/videos/2925022681")),
    ("opening", 4): (("FUT notes", "FUT 筆記", NOV), ("Q&A", "問答", QNA)),
    ("gameplay", 1): (("October notes", "十月筆記", NEWS + "fc27-october-gameplay-developer-notes"),
                      ("Q&A", "問答", "https://discord.com/channels/1164979454557290546/1565752402995322970")),
    ("fullbacks", 1): (("Earlier article", "上期文章", PREVIOUS),),
    ("tribute", 3): (("Tribute", "紀念專文", NEWS + "fc-27-john-motson-tribute"),),
    ("feedback", 1): (("Broadcast", "節目", "https://www.twitch.tv/easportsfc"),
                      ("Feedback portal", "意見平台", "https://go.ea.com/fc27_pfp")),
    ("feedback", 2): (("X", "X", "https://x.com/EASFCDirect"),
                      ("WhatsApp", "WhatsApp", "https://whatsapp.com/channel/0029VaypA13GehEPKXQgyM46"),
                      ("Discord", "Discord", "https://discord.com/invite/easportsfc")),
}

# The official article is the media destination. These fragments locate the
# surrounding text without guessing a video URL or opening the underlying asset.
FIGURES = {
    "dribbling": ("mid-to-high 60", "Control drill", "控球演練", 105),
    "near-post": ("stronger starting angles", "Near-post drill", "近柱演練", 0),
    "physicality": ("physical strength", "Contact drill", "對抗演練", 0),
    "reach": ("Interceptions value of 50", "Interception drill", "攔截演練", 62),
}

# Paired, original sentences about a fictional training session. The length
# targets exercise real pagination without distributing an EA translation.
SENTENCES = (
    ("The volunteer placed two blue cones beside the empty practice goal.", "志願者在練習球門旁放了兩個藍色標誌筒。"),
    ("One player watched from the touchline and sketched the route in a notebook.", "一名球員在邊線觀察，把路線畫在筆記簿上。"),
    ("A second group waited behind the white line until the coach gave the signal.", "另一組在白線後等候，直至教練示意開始。"),
    ("The recorder marked the starting position before anyone moved the ball.", "紀錄員在開球前標出了起點。"),
    ("Both partners changed places and repeated the exercise in the opposite direction.", "兩名拍檔交換位置，朝相反方向再練習一次。"),
    ("At the break the group compared the first sketch with the final arrangement.", "休息時，大家把最初的草圖跟最後的排列作了比較。"),
    ("The camera stayed on the tripod so that the sideline remained in view.", "攝影機一直放在腳架上，讓邊線保持在畫面內。"),
    ("The group collected the cones and filed the sheet with the other practice notes.", "各人收回標誌筒，把紀錄和其他練習筆記放在一起。"),
)
SHORT = (("A practice partner stayed by the touchline to watch.", "一位拍檔留在邊線觀察。"),
         ("Two volunteers checked the sketch.", "兩名志願者核對了草圖。"),
         ("A flag marked the spot.", "現場以旗子標示位置。"), ("They took turns.", "他們輪流上場。"),
         ("All set.", "準備就緒。"))


def sample_text(number, target):
    english, chinese = f"Sheet {number}.", f"演練紀錄 {number}。"
    cursor = number
    while True:
        en, zh = SENTENCES[cursor % len(SENTENCES)]
        if len(english) + len(en) + 1 > target:
            break
        english += " " + en
        chinese += zh
        cursor += 1
    for en, zh in SHORT:
        if len(english) + len(en) + 1 <= target:
            english += " " + en
            chinese += zh
    return english, chinese


def pitch_notes_fixture():
    blocks = [
        Block("title", "opening", "# [EA SPORTS FC™ 27 | Title Update v1.3.0 Pitch Notes]({ref0}) · 25 Nov 2026 · Offline sample",
              "# [FC27 v1.3.0 球場筆記]({ref0}) · 2026 年 11 月 25 日 · 離線排版示例", (PITCH,)),
        Block("cover", "opening", "[Cover image on the article]({ref0})", "[原文封面圖]({ref0})", (PITCH,)),
    ]
    number = 0

    def paragraphs(key, targets):
        nonlocal number
        for index, target in enumerate(targets, 1):
            number += 1
            refs = REFERENCES.get((key, index), ())
            en, zh = sample_text(number, target - sum(len(label) + 1 for label, _, _ in refs))
            for pos, (label, localized, _) in enumerate(refs):
                en += f" [{label}]({{ref{pos}}})"
                zh += f" [{localized}]({{ref{pos}}})"
            blocks.append(Block(f"{key}.p{index}", key, en, zh, tuple(r[2] for r in refs)))

    paragraphs("opening", (127, 245, 263, 275))
    toc = [["Contents", "目錄"]]
    for (_, en, zh, _), subs in OUTLINE:
        toc.append(["- " + en, "- " + zh])
        toc.extend([["  - " + sub[1], "  - " + sub[2]] for sub in subs])
    blocks.append(Block("contents", "contents", "\n".join(x[0] for x in toc), "\n".join(x[1] for x in toc)))

    for top, subs in OUTLINE:
        for level, (key, en, zh, sizes) in [(1, top)] + [(2, sub) for sub in subs]:
            heading = "#" * level + " "
            blocks.append(Block(key + ".heading", key, heading + en, heading + zh))
            paragraphs(key, sizes)
            if key in FIGURES:
                fragment, en, zh, size = FIGURES[key]
                blocks.append(Block(key + ".figure", key, f"[{en} · preview on EA]({{ref0}})",
                                    f"[{zh} · 原文示範]({{ref0}})", (PITCH + "#:~:text=" + quote(fragment, safe=""),)))
                if size:
                    number += 1
                    en, zh = sample_text(number, size)
                    blocks.append(Block(key + ".caption", key, en, zh))
    blocks.append(Block("signature", "feedback", "The fictional practice crew", "模擬演練小組"))
    return blocks

def illustrated_table_fixture():
    """Extra synthetic edge case. The actual 25 November Pitch Notes contain no data table."""
    en = ["| Practice | Start ⚽ | Finish |", "| --- | --- | --- |"]
    zh = ["| 練習 | 起點 ⚽ | 終點 |", "| --- | --- | --- |"]
    for n in range(1, 151):
        en.append(f"| Drill {n} | Marker {n} on the left | Marker {n + 1} on the right |")
        zh.append(f"| 演練 {n} | 左側第 {n} 個標誌筒 | 右側第 {n + 1} 個標誌筒 |")
    return [
        Block("exercise", "practice", "# Fictional drill", "# 虛構練習"),
        Block("table", "practice", "\n".join(en), "\n".join(zh)),
        Block("caption", "practice", "Table 1. Cone positions in practice order.", "表一。按練習次序排列的標誌筒位置。"),
        Block("drawing", "practice", "[Diagram]({ref0}) — the two end markers.",
              "[示意圖]({ref0}) — 兩端的標誌筒。", ("https://example.invalid/drill/diagram",)),
        Block("long", "notes", " ".join(f"Run {i} crossed the line ⚽." for i in range(320)),
              "".join(f"第 {i} 次練習越過邊線 ⚽。" for i in range(320))),
        Block("clip", "notes", "[Video]({ref0}) · last practice", "[影片]({ref0}) · 最後一次練習",
              ("https://example.invalid/drill/video",)),
    ]
