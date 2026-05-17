from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import Deque, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from cogs.menu import build_full_menu_view, build_main_menu_embed, build_menu_file, can_use_admin

ICON_MAP = {
    "short": "🍸",
    "tropical": "🍹",
    "wine": "🍷",
    "sparkling": "🥂",
    "beer": "🍺",
    "whisky": "🥃",
    "default": "🍸",
}

RARITY_STYLE = {
    "Common": {"label": "House Pour", "emoji": "⚪", "weight": 78, "color": 0x95A5A6},
    "Rare": {"label": "Signature Serve", "emoji": "🟣", "weight": 18, "color": 0x9B59B6},
    "SSR": {"label": "Top Shelf", "emoji": "🟡", "weight": 4, "color": 0xF1C40F},
}

RECENT_HISTORY_LIMIT = 8
DRINK_COOLDOWN_SECONDS = 1800.0
DRINK_USER_COOLDOWNS: dict[int, float] = {}


@dataclass(frozen=True)
class DrinkEntry:
    eng: str
    zh: str
    desc: str
    typ: str
    rarity: str = "Common"
    limited_tag: str | None = None


IBA: List[Tuple[str, str, str, str]] = [
    ("Alexander", "亞歷山大", "琴酒、可可甜酒與忌廉調製；入口柔滑，帶可可甜香與奶油尾韻。", "short"),
    ("Americano", "美式雞尾酒", "金巴利、甜苦艾酒與梳打水；苦甜開胃，氣泡感乾淨俐落。", "sparkling"),
    ("Angel Face", "天使之吻", "琴酒、杏子白蘭地與蘋果白蘭地；果香圓潤，酒體明亮。", "short"),
    ("Aviation", "航空", "琴酒、紫羅蘭甜酒與檸檬汁；花香細緻，酸度清爽。", "short"),
    ("Between the Sheets", "床笫之間", "白蘭地、蘭姆酒與橙酒；酒感扎實，酸甜平衡。", "short"),
    ("Boulevardier", "大道", "波本威士忌、金巴利與甜苦艾酒；苦甜厚實，尾段帶木桶感。", "whisky"),
    ("Brandy Crusta", "白蘭地克拉斯塔", "白蘭地、檸檬與橙酒；杯沿糖霜帶來經典酸甜層次。", "short"),
    ("Casino", "賭場", "琴酒、檸檬汁與橙酒；柑橘調清晰，收結俐落。", "short"),
    ("Clover Club", "三葉草俱樂部", "琴酒、紅石榴糖漿與蛋白；質感綿密，莓果酸甜柔和。", "short"),
    ("Daiquiri", "戴吉利", "蘭姆酒、青檸汁與糖漿；酸甜精準，展現蘭姆酒清爽骨架。", "tropical"),
    ("Dry Martini", "乾馬丁尼", "琴酒與乾苦艾酒；乾爽、冷冽、極簡，突出酒體線條。", "short"),
    ("Gin Fizz", "琴費士", "琴酒、檸檬汁與梳打水；氣泡輕盈，柑橘香明亮。", "sparkling"),
    ("Hanky Panky", "花招", "琴酒、甜苦艾酒與費南特苦酒；草本辛香突出，苦韻成熟。", "short"),
    ("John Collins", "約翰可林斯", "琴酒、檸檬汁、糖與梳打水；修長清爽，適合慢飲。", "sparkling"),
    ("Last Word", "最後的話", "琴酒、綠查特、櫻桃利口酒與檸檬汁；草本、果香與酸度非常平衡。", "short"),
    ("Manhattan", "曼哈頓", "黑麥威士忌與甜苦艾酒；辛香、苦甜、酒體深邃。", "whisky"),
    ("Martinez", "馬丁內斯", "琴酒、甜苦艾酒與橙味苦精；古典優雅，帶馬丁尼前身的圓潤感。", "short"),
    ("Mary Pickford", "瑪麗・碧克馥", "蘭姆酒、菠蘿汁與紅石榴糖漿；熱帶果香甜美，色澤明亮。", "tropical"),
    ("Monkey Gland", "猴腺", "琴酒、橙汁與紅石榴糖漿；果香鮮明，尾段微甜。", "short"),
    ("Negroni", "內格羅尼", "琴酒、金巴利與甜苦艾酒；苦甜均衡，草本感完整。", "short"),
    ("Old Fashioned", "古典雞尾酒", "威士忌、方糖與苦精；酒體厚實，木桶、香料與甜感層次分明。", "whisky"),
    ("Paradise", "天堂", "琴酒、杏子白蘭地與橙汁；果香柔順，酸甜輕盈。", "short"),
    ("Planter’s Punch", "種植者潘趣酒", "蘭姆酒與果汁調製；果香濃郁，熱帶感飽滿。", "tropical"),
    ("Porto Flip", "波特翻轉", "波特酒、白蘭地與蛋黃；口感厚滑，帶成熟果甜。", "wine"),
    ("Rusty Nail", "鏽釘", "蘇格蘭威士忌配蜂蜜香草利口酒；溫潤厚實，帶柔和甜香。", "whisky"),
    ("Sazerac", "薩澤拉克", "黑麥威士忌、苦艾酒與苦精；辛香強烈，紐奧良經典風格。", "whisky"),
    ("Sidecar", "邊車", "白蘭地、橙酒與檸檬汁；酸甜平衡，酒感俐落。", "short"),
    ("Stinger", "毒螫", "白蘭地與薄荷甜酒；甜中帶涼感，收結乾淨。", "short"),
    ("Tuxedo", "燕尾服", "琴酒與雪莉調製；乾爽優雅，帶細緻堅果與辛香。", "short"),
    ("Whiskey Sour", "威士忌酸酒", "威士忌、檸檬汁與糖漿；酸甜濃烈，平衡度高。", "whisky"),
    ("White Lady", "白衣女子", "琴酒、橙酒與檸檬汁；柑橘酸香柔和，口感乾淨。", "short"),
    ("Aperol Spritz", "阿佩羅氣泡酒", "阿佩羅、氣泡酒與梳打水；橙皮苦甜，輕盈開胃。", "sparkling"),
    ("Barracuda", "梭魚", "金色蘭姆酒、加利安諾與菠蘿汁；熱帶果香配上輕微氣泡感。", "tropical"),
    ("B52", "B52", "咖啡利口酒、百利甜與橙酒分層；甜香濃郁，層次分明。", "short"),
    ("Bellini", "貝里尼", "氣泡酒與白桃泥；果香細緻，酒感優雅。", "sparkling"),
    ("Black Russian", "黑俄羅斯", "伏特加與咖啡甜酒；簡潔濃烈，咖啡甜苦突出。", "short"),
    ("Bloody Mary", "血腥瑪麗", "伏特加、番茄汁與香料；鹹鮮辛香，醒胃感強。", "tropical"),
    ("Caipirinha", "卡皮里尼亞", "卡莎薩、青檸與糖；青檸油香鮮明，巴西經典。", "tropical"),
    ("Champagne Cocktail", "香檳雞尾酒", "香檳、方糖與苦精；簡潔高雅，氣泡帶出苦甜層次。", "sparkling"),
    ("Cosmopolitan", "大都會", "伏特加、橙酒與蔓越莓汁；酸甜俐落，果香時尚。", "short"),
    ("Cuba Libre", "自由古巴", "蘭姆酒、可樂與青檸汁；簡單爽快，焦糖與柑橘平衡。", "tropical"),
    ("French 75", "法式75", "琴酒、檸檬汁與香檳；酸香明亮，氣泡乾淨。", "sparkling"),
    ("French Connection", "法式連線", "干邑與杏仁利口酒；酒體簡潔，杏仁甜香圓潤。", "short"),
    ("Golden Dream", "黃金夢", "橙酒、加利安諾與忌廉；香滑甜美，帶雲呢拿氣息。", "short"),
    ("Grasshopper", "綠色蚱蜢", "薄荷甜酒、可可甜酒與忌廉；清涼甜香，口感柔滑。", "short"),
    ("Harvey Wallbanger", "哈維撞牆", "伏特加、橙汁與加利安諾；果香醒神，尾段帶草本甜香。", "short"),
    ("Hemingway Special", "海明威特調", "蘭姆酒、葡萄柚與櫻桃利口酒；酸爽清新，苦韻細緻。", "tropical"),
    ("Horse’s Neck", "馬頸", "波本或白蘭地配薑汁汽水與檸皮捲；辛香爽口。", "beer"),
    ("Irish Coffee", "愛爾蘭咖啡", "熱咖啡、愛爾蘭威士忌與鮮忌廉；暖身厚實，咖啡香濃。", "whisky"),
    ("Kir", "基爾", "白酒與黑醋栗利口酒；簡單優雅，果香柔和。", "wine"),
    ("Long Island Iced Tea", "長島冰茶", "多款烈酒混合並以可樂收尾；酒感強勁，酸甜爽快。", "tropical"),
    ("Mai Tai", "邁泰", "蘭姆酒、橙酒與杏仁糖漿；熱帶果香與堅果甜香並重。", "tropical"),
    ("Mimosa", "含羞草", "香檳與柳橙汁；輕盈果香，早午餐經典。", "sparkling"),
    ("Mint Julep", "薄荷朱利酒", "波本、薄荷與碎冰；清涼消暑，木桶甜香明顯。", "whisky"),
    ("Mojito", "莫吉托", "蘭姆酒、薄荷、青檸與梳打水；清新爽口，香草感明亮。", "tropical"),
    ("Moscow Mule", "莫斯科騾子", "伏特加、薑汁啤酒與青檸汁；辛口清爽，氣泡感活潑。", "beer"),
    ("Piña Colada", "椰林飄香", "蘭姆酒、椰漿與菠蘿汁；椰香豐厚，熱帶甜美。", "tropical"),
    ("Sea Breeze", "海風", "伏特加、蔓越莓與葡萄柚汁；酸甜清爽，果香乾淨。", "tropical"),
    ("Sex on the Beach", "海灘性愛", "伏特加、桃子甜酒與果汁；甜美易飲，果香奔放。", "tropical"),
    ("Singapore Sling", "新加坡司令", "琴酒、菠蘿汁與櫻桃白蘭地；熱帶感華麗，層次豐富。", "tropical"),
    ("Tequila Sunrise", "龍舌蘭日出", "龍舌蘭、柳橙汁與紅石榴糖漿；色彩鮮明，果香甜潤。", "tropical"),
    ("Vampiro", "吸血鬼", "龍舌蘭、番茄汁與香料；濃烈辛辣，鹹鮮感突出。", "tropical"),
    ("Yellow Bird", "黃鳥", "蘭姆酒、加利安諾與橙汁；果香熱帶，甜感明亮。", "tropical"),
    ("Zombie", "殭屍", "多款蘭姆酒與果汁調製；酒體強勁，熱帶層次濃厚。", "tropical"),
    ("Barrio", "巴里奧", "龍舌蘭、番茄汁與香料混合；辛香濃烈，風味厚重。", "tropical"),
    ("Bramble", "黑莓酒", "琴酒、黑莓利口酒與檸檬汁；莓果酸甜，口感清爽。", "short"),
    ("Dark ’n’ Stormy", "黑暗風暴", "黑蘭姆酒與薑汁啤酒；焦糖厚度配辛辣氣泡。", "beer"),
    ("Espresso Martini", "濃縮馬丁尼", "伏特加與咖啡；醇厚帶甜，咖啡泡沫細緻。", "short"),
    ("French Martini", "法式馬丁尼", "伏特加、黑醋栗利口酒與菠蘿汁；酸甜高雅，果香柔順。", "short"),
    ("Illegal", "非法", "梅斯卡爾、利萊與葡萄柚；煙燻酸爽，層次鮮明。", "whisky"),
    ("London Mule", "倫敦騾子", "琴酒、薑汁啤酒與青檸汁；辛辣清新，草本感輕盈。", "beer"),
    ("Paloma", "白鴿", "龍舌蘭與葡萄柚汽水；微苦清爽，非常易飲。", "tropical"),
    ("Paper Plane", "紙飛機", "波本、阿佩羅、阿瑪羅與檸檬汁；苦甜酸度精準。", "whisky"),
    ("Penicillin", "青黴素", "威士忌、蜂蜜與薑汁；煙燻暖胃，辛香甜潤。", "whisky"),
    ("Russian Spring Punch", "俄羅斯春季潘趣酒", "伏特加、黑醋栗利口酒與香檳；果香明亮，氣泡清爽。", "sparkling"),
    ("Spritz Veneziano", "威尼斯氣泡酒", "阿佩羅、普羅賽克與梳打水；苦甜輕盈，餐前酒風格。", "sparkling"),
    ("Tommy’s Margarita", "湯米瑪格麗塔", "龍舌蘭、青檸與龍舌蘭糖漿；酸甜更俐落，龍舌蘭感突出。", "tropical"),
    ("Vesper", "維斯珀馬丁尼", "琴酒、伏特加與利萊酒；冷冽俐落，酒體乾淨。", "short"),
]

