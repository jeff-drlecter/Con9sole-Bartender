from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import random
from typing import Deque, Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID
from cogs.menu import build_full_menu_view, build_main_menu_embed, build_menu_file

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
    "Common": {
        "label": "Common",
        "emoji": "⚪",
        "weight": 78,
        "color": 0x95A5A6,
    },
    "Rare": {
        "label": "Rare",
        "emoji": "🟣",
        "weight": 18,
        "color": 0x9B59B6,
    },
    "SSR": {
        "label": "SSR",
        "emoji": "🟡",
        "weight": 4,
        "color": 0xF1C40F,
    },
}

RECENT_HISTORY_LIMIT = 8


@dataclass(frozen=True)
class DrinkEntry:
    eng: str
    zh: str
    desc: str
    typ: str
    rarity: str = "Common"
    limited_tag: str | None = None


IBA: List[Tuple[str, str, str, str]] = [
    ("Alexander", "亞歷山大", "琴酒、可可甜酒與忌廉調製，柔和香甜。", "short"),
    ("Americano", "美式雞尾酒", "金巴利、甜苦艾酒加梳打水，清爽開胃。", "sparkling"),
    ("Angel Face", "天使之吻", "琴酒、杏子白蘭地與蘋果白蘭地，果香柔和。", "short"),
    ("Aviation", "航空", "琴酒、紫羅蘭甜酒、檸檬汁，帶花香酸味。", "short"),
    ("Between the Sheets", "床笫之間", "白蘭地、蘭姆與橙酒，酸甜平衡。", "short"),
    ("Boulevardier", "大道", "波本威士忌、金巴利、甜苦艾酒，苦甜厚實。", "whisky"),
    ("Brandy Crusta", "白蘭地克拉斯塔", "白蘭地加檸檬與橙酒，杯沿裹糖。", "short"),
    ("Casino", "賭場", "琴酒、檸檬汁與橙味利口酒，清爽俐落。", "short"),
    ("Clover Club", "三葉草俱樂部", "琴酒、紅石榴糖漿與蛋白，粉嫩酸甜。", "short"),
    ("Daiquiri", "戴吉利", "蘭姆酒、青檸汁與糖漿，清爽平衡。", "tropical"),
    ("Dry Martini", "乾馬丁尼", "琴酒加苦艾酒，乾爽俐落。", "short"),
    ("Gin Fizz", "琴費士", "琴酒、檸檬汁加梳打，清爽氣泡。", "sparkling"),
    ("Hanky Panky", "花招", "琴酒、甜苦艾酒與費南特苦酒，草本辛香。", "short"),
    ("John Collins", "約翰可林斯", "琴酒、檸檬汁、梳打水，酸甜清爽。", "sparkling"),
    ("Last Word", "最後的話", "琴酒、綠查特、櫻桃利口酒與檸檬汁，草本酸甜。", "short"),
    ("Manhattan", "曼哈頓", "黑麥威士忌與甜苦艾酒，苦甜厚重。", "whisky"),
    ("Martinez", "馬丁內斯", "琴酒、甜苦艾酒與橙味苦精，馬丁尼前身。", "short"),
    ("Mary Pickford", "瑪麗‧碧克馥", "蘭姆、菠蘿汁與紅石榴糖漿，熱帶甜美。", "tropical"),
    ("Monkey Gland", "猴腺", "琴酒、橙汁與紅石榴糖漿，色彩鮮豔。", "short"),
    ("Negroni", "內格羅尼", "琴酒、金巴利與甜苦艾酒，苦甜兼備。", "short"),
    ("Old Fashioned", "古典雞尾酒", "威士忌加方糖與苦精，經典濃烈。", "whisky"),
    ("Paradise", "天堂", "琴酒、杏子白蘭地與橙汁，果香怡人。", "short"),
    ("Planter’s Punch", "種植者潘趣酒", "蘭姆與果汁，濃郁果香。", "tropical"),
    ("Porto Flip", "波特翻轉", "波特酒、白蘭地與蛋黃，濃厚香甜。", "wine"),
    ("Rusty Nail", "鏽釘", "蘇威加蜂蜜酒，溫潤厚實。", "whisky"),
    ("Sazerac", "薩澤拉克", "黑麥威士忌、苦艾酒與苦精，紐奧良經典。", "whisky"),
    ("Sidecar", "邊車", "白蘭地、橙酒與檸檬汁，酸甜平衡。", "short"),
    ("Stinger", "毒螫", "白蘭地與薄荷甜酒，甜中清涼。", "short"),
    ("Tuxedo", "燕尾服", "琴酒與雪莉調製，優雅辛香。", "short"),
    ("Whiskey Sour", "威士忌酸酒", "威士忌、檸檬汁與糖漿，酸甜濃烈。", "whisky"),
    ("White Lady", "白衣女子", "琴酒、橙酒與檸檬汁，酸香柔和。", "short"),
    ("Aperol Spritz", "阿佩羅氣泡酒", "阿佩羅、氣泡酒與梳打水，輕盈果香。", "sparkling"),
    ("Barracuda", "梭魚", "金蘭姆、加利安諾與菠蘿汁，帶氣泡。", "tropical"),
    ("B52", "B52", "分層咖啡利口酒、百利甜與橙酒，層次分明。", "short"),
    ("Bellini", "貝里尼", "氣泡酒加白桃泥，優雅果香。", "sparkling"),
    ("Black Russian", "黑俄羅斯", "伏特加加咖啡甜酒，濃烈厚重。", "short"),
    ("Bloody Mary", "血腥瑪麗", "伏特加加番茄汁與香料，鹹鮮醒胃。", "tropical"),
    ("Caipirinha", "卡皮里尼亞", "卡莎薩加青檸與糖，巴西國民酒。", "tropical"),
    ("Champagne Cocktail", "香檳雞尾酒", "香檳加方糖與苦精，簡單高貴。", "sparkling"),
    ("Cosmopolitan", "大都會", "伏特加、橙酒、蔓越莓汁，時尚代表。", "short"),
    ("Cuba Libre", "自由古巴", "蘭姆加可樂與青檸汁，經典簡單。", "tropical"),
    ("French 75", "法式75", "琴酒、檸檬汁與香檳，酸香帶氣泡。", "sparkling"),
    ("French Connection", "法式連線", "干邑與杏仁利口酒，簡潔濃烈。", "short"),
    ("Golden Dream", "黃金夢", "橙酒、茴香酒與忌廉，香滑甜美。", "short"),
    ("Grasshopper", "綠色蚱蜢", "薄荷甜酒、可可甜酒與忌廉，清涼香甜。", "short"),
    ("Harvey Wallbanger", "哈維撞牆", "伏特加、橙汁與加利安諾，酸甜醒神。", "short"),
    ("Hemingway Special", "海明威特調", "蘭姆、葡萄柚與櫻桃利口酒，酸爽清新。", "tropical"),
    ("Horse’s Neck", "馬頸", "波本/白蘭地加薑汁汽水與檸皮捲。", "beer"),
    ("Irish Coffee", "愛爾蘭咖啡", "熱咖啡、愛爾蘭威士忌與鮮忌廉。", "whisky"),
    ("Kir", "基爾", "白酒加黑醋栗利口酒，簡單優雅。", "wine"),
    ("Long Island Iced Tea", "長島冰茶", "多種烈酒混合，可樂頂滿，強勁有力。", "tropical"),
    ("Mai Tai", "邁泰", "蘭姆酒加果汁，熱帶風情。", "tropical"),
    ("Mimosa", "含羞草", "香檳加柳橙汁，早午餐必備。", "sparkling"),
    ("Mint Julep", "薄荷朱利酒", "波本加薄荷與碎冰，清爽消暑。", "whisky"),
    ("Mojito", "莫吉托", "蘭姆、薄荷、青檸與梳打水，清新爽口。", "tropical"),
    ("Moscow Mule", "莫斯科騾子", "伏特加、薑汁啤酒與青檸汁，辛口清爽。", "beer"),
    ("Piña Colada", "椰林飄香", "蘭姆、椰漿與菠蘿汁，熱帶甜美。", "tropical"),
    ("Sea Breeze", "海風", "伏特加、蔓越莓與葡萄柚汁，清爽酸甜。", "tropical"),
    ("Sex on the Beach", "海灘性愛", "伏特加、桃子甜酒與果汁，甜美討喜。", "tropical"),
    ("Singapore Sling", "新加坡司令", "琴酒加鳳梨汁與櫻桃白蘭地，熱帶經典。", "tropical"),
    ("Tequila Sunrise", "龍舌蘭日出", "龍舌蘭、柳橙汁與紅石榴糖漿，色彩鮮明。", "tropical"),
    ("Vampiro", "吸血鬼", "龍舌蘭、番茄汁與香料，濃烈辛辣。", "tropical"),
    ("Yellow Bird", "黃鳥", "蘭姆、加利安諾與橙汁，果香熱帶。", "tropical"),
    ("Zombie", "殭屍", "多款蘭姆與果汁，強勁有力。", "tropical"),
    ("Barrio", "巴里奧", "龍舌蘭、番茄汁與香料混合，風味濃烈。", "tropical"),
    ("Bramble", "黑莓酒", "琴酒、黑莓利口酒與檸檬汁，莓果酸甜。", "short"),
    ("Dark ’n’ Stormy", "黑暗風暴", "黑蘭姆與薑汁啤酒，辛辣清爽。", "beer"),
    ("Espresso Martini", "濃縮馬丁尼", "伏特加加咖啡，醇厚帶甜。", "short"),
    ("French Martini", "法式馬丁尼", "伏特加、黑醋栗利口酒與鳳梨汁，酸甜高雅。", "short"),
    ("Illegal", "非法", "梅斯卡爾、利萊與葡萄柚，煙燻酸爽。", "whisky"),
    ("London Mule", "倫敦騾子", "琴酒、薑汁啤酒與青檸汁，辛辣清新。", "beer"),
    ("Paloma", "白鴿", "龍舌蘭與葡萄柚汽水，清爽易飲。", "tropical"),
    ("Paper Plane", "紙飛機", "波本、阿佩羅、阿瑪羅與檸檬汁，苦甜平衡。", "whisky"),
    ("Penicillin", "青黴素", "威士忌、蜂蜜與薑汁，煙燻暖胃。", "whisky"),
    ("Russian Spring Punch", "俄羅斯春季潘趣酒", "伏特加、黑醋栗利口酒與香檳，清爽氣泡。", "sparkling"),
    ("Spritz Veneziano", "威尼斯氣泡酒", "阿佩羅、普羅賽克與梳打水，輕盈果香。", "sparkling"),
    ("Tommy’s Margarita", "湯米瑪格麗塔", "龍舌蘭糖漿取代橙酒，更俐落清爽。", "tropical"),
    ("Vesper", "維斯珀馬丁尼", "琴酒、伏特加與利萊酒，冷冽俐落。", "short"),
]

