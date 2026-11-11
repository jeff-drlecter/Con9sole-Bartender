"""Compact, per-viewer Helper overview and owner-bound navigation."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import discord


def bounded_lines(lines,empty,limit=3):
    result=[]
    for line in lines[:limit]:
        if len('\n'.join(result+[line]))>1000: break
        result.append(line)
    return '\n'.join(result) or empty


def render_overview(pending,activity,attention,now,started,demo=False):
    embed=discord.Embed(title='🧭 Helper Overview'+('｜虛構示例' if demo else ''),
        description='先睇需要接應嘅成員，再掃其他活動。' if demo else f'更新 <t:{int(now)}:t> · 只顯示你有權查看嘅遊戲區')
    help_lines=[]
    for row,message in pending[:3]:
        state={'open':'待接應','claimed':'跟進中','handoff':'待轉交'}[row['state']]
        owner=f" · <@{row['owner']}>" if row.get('owner') else ''
        title=discord.utils.escape_markdown(' '.join(message.content.split())[:70]) or '查看原訊息'
        room=discord.utils.escape_markdown(message.channel.name[:35])
        reply='有人回覆' if row['replied'] else '未觀察到回覆'
        help_lines.append(f'**{room} · {state}**{owner}\n[{title}]({message.jump_url}) · <t:{int(row["created"])}:R> · {reply}')
    embed.add_field(name='🆘 需要接應',value=bounded_lines(help_lines,'暫無可顯示嘅疑似求助。'),inline=False)
    fields={f.name:f.value for f in activity.fields}
    chat=fields.get('💬 活躍遊戲區','').splitlines()
    voice=fields.get('🎙️ 而家開緊 call','').splitlines()
    embed.add_field(name='💬 邊區傾緊計｜近 30 分鐘',value=bounded_lines(chat,'暫未觀察到活動。'),inline=False)
    embed.add_field(name='🎙️ 邊區開緊 call',value=bounded_lines(voice,'暫無可查看及加入嘅房間。'),inline=False)
    embed.add_field(name='👋 值得接應',value=bounded_lines(attention,'暫未觀察到新加入成員發言或待接應組隊帖。'),inline=False)
    footer='虛構資料；唔係真實求助或活動。' if demo else '最近活動由 Bot 啟動後觀察 · 求助待人確認 · 未啟用通知'
    if not demo: footer+=' · 觀察起點 '+datetime.fromtimestamp(started,ZoneInfo('Asia/Hong_Kong')).strftime('%H:%M')
    embed.set_footer(text=footer)
    return embed


async def build_overview(cog,i):
    from core.helper_detection_ui import visible_candidates
    now=time.time()
    pending=await visible_candidates(cog,i,limit=3)
    activity=cog.live_embed(i.user)
    attention=cog.attention_lines(i.user,now)
    return render_overview(pending,activity,attention,now,cog.window.started)


async def show_overview(cog,i,edit=False):
    await i.response.defer(ephemeral=True)
    embed=await build_overview(cog,i)
    view=OverviewView(cog,i.user.id)
    if edit:
        await i.edit_original_response(content=None,embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
    else:
        await i.followup.send(embed=embed,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class OwnerView(discord.ui.View):
    def __init__(self,cog,owner):
        super().__init__(timeout=600)
        self.cog,self.owner=cog,owner
    async def interaction_check(self,i):
        if i.user.id!=self.owner:
            await i.response.send_message('請開自己嘅 Overview。',ephemeral=True)
            return False
        return await self.cog.access(i)


class BackToOverview(OwnerView):
    @discord.ui.button(label='返回 Overview',style=discord.ButtonStyle.primary)
    async def back(self,i,button): await show_overview(self.cog,i,edit=True)


class OverviewView(OwnerView):
    @discord.ui.button(label='刷新',style=discord.ButtonStyle.primary,row=0)
    async def refresh(self,i,button): await show_overview(self.cog,i,edit=True)
    @discord.ui.button(label='跟進求助',style=discord.ButtonStyle.success,row=0)
    async def pending(self,i,button):
        from core.helper_detection_ui import show_pending
        await show_pending(self.cog,i)
    @discord.ui.button(label='處理記錄',row=1)
    async def history(self,i,button):
        from core.helper_detection_ui import show_pending
        await show_pending(self.cog,i,closed=True)
    @discord.ui.button(label='完整活動',row=1)
    async def activity(self,i,button):
        await i.response.send_message(embed=self.cog.live_embed(i.user),view=BackToOverview(self.cog,i.user.id),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


def example_overview(now):
    from types import SimpleNamespace
    pending=[(dict(state='open',owner=None,replied=False,created=now-720),SimpleNamespace(content='連唔到朋友個場，點搞？',channel=SimpleNamespace(name='MH 吹水'),jump_url='https://example.com/help'))]
    activity=discord.Embed()
    activity.add_field(name='💬 活躍遊戲區',value='**GTA** · 6 人／18 則\n**Helldivers** · 3 人／7 則')
    activity.add_field(name='🎙️ 而家開緊 call',value='**FC** · 4 人 · 開咗 35 分鐘')
    return render_overview(pending,activity,['**新加入成員** · MH｜近 7 日加入，啱啱發言','**搵隊友** · GTA｜未觀察到直接回覆'],now,now-1800,demo=True)