ADJECTIVES: List[Tuple[str, str]] = [
    ("Smoky", "煙燻"),
    ("Citrus", "柑橘"),
    ("Spiced", "香料"),
    ("Tropical", "熱帶果香"),
    ("Berry", "莓果"),
    ("Herbal", "草本"),
    ("Floral", "花香"),
    ("Sweet", "柔甜"),
    ("Dry", "乾身"),
    ("Bold", "濃烈"),
    ("Fresh", "清新"),
    ("Creamy", "奶香"),
]

SPIRITS: List[Tuple[str, str, str]] = [
    ("Whisky", "威士忌", "whisky"),
    ("Bourbon", "波本", "whisky"),
    ("Rum", "蘭姆酒", "tropical"),
    ("Gin", "琴酒", "short"),
    ("Vodka", "伏特加", "short"),
    ("Tequila", "龍舌蘭", "tropical"),
    ("Mezcal", "梅斯卡爾", "whisky"),
    ("Brandy", "白蘭地", "short"),
]

STYLES: List[Tuple[str, str, str]] = [
    ("Highball", "高球", "short"),
    ("Sour", "酸酒", "short"),
    ("Fizz", "費士", "sparkling"),
    ("Collins", "可林斯", "short"),
    ("Martini", "馬丁尼", "short"),
    ("Spritz", "氣泡酒", "sparkling"),
    ("Mule", "騾子", "beer"),
    ("Julep", "朱利酒", "whisky"),
]

