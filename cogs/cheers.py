from __future__ import annotations
import random
import discord
from discord import app_commands
from discord.ext import commands
import config

# 名人鼓勵語錄（英文、中文、作者原名）
CHEERS_QUOTES: list[tuple[str, str, str]] = [
    (
        "Success is no accident. It is hard work, perseverance, learning, studying, sacrifice and most of all, love of what you are doing.",
        "成功不是偶然的。它是努力、堅持、學習、犧牲，更重要的是你對正在做的事的熱愛。",
        "Pelé",
    ),
    (
        "The more difficult the victory, the greater the happiness in winning.",
        "勝利越艱難，贏得時的喜悅就越大。",
        "Pelé",
    ),
    (
        "Talent wins games, but teamwork and intelligence win championships.",
        "天賦能贏比賽，但團隊合作與智慧才能贏得冠軍。",
        "Michael Jordan",
    ),
    (
        "I've failed over and over and over again in my life and that is why I succeed.",
        "我一生中一次又一次失敗，因此我才成功。",
        "Michael Jordan",
    ),
    (
        "A champion is defined not by their wins, but by how they can recover when they fall.",
        "冠軍的定義不在於勝利多少，而在於跌倒後如何站起來。",
        "Serena Williams",
    ),
    (
        "Don't count the days; make the days count.",
        "不要數著日子過，要讓日子變得有價值。",
        "Muhammad Ali",
    ),
    (
        "It always seems impossible until it's done.",
        "在完成之前，一切看起來都不可能。",
        "Nelson Mandela",
    ),
    (
        "You have to fight to reach your dream. You have to sacrifice and work hard for it.",
        "你必須奮鬥才能達成夢想，為此你得付出犧牲與努力。",
        "Lionel Messi",
    ),
    (
        "Dreams are not what you see in your sleep; dreams are the things which do not let you sleep.",
        "夢想不是你在睡夢中所見，而是那些讓你無法入眠的事物。",
        "Cristiano Ronaldo",
    ),
    (
        "You have to believe in yourself when no one else does—that makes you a winner right there.",
        "即使沒有人相信你，也要相信自己——那一刻你已是贏家。",
        "Venus Williams",
    ),
    (
        "I don't run to see who is the fastest. I run to see who has the most guts.",
        "我跑步不是為了看誰最快，而是看誰最有膽識。",
        "Steve Prefontaine",
    ),
    (
        "If you are afraid of failure, you don't deserve to be successful.",
        "如果你害怕失敗，你就不配成功。",
        "Charles Barkley",
    ),
    (
        "I always believed that if you put in the work, the results will come.",
        "我一直相信，只要付出努力，成果自然會來。",
        "Michael Jordan",
    ),
    (
        "Champions keep playing until they get it right.",
        "冠軍會一直打下去，直到做對為止。",
        "Billie Jean King",
    ),
    (
        "You miss 100% of the shots you don't take.",
        "你不出手，就錯過了百分之百的機會。",
        "Wayne Gretzky",
    ),
    (
        "I don't stop when I'm tired; I stop when I'm done.",
        "我不在疲倦時停下，而是在完成時停下。",
        "David Goggins",
    ),
]

class Cheers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="cheers", description="隨機派一句名人鼓勵語錄（中英對照）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(to="可選：@某人，送上鼓勵")
    async def cheers_cmd(self, inter: discord.Interaction, to: discord.Member | None = None):
        eng, zh, author = random.choice(CHEERS_QUOTES)
        header = f"🎉 給 {to.mention} 的打氣！\n" if to else "🎉 打氣時間！\n"
        msg = (
            header
            + f"**{author}** 說過：\n"
            + f"`{eng}`\n"
            + f"➡️ {zh}"
        )
        await inter.response.send_message(msg)

async def setup(bot: commands.Bot):
    await bot.add_cog(Cheers(bot))
