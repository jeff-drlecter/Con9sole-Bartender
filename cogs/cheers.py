from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.menu import build_full_menu_view, build_main_menu_embed, build_menu_file


CHEERS_QUOTES: list[tuple[str, str, str]] = [
    ("Success is no accident. It is hard work, perseverance, learning, studying, sacrifice and most of all, love of what you are doing.", "成功不是偶然的。它是努力、堅持、學習、犧牲，更重要的是你對正在做的事的熱愛。", "Pelé"),
    ("The more difficult the victory, the greater the happiness in winning.", "勝利越艱難，贏得時的喜悅就越大。", "Pelé"),
    ("Talent wins games, but teamwork and intelligence win championships.", "天賦能贏比賽，但團隊合作與智慧才能贏得冠軍。", "Michael Jordan"),
    ("I've failed over and over and over again in my life and that is why I succeed.", "我一生中一次又一次失敗，因此我才成功。", "Michael Jordan"),
    ("Obstacles don’t have to stop you. If you run into a wall, figure out how to climb it, go through it, or work around it.", "障礙不必讓你停下。撞到牆，就想辦法爬過去、穿過去或繞過去。", "Michael Jordan"),
    ("I always believed that if you put in the work, the results will come.", "我一直相信，只要付出努力，成果自然會來。", "Michael Jordan"),
    ("Champions keep playing until they get it right.", "冠軍會一直打下去，直到做對為止。", "Billie Jean King"),
    ("You miss 100% of the shots you don’t take.", "你不出手，就錯過了百分之百的機會。", "Wayne Gretzky"),
    ("You can’t put a limit on anything. The more you dream, the farther you get.", "任何事都不能設限；夢想越大，走得越遠。", "Michael Phelps"),
    ("I don’t stop when I’m tired; I stop when I’m done.", "我不在疲倦時停下，而是在完成時停下。", "David Goggins"),
    ("Hard days are the best because that’s when champions are made.", "艱難的日子最寶貴，冠軍在此誕生。", "Gabby Douglas"),
    ("Set your goals high, and don’t stop till you get there.", "把目標訂得高一點，達成前不要停。", "Bo Jackson"),
    ("Gold medals aren’t really made of gold. They’re made of sweat, determination, and guts.", "金牌不是金子造的，而是汗水、決心與膽識鑄成的。", "Dan Gable"),
    ("Age is no barrier. It’s a limitation you put on your mind.", "年齡不是障礙，那只是你的心理限制。", "Jackie Joyner-Kersee"),
    ("Excellence is the gradual result of always striving to do better.", "卓越是持續努力追求更好的漸進結果。", "Pat Riley"),
    ("Do not let what you cannot do interfere with what you can do.", "不要讓你做不到的事，妨礙你能做到的事。", "John Wooden"),
    ("It’s not whether you get knocked down; it’s whether you get up.", "被擊倒沒關係，重點是能否站起來。", "Vince Lombardi"),
    ("I never left the field saying I could have done more to get ready, and that gives me peace of mind.", "我從不覺得準備不足離場，這讓我安心。", "Peyton Manning"),
    ("The difference between the impossible and the possible lies in a man’s determination.", "不可能與可能的差別在於決心。", "Tommy Lasorda"),
    ("Run when you can, walk if you have to, crawl if you must; just never give up.", "能跑就跑，能走就走，不行就爬，但絕不放棄。", "Dean Karnazes"),
    ("If you train hard, you’ll not only be hard, you’ll be hard to beat.", "努力訓練，不只變強，更難被擊敗。", "Herschel Walker"),
    ("Victory is in having done your best. If you’ve done your best, you’ve won.", "勝利在於盡力。若你盡了力，你就贏了。", "Bill Bowerman"),
    ("If you don’t have confidence, you’ll always find a way not to win.", "沒有自信，你總會找到輸的理由。", "Carl Lewis"),
    ("What you lack in talent can be made up with desire, hustle, and giving 110% all the time.", "缺天賦可用渴望、拼勁和 110% 投入補足。", "Don Zimmer"),
    ("The harder the battle, the sweeter the victory.", "戰鬥越艱難，勝利越甜美。", "Les Brown"),
    ("Never let the fear of striking out keep you from playing the game.", "別因害怕出局而不上場。", "Babe Ruth"),
    ("Pain is temporary. Quitting lasts forever.", "痛苦是短暫的；放棄是永遠的。", "Lance Armstrong"),
    ("Do today what others won’t so tomorrow you can do what others can’t.", "今天做別人不願做的事，明天你就能做別人不能做的事。", "Jerry Rice"),
    ("The will to win is important, but the will to prepare is vital.", "求勝重要，準備更關鍵。", "Joe Paterno"),
    ("You just can’t beat the person who never gives up.", "你永遠打不倒一個從不放棄的人。", "Babe Ruth"),
    ("Champions act like champions before they are champions.", "在成為冠軍之前，先以冠軍的方式行事。", "Bill Walsh"),
    ("There may be people that have more talent than you, but there’s no excuse for anyone to work harder than you do.", "有人天賦勝你，但冇人有藉口比你更少努力。", "Derek Jeter"),
    ("I became a good pitcher when I stopped trying to make them miss the ball and started trying to make them hit it.", "當我改變策略讓他們打到球，我成為了更好的投手。", "Sandy Koufax"),
    ("Sports do not build character. They reveal it.", "運動不塑造性格，它揭示性格。", "Heywood Broun"),
    ("Success is where preparation and opportunity meet.", "成功是準備與機會的交會點。", "Bobby Unser"),
    ("Perfection is not attainable, but if we chase perfection we can catch excellence.", "完美不可及，但追求完美能抓住卓越。", "Vince Lombardi"),
    ("I hated every minute of training, but I said, ‘Don’t quit. Suffer now and live the rest of your life as a champion.’", "我討厭訓練，但我告訴自己：別放棄。現在吃苦，餘生以冠軍之名。", "Muhammad Ali"),
    ("The man who has no imagination has no wings.", "沒有想像力就沒有翅膀。", "Muhammad Ali"),
    ("He who is not courageous enough to take risks will accomplish nothing in life.", "不敢冒險，終將一事無成。", "Muhammad Ali"),
    ("I don’t have time to worry about what I’m going to do. I just go out and play.", "我冇時間擔心要做咩；我只係上場。", "LeBron James"),
    ("You have to fight to reach your dream. You have to sacrifice and work hard for it.", "為夢想而戰，付出與努力是必須。", "Lionel Messi"),
    ("Dreams are not what you see in your sleep; dreams are the things which do not let you sleep.", "夢想不是睡夢所見，而是令你夜不能寐的事。", "Cristiano Ronaldo"),
    ("Champions are made from something they have deep inside them—a desire, a dream, a vision.", "冠軍來自內心深處的渴望、夢想與願景。", "Muhammad Ali"),
    ("It always seems impossible until it’s done.", "在完成之前，一切看起來都不可能。", "Nelson Mandela"),
    ("Courage is not the absence of fear, but the triumph over it.", "勇氣不是沒有恐懼，而是戰勝恐懼。", "Nelson Mandela"),
    ("The secret of getting ahead is getting started.", "領先的秘密在於開始行動。", "Mark Twain"),
    ("It’s not the size of the dog in the fight, it’s the size of the fight in the dog.", "決定勝負的不是狗的體型，而是牠心中的戰意。", "Mark Twain"),
    ("Keep your face always toward the sunshine—and shadows will fall behind you.", "永遠面向陽光，陰影自然落在背後。", "Walt Whitman"),
    ("If you can dream it, you can do it.", "如果你能夢想到它，你就能做到它。", "Walt Disney"),
    ("The only limit to our realization of tomorrow is our doubts of today.", "實現明日的唯一限制，是我們今日的懷疑。", "Franklin D. Roosevelt"),
    ("Believe you can and you’re halfway there.", "相信自己能做到，你就已成功一半。", "Theodore Roosevelt"),
    ("Do what you can, with what you have, where you are.", "在你所在，用你所有，做你所能。", "Theodore Roosevelt"),
    ("Start where you are. Use what you have. Do what you can.", "從你所在之處開始，利用你所有，盡你所能。", "Arthur Ashe"),
    ("Act as if what you do makes a difference. It does.", "就當你的行動會帶來改變——因為它確實會。", "William James"),
    ("Opportunities don’t happen. You create them.", "機會不是發生；是你創造。", "Chris Grosser"),
    ("The best way to predict the future is to create it.", "預測未來的最佳方法是親手創造。", "Peter Drucker"),
    ("Success is walking from failure to failure with no loss of enthusiasm.", "成功是不失熱情地在失敗間前行。", "Winston Churchill"),
    ("If you’re going through hell, keep going.", "若你正在經歷地獄，繼續走。", "Winston Churchill"),
    ("Failure is not the opposite of success; it’s part of success.", "失敗不是成功的反面，而是成功的一部分。", "Arianna Huffington"),
    ("Everything you’ve ever wanted is on the other side of fear.", "你渴望的一切，都在恐懼的另一邊。", "George Addair"),
    ("Great things are done by a series of small things brought together.", "偉大的事由一連串小事累積而成。", "Vincent van Gogh"),
    ("What lies behind us and what lies before us are tiny matters compared to what lies within us.", "與我們內在相比，過去與未來皆為小事。", "Ralph Waldo Emerson"),
    ("You are never too old to set another goal or to dream a new dream.", "無論年紀多大，都可再設目標或做新夢。", "C. S. Lewis"),
    ("The future belongs to those who believe in the beauty of their dreams.", "未來屬於相信夢想之美的人。", "Eleanor Roosevelt"),
    ("Make each day your masterpiece.", "讓每一天都成為你的代表作。", "John Wooden"),
    ("It’s never too late to be what you might have been.", "成為你想成為的人，永遠不嫌遲。", "George Eliot"),
    ("Success is the sum of small efforts, repeated day in and day out.", "成功是日復一日小努力的總和。", "Robert Collier"),
    ("Do one thing every day that scares you.", "每天做一件讓你害怕的事。", "Eleanor Roosevelt"),
    ("Work hard in silence; let success make the noise.", "默默努力，讓成功發聲。", "Frank Ocean"),
    ("Don’t wish it were easier; wish you were better.", "別求更容易；求自己更強。", "Jim Rohn"),
    ("Little by little, one travels far.", "一點一點地，人能走得很遠。", "J. R. R. Tolkien"),
    ("Doubt kills more dreams than failure ever will.", "懷疑扼殺的夢想比失敗更多。", "Suzy Kassem"),
    ("Hold the vision, trust the process.", "堅守願景，信任過程。", "Jon Gordon"),
    ("Success usually comes to those who are too busy to be looking for it.", "成功往往屬於忙於行動、無暇找成功的人。", "Henry David Thoreau"),
    ("Perseverance is not a long race; it is many short races one after the other.", "堅持不是一場長跑，而是一場接一場的短跑。", "Walter Elliot"),
    ("Your limitation—it’s only your imagination.", "你的限制，只是想像。", "Tony Robbins"),
    ("Great things never come from comfort zones.", "偉大不會來自舒適圈。", "Roy T. Bennett"),
    ("Sometimes we’re tested not to show our weaknesses, but to discover our strengths.", "考驗不是為顯示弱點，而是為發現力量。", "Les Brown"),
    ("Believe in yourself and all that you are.", "相信自己與你的一切。", "Christian D. Larson"),
    ("The only place where success comes before work is in the dictionary.", "成功先於努力的唯一地方，是字典。", "Vidal Sassoon"),
    ("You don’t have to be great to start, but you have to start to be great.", "開始不必偉大，但要開始才會偉大。", "Zig Ziglar"),
    ("Limitations live only in our minds. But if we use our imaginations, our possibilities become limitless.", "限制只在心中；善用想像，可能性無限。", "Jamie Paolinetti"),
    ("Success isn’t always about greatness. It’s about consistency.", "成功不總是關乎偉大，而是關乎持之以恆。", "Dwayne Johnson"),
    ("Strength doesn’t come from what you can do. It comes from overcoming the things you once thought you couldn’t.", "力量不是來自你能做的事，而是克服你以為做不到的事。", "Rikki Rogers"),
    ("Believe in your infinite potential.", "相信你無限的潛能。", "Stephen R. Covey"),
    ("If you want to lift yourself up, lift up someone else.", "想提升自己，先扶起他人。", "Booker T. Washington"),
    ("Success is the sum of details.", "成功是細節的總和。", "Harvey S. Firestone"),
    ("Genius is 1% inspiration and 99% perspiration.", "天才是 1% 靈感加 99% 汗水。", "Thomas A. Edison"),
    ("I have not failed. I’ve just found 10,000 ways that won’t work.", "我沒有失敗，我只是找到了一萬種行不通的方法。", "Thomas A. Edison"),
    ("Whether you think you can, or you think you can’t—you’re right.", "無論你覺得能或不能——你都對。", "Henry Ford"),
    ("Quality means doing it right when no one is looking.", "品質是無人注視時仍把事做對。", "Henry Ford"),
    ("Stay hungry, stay foolish.", "求知若飢，虛懷若愚。", "Steve Jobs"),
    ("The people who are crazy enough to think they can change the world are the ones who do.", "瘋狂到相信能改變世界的人，往往真的做到了。", "Steve Jobs"),
    ("If opportunity doesn’t knock, build a door.", "若機會不敲門，就造一扇門。", "Milton Berle"),
    ("Do or do not. There is no try.", "要做就做，沒有嘗試。", "Yoda"),
    ("The journey of a thousand miles begins with a single step.", "千里之行，始於足下。", "Laozi"),
    ("Everything has beauty, but not everyone sees it.", "萬物皆有美，但不是人人都看見。", "Confucius"),
    ("We are what we repeatedly do. Excellence, then, is not an act, but a habit.", "我們反覆做什麼，就成為什麼；卓越不是行為，而是習慣。", "Aristotle"),
    ("Happiness depends upon ourselves.", "幸福取決於我們自己。", "Aristotle"),
    ("The only true wisdom is in knowing you know nothing.", "真正的智慧在於知道自己一無所知。", "Socrates"),
    ("Be the change that you wish to see in the world.", "成為你想在世界上看見的改變。", "Mahatma Gandhi"),
    ("Live as if you were to die tomorrow. Learn as if you were to live forever.", "像明天就會死去般地生活，像永遠活著般地學習。", "Mahatma Gandhi"),
    ("Not all those who wander are lost.", "徘徊之人未必迷失。", "J. R. R. Tolkien"),
    ("It is never too late to give up your prejudices.", "放下偏見永遠不嫌遲。", "Henry David Thoreau"),
    ("The successful warrior is the average man, with laser-like focus.", "成功的戰士其實是普通人，但擁有雷射般的專注。", "Bruce Lee"),
    ("Absorb what is useful, discard what is not, add what is uniquely your own.", "吸收有用，剔除無用，加入屬於你的獨特。", "Bruce Lee"),
    ("The key to immortality is first living a life worth remembering.", "通往不朽的關鍵，是先活出值得被記住的人生。", "Bruce Lee"),
    ("Perseverance, secret of all triumphs.", "堅持，是所有勝利的祕密。", "Victor Hugo"),
    ("Even the darkest night will end and the sun will rise.", "最黑暗的夜也會過去，太陽終會升起。", "Victor Hugo"),
    ("Hope is a waking dream.", "希望是醒著的夢。", "Aristotle"),
    ("Fortune favors the bold.", "幸運偏愛勇者。", "Virgil"),
    ("He who has a why to live can bear almost any how.", "知道為什麼而活的人，幾乎可以承受任何生活方式。", "Friedrich Nietzsche"),
    ("We are what we think.", "我們即是我們所想。", "Buddha"),
]