FLAVORS: List[Tuple[str, str]] = [
    ("with Ginger", "薑汁"),
    ("with Honey", "蜂蜜"),
    ("with Mint", "薄荷"),
    ("with Basil", "羅勒"),
    ("with Peach", "水蜜桃"),
    ("with Coconut", "椰香"),
    ("with Coffee", "咖啡"),
    ("with Chocolate", "朱古力"),
    ("with Yuzu", "柚子"),
    ("with Lychee", "荔枝"),
    ("with Passionfruit", "熱情果"),
    ("with Pineapple", "菠蘿"),
]

SEASONAL_DRINKS: Dict[Tuple[int, ...], List[DrinkEntry]] = {
    (12, 1, 2): [
        DrinkEntry("Snowflake Martini", "雪花馬丁尼", "冷冽酒體配上淡甜奶香；冬日限定，口感細緻柔滑。", "short", "SSR", "冬日限定"),
        DrinkEntry("Hot Honey Whisky", "熱蜜威士忌", "蜂蜜暖感與威士忌厚度交疊；適合寒夜慢慢品嚐。", "whisky", "Rare", "冬日限定"),
    ],
    (3, 4, 5): [
        DrinkEntry("Sakura Fizz", "櫻花費士", "花香與清爽氣泡感並重；春日限定，輕盈明亮。", "sparkling", "SSR", "春日限定"),
        DrinkEntry("Garden Collins", "花園可林斯", "草本與柑橘交織；入口清爽，尾韻乾淨。", "short", "Rare", "春日限定"),
    ],
    (6, 7, 8): [
        DrinkEntry("Sunset Colada", "夕陽可樂達", "椰香與果香飽滿；夏日限定，熱帶感濃厚。", "tropical", "SSR", "夏日限定"),
        DrinkEntry("Mango Breeze", "芒果海風", "清甜果香配上爽口尾韻；夏日限定，輕鬆易飲。", "tropical", "Rare", "夏日限定"),
    ],
    (9, 10, 11): [
        DrinkEntry("Maple Old Fashioned", "楓糖古典", "楓糖甜香提升威士忌層次；秋日限定，木桶感更圓潤。", "whisky", "SSR", "秋日限定"),
        DrinkEntry("Roasted Fig Sour", "烤無花果酸酒", "果甜帶微酸，尾段溫潤厚實；秋日限定。", "short", "Rare", "秋日限定"),
    ],
}