ADJECTIVES: List[Tuple[str, str]] = [
    ("Smoky", "煙燻"), ("Citrus", "柑橘"), ("Spiced", "香料"), ("Tropical", "熱帶"),
    ("Berry", "莓果"), ("Herbal", "草本"), ("Floral", "花香"), ("Sweet", "甜味"),
    ("Dry", "乾口"), ("Bold", "濃烈"), ("Fresh", "清新"), ("Creamy", "奶香"),
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
    ("Fizz", "氣泡酒", "sparkling"),
    ("Collins", "可林斯", "short"),
    ("Martini", "馬丁尼", "short"),
    ("Spritz", "氣泡", "sparkling"),
    ("Mule", "騾子", "tropical"),
    ("Julep", "朱利酒", "tropical"),
]

FLAVORS: List[Tuple[str, str]] = [
    ("with Ginger", "加薑"), ("with Honey", "加蜂蜜"), ("with Mint", "加薄荷"),
    ("with Basil", "加羅勒"), ("with Peach", "加水蜜桃"), ("with Coconut", "加椰子"),
    ("with Coffee", "加咖啡"), ("with Chocolate", "加朱古力"), ("with Yuzu", "加柚子"),
    ("with Lychee", "加荔枝"), ("with Passionfruit", "加熱情果"), ("with Pineapple", "加菠蘿"),
]