CHEERS_COOLDOWN_SECONDS = 30.0
CHEERS_USER_COOLDOWNS: dict[int, float] = {}


def get_cheers_retry_after(user_id: int) -> float:
    last_used = CHEERS_USER_COOLDOWNS.get(user_id, 0.0)
    elapsed = time.time() - last_used
    retry_after = CHEERS_COOLDOWN_SECONDS - elapsed
    return retry_after if retry_after > 0 else 0.0


def touch_cheers_cooldown(user_id: int) -> None:
    CHEERS_USER_COOLDOWNS[user_id] = time.time()


class Cheers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _enforce_cheers_cooldown(self, inter: discord.Interaction) -> bool:
        retry_after = get_cheers_retry_after(inter.user.id)
        if retry_after > 0:
            message = f"⏳ 請等 {retry_after:.1f} 秒後再使用打氣時間。"
            if inter.response.is_done():
                await inter.followup.send(message, ephemeral=True)
            else:
                await inter.response.send_message(message, ephemeral=True)
            return False

        touch_cheers_cooldown(inter.user.id)
        return True

    async def do_cheers(
        self,
        inter: discord.Interaction,
        to: discord.Member | None = None,
        *,
        enforce_cooldown: bool = True,
    ) -> None:
        if enforce_cooldown:
            ok = await self._enforce_cheers_cooldown(inter)
            if not ok:
                return

        eng, zh, author = random.choice(CHEERS_QUOTES)

        if to:
            result_desc = f"🎉 給 {to.mention} 的打氣！\n\n**{author} 講過：**"
        else:
            result_desc = f"{inter.user.mention} 的打氣時間！ 🎉\n\n**{author} 講過：**"

        embed = build_main_menu_embed(inter.user)
        embed.color = 0x57F287
        embed.add_field(name="　", value=result_desc, inline=False)
        embed.add_field(name="English", value=f"💬 {eng}", inline=False)
        embed.add_field(name="中文", value=f"➡️ {zh}", inline=False)
        embed.set_footer(text="Con9sole-Bartender Cheers")
        embed.timestamp = discord.utils.utcnow()

        if inter.response.is_done():
            await inter.followup.send(
                embed=embed,
                view=build_full_menu_view(inter),
                file=build_menu_file(),
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                embed=embed,
                view=build_full_menu_view(inter),
                file=build_menu_file(),
                ephemeral=True,
            )

    @app_commands.command(name="cheers", description="隨機派一句名人鼓勵語錄（中英對照，Embed）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(to="可選：@某人，送上鼓勵")
    async def cheers_cmd(
        self,
        inter: discord.Interaction,
        to: discord.Member | None = None,
    ) -> None:
        await self.do_cheers(inter, to, enforce_cooldown=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cheers(bot))
