from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CheerQuote:
    author: str
    english: str
    chinese: str
    category: str = "general"


CHEERS_COOLDOWN_SECONDS = 1800.0
BARTENDER_ATTACHMENT_NAME = "bartender.png"


CHEERS_QUOTES: List[CheerQuote] = [
    CheerQuote(
        author="Michael Jordan",
        english="I always believed that if you put in the work, the results will come.",
        chinese="我一直相信，只要付出努力，成果自然會來。",
        category="sports",
    ),
    CheerQuote(
        author="Bo Jackson",
        english="Set your goals high, and don’t stop till you get there.",
        chinese="把目標訂得高一點，達成前不要停。",
        category="sports",
    ),
    CheerQuote(
        author="Serena Williams",
        english="A champion is defined not by their wins but by how they can recover when they fall.",
        chinese="冠軍不是由勝利定義，而是由跌倒後如何重新站起來定義。",
        category="sports",
    ),
    CheerQuote(
        author="Kobe Bryant",
        english="Everything negative — pressure, challenges — is all an opportunity for me to rise.",
        chinese="所有負面的壓力與挑戰，都是讓我提升自己的機會。",
        category="sports",
    ),
    CheerQuote(
        author="Muhammad Ali",
        english="Don’t count the days; make the days count.",
        chinese="不要只是數日子，要讓每一天都有價值。",
        category="sports",
    ),
    CheerQuote(
        author="Cristiano Ronaldo",
        english="Dreams are not what you see in your sleep; dreams are things which do not let you sleep.",
        chinese="夢想不是睡著時看見的東西，而是讓你睡不著的東西。",
        category="sports",
    ),
    CheerQuote(
        author="Lionel Messi",
        english="You have to fight to reach your dream. You have to sacrifice and work hard for it.",
        chinese="你要為夢想奮鬥，為它犧牲，為它努力。",
        category="sports",
    ),
    CheerQuote(
        author="Usain Bolt",
        english="I trained four years to run nine seconds.",
        chinese="我訓練了四年，只為跑出那九秒。",
        category="sports",
    ),
    CheerQuote(
        author="Stephen Curry",
        english="Success is not an accident. Success is actually a choice.",
        chinese="成功不是偶然，成功其實是一種選擇。",
        category="sports",
    ),
    CheerQuote(
        author="Simone Biles",
        english="I’d rather regret the risks that didn’t work out than the chances I didn’t take.",
        chinese="我寧願後悔失敗的嘗試，也不想後悔從未把握的機會。",
        category="sports",
    ),
    CheerQuote(
        author="Winston Churchill",
        english="Success is not final, failure is not fatal: it is the courage to continue that counts.",
        chinese="成功不是終點，失敗也不是致命；真正重要的是繼續前進的勇氣。",
        category="resilience",
    ),
    CheerQuote(
        author="Nelson Mandela",
        english="It always seems impossible until it is done.",
        chinese="事情在完成之前，看起來總是不可能。",
        category="resilience",
    ),
    CheerQuote(
        author="Maya Angelou",
        english="You may encounter many defeats, but you must not be defeated.",
        chinese="你可能會遭遇很多挫敗，但你不可以被挫敗打倒。",
        category="resilience",
    ),
    CheerQuote(
        author="Theodore Roosevelt",
        english="Believe you can and you’re halfway there.",
        chinese="相信自己做得到，你已經走了一半。",
        category="motivation",
    ),
    CheerQuote(
        author="Henry Ford",
        english="Whether you think you can, or you think you can’t — you’re right.",
        chinese="無論你認為自己做得到，還是做不到，你都是對的。",
        category="mindset",
    ),
    CheerQuote(
        author="Confucius",
        english="It does not matter how slowly you go as long as you do not stop.",
        chinese="走得慢不要緊，最重要是不要停下來。",
        category="persistence",
    ),
    CheerQuote(
        author="Lao Tzu",
        english="A journey of a thousand miles begins with a single step.",
        chinese="千里之行，始於足下。",
        category="persistence",
    ),
    CheerQuote(
        author="Bruce Lee",
        english="Do not pray for an easy life; pray for the strength to endure a difficult one.",
        chinese="不要祈求安逸的人生，要鍛鍊承受困難的力量。",
        category="strength",
    ),
    CheerQuote(
        author="Bruce Lee",
        english="Knowing is not enough; we must apply. Willing is not enough; we must do.",
        chinese="知道還不夠，必須實踐；願意還不夠，必須行動。",
        category="action",
    ),
    CheerQuote(
        author="Steve Jobs",
        english="The only way to do great work is to love what you do.",
        chinese="成就偉大工作的唯一方法，是熱愛你正在做的事。",
        category="work",
    ),
    CheerQuote(
        author="Oprah Winfrey",
        english="The biggest adventure you can take is to live the life of your dreams.",
        chinese="你能展開最大的冒險，就是活出夢想中的人生。",
        category="dream",
    ),
    CheerQuote(
        author="Walt Disney",
        english="All our dreams can come true, if we have the courage to pursue them.",
        chinese="只要有勇氣追尋，所有夢想都有可能成真。",
        category="dream",
    ),
    CheerQuote(
        author="Eleanor Roosevelt",
        english="The future belongs to those who believe in the beauty of their dreams.",
        chinese="未來屬於相信夢想之美的人。",
        category="dream",
    ),
    CheerQuote(
        author="Albert Einstein",
        english="In the middle of difficulty lies opportunity.",
        chinese="困難之中，往往藏著機會。",
        category="resilience",
    ),
    CheerQuote(
        author="Thomas Edison",
        english="I have not failed. I’ve just found 10,000 ways that won’t work.",
        chinese="我沒有失敗，我只是找到了一萬種行不通的方法。",
        category="resilience",
    ),
    CheerQuote(
        author="Vince Lombardi",
        english="Winners never quit and quitters never win.",
        chinese="勝利者不會放棄，放棄者不會勝利。",
        category="persistence",
    ),
    CheerQuote(
        author="Tony Robbins",
        english="The path to success is to take massive, determined action.",
        chinese="通往成功的路，就是果斷而大量地行動。",
        category="action",
    ),
    CheerQuote(
        author="Les Brown",
        english="You are never too old to set another goal or to dream a new dream.",
        chinese="你永遠不會太老，去設定新目標或做一個新夢。",
        category="dream",
    ),
    CheerQuote(
        author="Unknown",
        english="Small steps every day still move you forward.",
        chinese="每天走一小步，也是在向前。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="Rest if you must, but don’t quit.",
        chinese="累了可以休息，但不要放棄。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="You have survived every difficult day so far.",
        chinese="到目前為止，你已經撐過了所有艱難的日子。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="Progress does not need to be loud to be real.",
        chinese="進步不一定要轟烈，真實就已經足夠。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="One more try can change the whole story.",
        chinese="再試一次，可能就會改寫整個故事。",
        category="persistence",
    ),
    CheerQuote(
        author="Unknown",
        english="You do not need to be perfect to be proud of yourself.",
        chinese="你不需要完美，也值得為自己感到驕傲。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="Your pace is still a pace.",
        chinese="你的速度再慢，也仍然是在前進。",
        category="gentle",
    ),
    CheerQuote(
        author="Unknown",
        english="Today’s effort is tomorrow’s confidence.",
        chinese="今天的努力，會成為明天的底氣。",
        category="motivation",
    ),
    CheerQuote(
        author="Unknown",
        english="Keep going. The version of you who started this is still counting on you.",
        chinese="繼續走下去。當初開始的那個你，仍然在相信你。",
        category="persistence",
    ),
    CheerQuote(
        author="Unknown",
        english="You are closer than you think.",
        chinese="你比自己想像中更接近目標。",
        category="motivation",
    ),
]