TASTING_LINES = [
    "酒體平衡，香氣由前段慢慢展開，適合慢慢品嚐。",
    "入口乾淨，尾韻有層次，屬於容易入口但不單調的一杯。",
    "香氣集中，酸甜與酒感比例清晰，是吧枱上很穩的一杯。",
    "風味有記憶點，既保留基酒個性，又有足夠修飾。",
    "整體線條俐落，前段香氣明顯，收結不拖泥帶水。",
]


def build_tasting_note(drink: DrinkEntry) -> str:
    base = drink.desc.rstrip("。")
    return f"{base}。{random.choice(TASTING_LINES)}"


def get_drink_retry_after(user_id: int) -> float:
    last_used = DRINK_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = DRINK_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_drink_cooldown(user_id: int) -> None:
    DRINK_USER_COOLDOWNS[user_id] = time.time()


def rarity_for_generated_name(eng: str, typ: str) -> str:
    rare_keywords = ("Martini", "Vesper", "Paper Plane", "Penicillin", "French 75", "Negroni")
    ssr_keywords = ("Zombie", "Long Island", "Old Fashioned", "Manhattan", "Piña Colada", "Singapore Sling")

    if any(key.lower() in eng.lower() for key in ssr_keywords):
        return "SSR"
    if any(key.lower() in eng.lower() for key in rare_keywords):
        return "Rare"
    if typ in {"wine", "sparkling"}:
        return "Rare"
    return "Common"