SEASONAL_DRINKS: Dict[Tuple[int, ...], List[DrinkEntry]] = {
    (12, 1, 2): [
        DrinkEntry("Snowflake Martini", "雪花馬丁尼", "冷冽酒體配上淡甜奶香，冬日限定。", "short", "SSR", "冬日限定"),
        DrinkEntry("Hot Honey Whisky", "熱蜜威士忌", "蜂蜜暖感與威士忌厚度交疊，適合寒夜。", "whisky", "Rare", "冬日限定"),
    ],
    (3, 4, 5): [
        DrinkEntry("Sakura Fizz", "櫻花氣泡酒", "帶花香與清爽氣泡感，春日限定。", "sparkling", "SSR", "春日限定"),
        DrinkEntry("Garden Collins", "花園可林斯", "草本與柑橘交織，輕盈明亮。", "short", "Rare", "春日限定"),
    ],
    (6, 7, 8): [
        DrinkEntry("Sunset Colada", "夕陽可樂達", "椰香與果香飽滿，熱帶感爆棚。", "tropical", "SSR", "夏日限定"),
        DrinkEntry("Mango Breeze", "芒果海風", "清甜果香配上爽口尾韻，超消暑。", "tropical", "Rare", "夏日限定"),
    ],
    (9, 10, 11): [
        DrinkEntry("Maple Old Fashioned", "楓糖古典", "楓糖甜香提升威士忌層次，秋日限定。", "whisky", "SSR", "秋日限定"),
        DrinkEntry("Roasted Fig Sour", "烤無花果酸酒", "果甜帶微酸，尾段溫潤厚實。", "short", "Rare", "秋日限定"),
    ],
}


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
            desc = f"以{sp_zh}為基酒，呈現{adj_zh}風味。"
            rarity = "Common"
            if adj_en in {"Floral", "Creamy", "Bold"}:
                rarity = "Rare"
            drinks.append(DrinkEntry(eng, zh, desc, sp_type, rarity))

            for sty_en, sty_zh, sty_type in STYLES:
                eng2 = f"{adj_en} {sp_en} {sty_en}"
                zh2 = f"{adj_zh}{sp_zh}{sty_zh}"
                desc2 = f"以{sp_zh}為基酒，調製成{sty_zh}風格，帶有{adj_zh}特色。"
                rarity2 = "Rare" if sty_en in {"Martini", "Spritz"} or adj_en in {"Bold", "Floral"} else "Common"
                drinks.append(DrinkEntry(eng2, zh2, desc2, sty_type, rarity2))

            for flav_en, flav_zh in FLAVORS:
                eng3 = f"{sp_en} {flav_en} ({adj_en})"
                zh3 = f"{adj_zh}{sp_zh}{flav_zh}"
                desc3 = f"以{sp_zh}為基酒，加入{flav_zh}，突顯{adj_zh}口感。"
                rarity3 = "SSR" if flav_en in {"with Yuzu", "with Lychee", "with Passionfruit"} and adj_en in {"Floral", "Fresh"} else "Rare" if flav_en in {"with Coffee", "with Chocolate"} else "Common"
                drinks.append(DrinkEntry(eng3, zh3, desc3, sp_type, rarity3))

    return drinks


