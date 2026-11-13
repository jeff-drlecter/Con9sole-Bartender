"""Shared aggregate awareness; source text stays in permission-filtered private views."""
import time
import discord
import config
from core.helper_overview import bounded_lines


def dashboard_embed(cog):
    now=time.time()
    embed=discord.Embed(title='📊 社群動態 Dashboard',
        description=f'更新 <t:{int(now)}:t> · 每 2 分鐘更新\n查看各區活動；需要接應時按下方按鈕。')
    guild=getattr(cog.channel,'guild',None)
    chat,voice=[],[]
    if guild:
        categories=cog.game_categories(guild)
        groups={}
        for cid,count in cog.window.counts(now).items():
            source=guild.get_channel(cid)
            if not source or not cog.pulse_source(source): continue
            group=groups.setdefault(source.category_id,dict(users=set(),messages=0))
            group['users'].update(count['users'])
            group['messages']+=count['messages']
        for cid,count in sorted(groups.items(),key=lambda row:-row[1]['messages'])[:8]:
            category=guild.get_channel(cid)
            if category:
                name=discord.utils.escape_markdown(category.name[:65])
                chat.append(f"**{name}** · {len(count['users'])} 人／{count['messages']} 則")
        rooms={}
        for room in guild.voice_channels:
            if room.category_id not in categories or room.name==config.TEMP_VC_HUB_NAME: continue
            if any(w in room.category.name.casefold() for w in ('admin','管理','hidden','archive','封存','金主','staff','private','私密','測試')): continue
            people={m.id for m in room.members if not m.bot}
            if not people: continue
            group=rooms.setdefault(room.category_id,dict(people=set(),rooms=0))
            group['people'].update(people)
            group['rooms']+=1
        for cid,count in sorted(rooms.items(),key=lambda row:-len(row[1]['people']))[:8]:
            name=discord.utils.escape_markdown(guild.get_channel(cid).name[:65])
            voice.append(f"**{name}** · {count['rooms']} 間／{len(count['people'])} 人")
    embed.add_field(name='💬 文字活動｜近 30 分鐘',value=bounded_lines(chat,'暫未觀察到活動。',8),inline=False)
    embed.add_field(name='🎙️ 目前語音',value=bounded_lines(voice,'暫無活動中的語音房。',8),inline=False)
    embed.set_footer(text='僅顯示已納入的社群遊戲區及公海概況；不轉貼原文或成員名單。個人詳情按原有權限顯示。文字統計自 Bot 啟動後開始。')
    return embed
