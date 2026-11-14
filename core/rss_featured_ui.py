"""Short public highlights, with optional private preference-filtered views."""
import asyncio
import time
from datetime import datetime
import discord
from core.rss_wording import rss_text
from core.rss_digest import HK, excerpt, display_link
from core.rss_featured import highlights, chart_rows, CHART_PAGE

LABELS={'today':'📌 今日精選','month':'🗓️ 本月精選','hot':'🔥 最近熱門'}


def render_featured(kind,rows,now,snapshot=None,compact=False,simulation=True):
    stamp=datetime.fromtimestamp(now,HK).strftime('%m/%d %H:%M')
    embed=discord.Embed(title=LABELS[kind]+'｜'+stamp)
    if kind=='hot':
        header='Steam 官方 Most Played 榜（PC；非全平台排名）\n'
        if snapshot:
            header+=f"榜單日期 <t:{int(snapshot['asof'])}:d> · 擷取 <t:{int(snapshot['fetched'])}:R>\n"
        lines=[f"**#{r['rank']}** [{discord.utils.escape_markdown(excerpt(r['name'],75))}](https://store.steampowered.com/app/{r['appid']}/)" for r in rows]
        footer='\n[官方完整榜單]('+CHART_PAGE+')'
    else:
        header=('香港時間今日新聞／目前有效優惠' if kind=='today' else '本月已收錄新聞／目前有效優惠；未涵蓋全月')+' · 優先會員、更新及關注主題\n'
        lines=[]
        for row in rows:
            title=discord.utils.escape_markdown(excerpt(row['title'],85))
            date=datetime.fromtimestamp(row['published'],HK).strftime('%m/%d')
            line=f"**{row['reason']}** · [{title}](<{display_link(row['link'])}>)"
            if kind=='month': line+=' · '+date
            if row.get('offer'): line+=f" · {row['offer']['region']} · 截止 <t:{int(row['offer']['deadline'])}:f>"
            lines.append(line)
        footer=''
    if not lines: lines=['暫無符合內容。' if kind!='hot' else '暫無符合／有效榜單資料；不以新聞新舊代替熱度。']
    description=header
    budget=1500 if compact else 3500
    for line in lines:
        if len(description)+len(line)+len(footer)+2>budget: break
        description+='\n'+line
    embed.description=description+footer
    embed.set_footer(text=('🧪 測試精選' if simulation else '遊戲情報') + ' · 原文標題節錄 · 不代表免費領取')
    return embed


async def sections(cog,now,pref=None,include_stores=False):
    snapshot=await asyncio.to_thread(cog.preferences.get_chart)
    today=await asyncio.to_thread(highlights,cog.store,cog.digest_config,cog.sources,now,'today',pref)
    month=await asyncio.to_thread(highlights,cog.store,cog.digest_config,cog.sources,now,'month',pref)
    hot=chart_rows(snapshot,cog.digest_config,now,pref)
    if include_stores and cog.store_news is not None:
        from core.store_sources import combine_articles
        from core.rss_preferences import DEFAULT
        today=combine_articles(today+await asyncio.to_thread(cog.store_news.preview,cog.digest_config,pref or DEFAULT,now,'today'),5,cog.digest_config)
        month=combine_articles(month+await asyncio.to_thread(cog.store_news.preview,cog.digest_config,pref or DEFAULT,now,'month'),5,cog.digest_config)
    return {'today':today,'month':month,'hot':hot},snapshot


async def show_featured(cog,interaction,kind):
    await interaction.response.defer(ephemeral=True)
    pref=await asyncio.to_thread(cog.preferences.get,interaction.user.id)
    now=time.time()
    results,snapshot=await sections(cog,now,pref,include_stores=cog.store_news_available(interaction))
    await interaction.followup.send(rss_text(interaction.user, 'featured')+'\n'+cog.store_news_scope(interaction),
        embed=render_featured(kind,results[kind],now,snapshot,simulation=not cog.public_personal),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
