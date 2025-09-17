from __future__ import annotations
import random
import discord
from discord import app_commands
from discord.ext import commands
import config

# 名人鼓勵語錄（英文、中文、作者原名）— 100 句
CHEERS_QUOTES: list[tuple[str, str, str]] = [
    ("Success is no accident. It is hard work, perseverance, learning, studying, sacrifice and most of all, love of what you are doing.", "成功不是偶然的。它是努力、堅持、學習、犧牲，更重要的是你對正在做的事的熱愛。", "Pelé"),
    ("The more difficult the victory, the greater the happiness in winning.", "勝利越艱難，贏得時的喜悅就越大。", "Pelé"),
    ("Talent wins games, but teamwork and intelligence win championships.", "天賦能贏比賽，但團隊合作與智慧才能贏得冠軍。", "Michael Jordan"),
    ("I've failed over and over and over again in my life and that is why I succeed.", "我一生中一次又一次失敗，因此我才成功。", "Michael Jordan"),
    ("A champion is defined not by their wins, but by how they can recover when they fall.", "冠軍的定義不在於勝利多少，而在於跌倒後如何站起來。", "Serena Williams"),
    ("Don't count the days; make the days count.", "不要數著日子過，要讓日子變得有價值。", "Muhammad Ali"),
    ("It always seems impossible until it's done.", "在完成之前，一切看起來都不可能。", "Nelson Mandela"),
    ("You have to fight to reach your dream. You have to sacrifice and work hard for it.", "你必須奮鬥才能達成夢想，為此你得付出犧牲與努力。", "Lionel Messi"),
    ("Dreams are not what you see in your sleep; dreams are the things which do not let you sleep.", "夢想不是你在睡夢中所見，而是那些讓你無法入眠的事物。", "Cristiano Ronaldo"),
    ("You have to believe in yourself when no one else does—that makes you a winner right there.", "即使沒有人相信你，也要相信自己——那一刻你已是贏家。", "Venus Williams"),
    ("I don't run to see who is the fastest. I run to see who has the most guts.", "我跑步不是為了看誰最快，而是看誰最有膽識。", "Steve Prefontaine"),
    ("If you are afraid of failure, you don't deserve to be successful.", "如果你害怕失敗，你就不配成功。", "Charles Barkley"),
    ("I always believed that if you put in the work, the results will come.", "我一直相信，只要付出努力，成果自然會來。", "Michael Jordan"),
    ("Champions keep playing until they get it right.", "冠軍會一直打下去，直到做對為止。", "Billie Jean King"),
    ("You miss 100% of the shots you don't take.", "你不出手，就錯過了百分之百的機會。", "Wayne Gretzky"),
    ("I don't stop when I'm tired; I stop when I'm done.", "我不在疲倦時停下，而是在完成時停下。", "David Goggins"),
    ("Hard days are the best because that’s when champions are made.", "艱難的日子最寶貴，因為冠軍就是在這時誕生的。", "Gabby Douglas"),
    ("What makes something special is not just what you have to gain, but what you feel there is to lose.", "讓事物變得特別的不是你得到什麼，而是你覺得可能會失去什麼。", "Andre Agassi"),
    ("Push yourself again and again. Don’t give an inch until the final buzzer sounds.", "一再鞭策自己，在終場哨聲響起前不要退讓一步。", "Larry Bird"),
    ("The only way to prove that you’re a good sport is to lose.", "證明你是好運動員的唯一方式就是接受失敗。", "Ernie Banks"),
    ("A trophy carries dust. Memories last forever.", "獎盃會積灰，但回憶會永存。", "Mary Lou Retton"),
    ("Winning isn’t everything, but wanting to win is.", "勝利不是一切，但想贏才是一切。", "Vince Lombardi"),
    ("Adversity causes some men to break; others to break records.", "逆境讓人崩潰，但也讓人破紀錄。", "William Arthur Ward"),
    ("Set your goals high, and don’t stop till you get there.", "把目標訂得高一點，直到達成前都不要停。", "Bo Jackson"),
    ("Gold medals aren’t really made of gold. They’re made of sweat, determination, and guts.", "金牌不是真的用金子造的，而是用汗水、決心和膽識鑄成的。", "Dan Gable"),
    ("I hated every minute of training, but I said, ‘Don’t quit. Suffer now and live the rest of your life as a champion.’", "我討厭每一分鐘的訓練，但我告訴自己：別放棄。現在忍受痛苦，餘生就能以冠軍身份生活。", "Muhammad Ali"),
    ("Age is no barrier. It’s a limitation you put on your mind.", "年齡不是障礙，那只是你自己心裡的限制。", "Jackie Joyner-Kersee"),
    ("Excellence is the gradual result of always striving to do better.", "卓越是持續努力追求更好的一個漸進結果。", "Pat Riley"),
    ("Do not let what you cannot do interfere with what you can do.", "不要讓你做不到的事，妨礙你能做到的事。", "John Wooden"),
    ("It’s not whether you get knocked down; it’s whether you get up.", "被擊倒沒關係，重點是你能否站起來。", "Vince Lombardi"),
    ("I never left the field saying I could have done more to get ready, and that gives me peace of mind.", "我從未離開球場時覺得自己可以做更多準備，這讓我心安。", "Peyton Manning"),
    ("It’s not the will to win that matters—everyone has that. It’s the will to prepare to win that matters.", "重要的不是想贏的意志，每個人都有；而是準備去贏的意志。", "Paul Bryant"),
    ("The difference between the impossible and the possible lies in a man’s determination.", "不可能與可能之間的差別在於一個人的決心。", "Tommy Lasorda"),
    ("Champions are not born; they are made.", "冠軍不是天生的，而是後天造就的。", "Anonymous"),
    ("Run when you can, walk if you have to, crawl if you must; just never give up.", "能跑就跑，能走就走，不行就爬，但絕不放棄。", "Dean Karnazes"),
    ("If you train hard, you’ll not only be hard, you’ll be hard to beat.", "如果你努力訓練，你不僅會變強，還會變得難以擊敗。", "Herschel Walker"),
    ("Victory is in having done your best. If you’ve done your best, you’ve won.", "勝利在於盡力，如果你已經盡力，那你就贏了。", "Bill Bowerman"),
    ("If you don’t have confidence, you’ll always find a way not to win.", "如果你沒有自信，你總會找到理由輸。", "Carl Lewis"),
    ("You can’t put a limit on anything. The more you dream, the farther you get.", "任何事都不能設限，夢想越大，你走得越遠。", "Michael Phelps"),
    ("What you lack in talent can be made up with desire, hustle, and giving 110% all the time.", "缺乏天賦可以用慾望、拼勁和百分之百的投入來補足。", "Don Zimmer"),
    ("The harder the battle, the sweeter the victory.", "戰鬥越艱難，勝利越甜美。", "Les Brown"),
    ("Only he who can see the invisible can do the impossible.", "只有能看見無形之物的人，才能做到不可能之事。", "Frank Gaines"),
    ("Never let the fear of striking out keep you from playing the game.", "不要因為害怕出局，就不敢上場比賽。", "Babe Ruth"),
    ("Obstacles don’t have to stop you. If you run into a wall, don’t turn around and give up. Figure out how to climb it, go through it, or work around it.", "障礙不必讓你停下。如果你遇到牆，不要轉身放棄，要想辦法爬過去、穿過去或繞過去。", "Michael Jordan"),
    ("Pain is temporary. Quitting lasts forever.", "痛苦是短暫的，放棄卻是永遠的。", "Lance Armstrong"),
    ("Do today what others won’t so tomorrow you can do what others can’t.", "今天做別人不願做的事，明天你就能做別人不能做的事。", "Jerry Rice"),
    ("Don’t measure yourself by what you have accomplished, but by what you should have accomplished with your ability.", "不要以你已完成的事來衡量自己，而要以你能力本應完成的事來衡量。", "John Wooden"),
    ("Champions believe in themselves even when no one else does.", "即使沒有人相信，冠軍仍然相信自己。", "Unknown"),
    ("You are never too old to set another goal or to dream a new dream.", "無論年紀多大，都可以再設目標或做新夢。", "C. S. Lewis"),
    ("The future belongs to those who believe in the beauty of their dreams.", "未來屬於相信夢想之美的人。", "Eleanor Roosevelt"),
    ("Our greatest glory is not in never falling, but in rising every time we fall.", "我們最偉大的榮耀不在於從不跌倒，而是每次跌倒後都能再站起來。", "Confucius"),
    ("The only limit to our realization of tomorrow is our doubts of today.", "我們對明日實現的唯一限制，是我們對今日的懷疑。", "Franklin D. Roosevelt"),
    ("Believe you can and you're halfway there.", "相信自己能做到，你就已經成功一半。", "Theodore Roosevelt"),
    ("Start where you are. Use what you have. Do what you can.", "從你所在之處開始，利用你手上所擁有，盡你所能去做。", "Arthur Ashe"),
    ("It does not matter how slowly you go as long as you do not stop.", "只要不停下來，走得多慢都沒關係。", "Confucius"),
    ("The secret of getting ahead is getting started.", "領先的秘密在於開始行動。", "Mark Twain"),
    ("Act as if what you do makes a difference. It does.", "就當你的行動會帶來改變——因為它確實會。", "William James"),
    ("Keep your face always toward the sunshine—and shadows will fall behind you.", "永遠面向陽光，陰影自然落在背後。", "Walt Whitman"),
    ("Everything you've ever wanted is on the other side of fear.", "你曾渴望的一切，都在恐懼的另一邊。", "George Addair"),
    ("Opportunities don't happen. You create them.", "機會不是發生，是你創造出來的。", "Chris Grosser"),
    ("It’s not whether you win or lose, it’s how you play the game.", "重點不在輸贏，而在你如何比賽。", "Grantland Rice"),
    ("The best way to predict the future is to create it.", "預測未來的最佳方式，就是親手創造。", "Peter Drucker"),
    ("If you can dream it, you can do it.", "如果你能夢想到它，你就能做到它。", "Walt Disney"),
    ("Believe in yourself and all that you are. Know that there is something inside you that is greater than any obstacle.", "相信自己，並相信你內在的力量比任何障礙都強。", "Christian D. Larson"),
    ("Perseverance is not a long race; it is many short races one after the other.", "堅持不是一場長跑，而是一場接一場的短跑。", "Walter Elliot"),
    ("Success is walking from failure to failure with no loss of enthusiasm.", "成功就是不斷從失敗走向失敗，卻不失熱情。", "Winston Churchill"),
    ("Courage is not the absence of fear, but the triumph over it.", "勇氣不是沒有恐懼，而是戰勝恐懼。", "Nelson Mandela"),
    ("Do what you can, with what you have, where you are.", "在你的所在，用你所擁有，做你所能做。", "Theodore Roosevelt"),
    ("The harder you work for something, the greater you’ll feel when you achieve it.", "你為某事越努力，達成時的感受就越美好。", "Anonymous"),
    ("It’s not the size of the dog in the fight, it’s the size of the fight in the dog.", "決定勝負的不是狗的體型，而是牠心中的戰意。", "Mark Twain"),
    ("Failure is not the opposite of success; it’s part of success.", "失敗不是成功的反面，而是成功的一部分。", "Arianna Huffington"),
    ("If you want to lift yourself up, lift up someone else.", "如果你想提升自己，先幫助別人。", "Booker T. Washington"),
    ("You are stronger than you think.", "你比自己以為的更強大。", "Anonymous"),
    ("The pain you feel today will be the strength you feel tomorrow.", "你今天感到的痛苦，會成為你明天的力量。", "Anonymous"),
    ("Great things are done by a series of small things brought together.", "偉大的事由一連串小事累積而成。", "Vincent van Gogh"),
    ("What lies behind us and what lies before us are tiny matters compared to what lies within us.", "與我們內在相比，過去與未來皆為小事。", "Ralph Waldo Emerson"),
    ("Don’t wait for opportunity. Create it.", "不要等待機會，創造機會。", "Anonymous"),
    ("It always seems impossible until it's done.", "一切看來不可能，直到它完成為止。", "Nelson Mandela"),
    ("The only place where success comes before work is in the dictionary.", "唯一成功先於努力的地方，是字典裡。", "Vidal Sassoon"),
    ("You don’t have to be great to start, but you have to start to be great.", "開始不必偉大，但你必須開始，才能變得偉大。", "Zig Ziglar"),
    ("Limitations live only in our minds. But if we use our imaginations, our possibilities become limitless.", "限制只存在於我們的心中；善用想像，可能性將無限。", "Jamie Paolinetti"),
    ("Success isn’t always about greatness. It’s about consistency.", "成功不總是關乎偉大，而是關乎持之以恆。", "Dwayne Johnson"),
    ("Little by little, one travels far.", "一點一點地，人就能走得很遠。", "J. R. R. Tolkien"),
    ("Strength doesn’t come from what you can do. It comes from overcoming the things you once thought you couldn’t.", "力量不是來自你能做的事，而是來自你克服曾以為做不到的事。", "Rikki Rogers"),
    ("Doubt kills more dreams than failure ever will.", "懷疑扼殺的夢想，比失敗更多。", "Suzy Kassem"),
    ("Hold the vision, trust the process.", "堅守願景，信任過程。", "Anonymous"),
    ("Make each day your masterpiece.", "讓每一天都成為你的代表作。", "John Wooden"),
    ("It’s never too late to be what you might have been.", "成為你想成為的人，永遠不嫌遲。", "George Eliot"),
    ("Success is the sum of small efforts, repeated day in and day out.", "成功是日復一日重複的小努力之總和。", "Robert Collier"),
    ("Believe in your infinite potential.", "相信你無限的潛能。", "Anonymous"),
    ("Champions are made from something they have deep inside them—a desire, a dream, a vision.", "冠軍來自內心深處的渴望、夢想與願景。", "Muhammad Ali"),
    ("If you want to go fast, go alone. If you want to go far, go together.", "想走快，獨自走；想走遠，一起走。", "African Proverb"),
    ("He who is not courageous enough to take risks will accomplish nothing in life.", "沒有勇氣冒險的人，這一生將一事無成。", "Muhammad Ali"),
    ("Success usually comes to those who are too busy to be looking for it.", "成功通常降臨在忙於行動、無暇尋找成功的人身上。", "Henry David Thoreau"),
    ("Perfection is not attainable, but if we chase perfection we can catch excellence.", "完美不可及，但若追求完美，我們可抓住卓越。", "Vince Lombardi"),
    ("Do one thing every day that scares you.", "每天做一件讓你害怕的事。", "Eleanor Roosevelt"),
    ("Great things never come from comfort zones.", "偉大不會來自舒適圈。", "Anonymous"),
    ("Your limitation—it’s only your imagination.", "你的限制，只是你的想像。", "Anonymous"),
    ("Sometimes we’re tested not to show our weaknesses, but to discover our strengths.", "有時考驗不是為了顯示弱點，而是為了發現力量。", "Anonymous"),
    ("Don’t wish it were easier; wish you were better.", "不要希望事情更容易，願你變得更強。", "Jim Rohn"),
    ("Work hard in silence; let success make the noise.", "默默努力，讓成功發出聲音。", "Anonymous"),
    ("If you’re going through hell, keep going.", "如果你正在經歷地獄，繼續走下去。", "Winston Churchill"),
    ("You were born to be a player. You were meant to be here. This moment is yours.", "你生來就是選手，你注定在此處，這一刻屬於你。", "Herb Brooks"),
    ("Champions act like champions before they are champions.", "在成為冠軍之前，冠軍就有冠軍的作風。", "Bill Walsh"),
    ("There may be people that have more talent than you, but there's no excuse for anyone to work harder than you do.", "有人天賦勝你，但沒有人有藉口比你更少努力。", "Derek Jeter"),
    ("I became a good pitcher when I stopped trying to make them miss the ball and started trying to make them hit it.", "當我不再試圖讓他們揮空，而是讓他們打到球時，我成為了好投手。", "Sandy Koufax"),
    ("Sports do not build character. They reveal it.", "運動不塑造性格，它揭示性格。", "Heywood Broun"),
    ("The man who has no imagination has no wings.", "沒有想像力的人，就沒有翅膀。", "Muhammad Ali"),
    ("Success is where preparation and opportunity meet.", "成功是準備與機會相遇之處。", "Bobby Unser"),
    ("The will to win is important, but the will to prepare is vital.", "求勝意志重要，但準備的意志更為關鍵。", "Joe Paterno"),
    ("Champions aren’t made in gyms. Champions are made from something they have deep inside them.", "冠軍不是在健身房被造就的，而是來自內心深處的某種力量。", "Muhammad Ali"),
    ("You just can’t beat the person who never gives up.", "你永遠打不倒一個從不放棄的人。", "Babe Ruth"),
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