def build_drinks() -> List[DrinkEntry]:
    drinks: List[DrinkEntry] = []

    for eng, zh, desc, typ in IBA:
        drinks.append(DrinkEntry(eng, zh, desc, typ, rarity_for_generated_name(eng, typ)))

    for adj_en, adj_zh in ADJECTIVES:
        for sp_en, sp_zh, sp_type in SPIRITS:
            eng = f"{adj_en} {sp_en}"
            zh = f"{adj_zh}{sp_zh}"
            desc = f"以{sp_zh}為主體，呈現{adj_zh}取向；香氣直接，酒體線條清晰。"
            rarity = "Rare" if adj_en in {"Floral", "Creamy", "Bold"} else "Common"
            drinks.append(DrinkEntry(eng, zh, desc, sp_type, rarity))

            for sty_en, sty_zh, sty_type in STYLES:
                eng2 = f"{adj_en} {sp_en} {sty_en}"
                zh2 = f"{adj_zh}{sp_zh}{sty_zh}"
                desc2 = f"以{sp_zh}作基底，調成{sty_zh}風格；{adj_zh}調性突出，結構平衡。"
                rarity2 = "Rare" if sty_en in {"Martini", "Spritz"} or adj_en in {"Bold", "Floral"} else "Common"
                drinks.append(DrinkEntry(eng2, zh2, desc2, sty_type, rarity2))

            for flav_en, flav_zh in FLAVORS:
                eng3 = f"{sp_en} {flav_en} ({adj_en})"
                zh3 = f"{adj_zh}{sp_zh}{flav_zh}"
                desc3 = f"以{sp_zh}為基酒，融入{flav_zh}風味；{adj_zh}口感更有層次。"
                rarity3 = (
                    "SSR"
                    if flav_en in {"with Yuzu", "with Lychee", "with Passionfruit"} and adj_en in {"Floral", "Fresh"}
                    else "Rare"
                    if flav_en in {"with Coffee", "with Chocolate"}
                    else "Common"
                )
                drinks.append(DrinkEntry(eng3, zh3, desc3, sp_type, rarity3))

    return drinks


ALL_DRINKS: List[DrinkEntry] = build_drinks()


