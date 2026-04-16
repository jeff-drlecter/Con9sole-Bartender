from config import GUILD_ID
import random
from typing import List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

# ------------------------------------------------------------
# Con9sole-Bartender: drink.py
# Slash command: /drink to:@member
# 功能：隨機為指定對象點一款「酒名」（英文+中文譯名），以 Embed 顯示
# 資料來源：IBA 77 款官方雞尾酒 + 自動組合 >=1000 種
# 額外功能：附上簡短調製介紹 + 類型對應 icon
# ------------------------------------------------------------

ICON_MAP = {
    "short": "🍸",
    "tropical": "🍹",
    "wine": "🍷",
    "sparkling": "🥂",
    "beer": "🍺",
    "whisky": "🥃",
    "default": "🍸",
}

# IBA 官方 77 款（英文, 中文, 簡介, 類型）
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


def build_drink_names() -> List[Tuple[str, str, str, str]]:
    names: List[Tuple[str, str, str, str]] = []

    names.extend(IBA)

    for adj_en, adj_zh in ADJECTIVES:
        for sp_en, sp_zh, sp_type in SPIRITS:
            eng = f"{adj_en} {sp_en}"
            zh = f"{adj_zh}{sp_zh}"
            desc = f"以{sp_zh}為基酒，呈現{adj_zh}風味。"
            names.append((eng, zh, desc, sp_type))

            for sty_en, sty_zh, sty_type in STYLES:
                eng2 = f"{adj_en} {sp_en} {sty_en}"
                zh2 = f"{adj_zh}{sp_zh}{sty_zh}"
                desc2 = f"以{sp_zh}為基酒，調製成{sty_zh}風格，帶有{adj_zh}特色。"
                names.append((eng2, zh2, desc2, sty_type))

            for flav_en, flav_zh in FLAVORS:
                eng3 = f"{sp_en} {flav_en} ({adj_en})"
                zh3 = f"{adj_zh}{sp_zh}{flav_zh}"
                desc3 = f"以{sp_zh}為基酒，加入{flav_zh}，突顯{adj_zh}口感。"
                names.append((eng3, zh3, desc3, sp_type))

    if len(names) < 1000:
        need = 1000 - len(names)
        names.extend([
            (f"House Recipe #{i+1}", f"特調 #{i+1}", f"特調配方 #{i+1}，隨機風味。", "default")
            for i in range(need)
        ])

    return names[:1000]


DRINKS: List[Tuple[str, str, str, str]] = build_drink_names()


class Drink(commands.Cog):
    """/drink：隨機為指定對象點一款酒（英文+中文+簡介+類型icon）。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def do_drink(
        self,
        interaction: discord.Interaction,
        to: discord.Member | None = None,
    ) -> None:
        """核心邏輯：供 slash command 同 menu button 共用。"""
        eng, zh, desc, typ = random.choice(DRINKS)
        icon = ICON_MAP.get(typ, ICON_MAP["default"])

        giver = interaction.user.mention
        receiver = (to or interaction.user).mention

        if to and to.id != interaction.user.id:
            line = f"{icon} {giver} 為 {receiver} 點咗 **{eng} ({zh})**，請享用～"
        else:
            line = f"{icon} {giver} 為自己點咗 **{eng} ({zh})**，請享用～"

        embed = discord.Embed(
            description=f"{line}\n➡️ 簡介：{desc}",
            color=discord.Color.random(),
        )
        embed.set_author(name="Con9sole-Bartender")

        await interaction.response.send_message(embed=embed)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="drink", description="隨機為某人點一款酒")
    @app_commands.describe(to="收酒嘅人")
    async def drink(self, interaction: discord.Interaction, to: discord.Member):
        await self.do_drink(interaction, to)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drink(bot))