ALL_DRINKS: List[DrinkEntry] = build_drinks()


def current_seasonal_pool() -> List[DrinkEntry]:
    month = datetime.now().month
    for months, pool in SEASONAL_DRINKS.items():
        if month in months:
            return pool
    return []


class Drink(commands.Cog):
    """/drink：隨機為指定對象點一款酒（抽卡式稀有度 + 限定 + 去重）。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.user_recent_draws: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=RECENT_HISTORY_LIMIT))

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
            return f"{icon} {giver} 為 {receiver} 抽到 **{drink.eng} ({drink.zh})**，請享用～"
        return f"{icon} {giver} 為自己抽到 **{drink.eng} ({drink.zh})**，請享用～"

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
    ) -> None:
        rarity = self._pick_rarity()
        drink = self._pick_unique_drink(interaction.user.id, rarity)

        rarity_meta = RARITY_STYLE[drink.rarity]
        header = self._build_header_line(interaction, to, drink)
        limited_text = f"\n🌟 限定：{drink.limited_tag}" if drink.limited_tag else ""

        embed = build_main_menu_embed(interaction.user)
        embed.color = rarity_meta["color"]
        embed.add_field(name="　", value=f"{header}\n➡️ 簡介：{drink.desc}{limited_text}", inline=False)
        embed.add_field(
            name="抽卡結果",
            value=f"{rarity_meta['emoji']} **{rarity_meta['label']}**",
            inline=True,
        )
        embed.add_field(
            name="最近去重",
            value=f"已避開你最近 {RECENT_HISTORY_LIMIT} 杯酒",
            inline=True,
        )
        embed.set_footer(text="Common 78% · Rare 18% · SSR 4%")

        await interaction.response.send_message(
            embed=embed,
            view=build_full_menu_view(interaction),
            file=build_menu_file(),
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="隨機為某人點一款酒")
    @app_commands.describe(to="收酒嘅人")
    async def drink(self, interaction: discord.Interaction, to: discord.Member | None = None):
        await self.do_drink(interaction, to)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