def current_seasonal_pool() -> List[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return pool
    return []


async def send_or_followup(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    file: discord.File | None = None,
    content: str | None = None,
    ephemeral: bool = False,
) -> None:
    """Safely send interaction response / followup.

    discord.py 對 file=None / view=None 會有機會當成實物處理，
    導致 NoneType.to_dict / NoneType.is_finished。
    所以所有 optional arg 都只喺非 None 時先放入 kwargs。
    """
    kwargs: dict[str, object] = {"ephemeral": ephemeral}

    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


def build_quick_bar_kwargs(interaction: discord.Interaction) -> dict[str, object]:
    """Build Quick Bar payload for the same Discord message.

    用同一個 message 出兩個 embeds：
    1) Bartender’s Pick result
    2) Con9sole Bartender Quick Bar

    注意：唔傳 view=None / file=None，避免 discord.py NoneType error。
    """
    menu_embed = build_main_menu_embed(interaction.user)

    kwargs: dict[str, object] = {}

    menu_view = build_full_menu_view(interaction)
    if menu_view is not None:
        kwargs["view"] = menu_view

    menu_file = build_menu_file()
    if menu_file is not None:
        kwargs["file"] = menu_file

    kwargs["menu_embed"] = menu_embed
    return kwargs


class Drink(commands.Cog):
    """/drink：以 bartender 風格隨機為指定對象點一款酒。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

    async def _record_usage(self, interaction: discord.Interaction) -> None:
        menu_cog = self.bot.get_cog("Menu")
        if menu_cog and hasattr(menu_cog, "record_usage"):
            try:
                await menu_cog.record_usage("drink", interaction.user.id, interaction.guild_id)
            except Exception:
                pass

    async def _enforce_drink_cooldown(self, interaction: discord.Interaction) -> bool:
        # Admin / helpers 無視調酒 cooldown
        if can_use_admin(interaction.user):
            return True

        retry_after = get_drink_retry_after(interaction.user.id)
        if retry_after > 0:
            message = f"⏳ 酒保正在整理吧枱，請等 {retry_after:.1f} 秒後再點下一杯。"
            await send_or_followup(interaction, content=message, ephemeral=True)
            return False

        touch_drink_cooldown(interaction.user.id)
        return True

    def _pick_rarity(self) -> str:
        labels = list(RARITY_STYLE.keys())
        weights = [RARITY_STYLE[label]["weight"] for label in labels]
        return random.choices(labels, weights=weights, k=1)[0]

    def _build_pool_for_rarity(self, rarity: str) -> List[DrinkEntry]:
        pool = [drink for drink in ALL_DRINKS if drink.rarity == rarity]
        seasonal = [drink for drink in current_seasonal_pool() if drink.rarity == rarity]
        return pool + seasonal

    def _pick_unique_drink(self, user_id: int, rarity: str) -> DrinkEntry:
        pool = self._build_pool_for_rarity(rarity)
        if not pool:
            pool = ALL_DRINKS + current_seasonal_pool()

        recent = set(self.user_recent_draws[user_id])
        candidates = [d for d in pool if d.eng not in recent]
        chosen = random.choice(candidates or pool)
        self.user_recent_draws[user_id].append(chosen.eng)
        return chosen

    def _build_header_line(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None,
        drink: DrinkEntry,
    ) -> str:
        icon = ICON_MAP.get(drink.typ, ICON_MAP["default"])
        giver = interaction.user.mention
        receiver = (to or interaction.user).mention

        if to and to.id != interaction.user.id:
            return f"{icon} {giver} 為 {receiver} 點了一杯 **{drink.eng}（{drink.zh}）**。"
        return f"{icon} {giver} 在吧枱前點了一杯 **{drink.eng}（{drink.zh}）**。"

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_drink_cooldown(interaction)
            if not ok:
                return

        await self._record_usage(interaction)

        rarity = self._pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 **限定供應：** {drink.limited_tag}" if drink.limited_tag else ""
        tasting_note = build_tasting_note(drink)

        result_embed = discord.Embed(
            title="Bartender’s Pick",
            color=rarity_meta["color"],
            timestamp=discord.utils.utcnow(),
        )
        result_embed.add_field(
            name="　",
            value=f"{header}\n\n➡️ **品飲筆記：** {tasting_note}{limited_text}",
            inline=False,
        )
        result_embed.add_field(
            name="吧枱級別",
            value=f"{rarity_meta['emoji']} **{rarity_meta['label']}**",
            inline=True,
        )
        result_embed.add_field(
            name="風格分類",
            value=f"{ICON_MAP.get(drink.typ, ICON_MAP['default'])} `{drink.typ}`",
            inline=True,
        )
        result_embed.add_field(
            name="酒單輪替",
            value=f"已避開你最近品嚐過的 {RECENT_HISTORY_LIMIT} 杯",
            inline=True,
        )
        result_embed.set_footer(text="House Pour 78% · Signature Serve 18% · Top Shelf 4%")

        quick_bar_kwargs = build_quick_bar_kwargs(interaction)
        menu_embed = quick_bar_kwargs.pop("menu_embed")

        # Same Discord message, two embeds, one button row.
        # 呢個 layout 會似 RPG bot：同一個 bot message 入面，上方結果卡，下方 Quick Bar 卡。
        send_kwargs: dict[str, object] = {
            "embeds": [result_embed, menu_embed],
        }
        send_kwargs.update(quick_bar_kwargs)

        if interaction.response.is_done():
            await interaction.followup.send(**send_kwargs)
        else:
            await interaction.response.send_message(**send_kwargs)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="由酒保為你或指定成員調一杯特選飲品")
    @app_commands.describe(to="收酒嘅人")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None):
        await self.do_drink(interaction, to, enforce_cooldown=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
