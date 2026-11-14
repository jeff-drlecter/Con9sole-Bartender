"""Opt-in RSS publisher; RSS_DELIVERY_SOURCES is empty by default."""
from __future__ import annotations

import asyncio
import logging
import json
from pathlib import Path
import os
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.rss_delivery import enabled_sources
from core.rss_digest import DigestConfig, DigestStore, OFFER_LABELS, HK, excerpt, display_link
from datetime import datetime
from core.rss_simulation import scenarios
from core.rss_wording import rss_text
from core.store_sources import StoreNewsStore,epic_url,epic_offers,steam_news,reviewed_steam_offer
from core.rss_preferences import PreferenceStore
from core.rss_personal_ui import PersonalPanel
from core.rss_featured import CHART_URL, parse_chart, verified_game
from core.rss_featured_ui import sections, render_featured
from core.rss_trial import MAX_BYTES, SOURCES, parse_feed
from core.storage_paths import DATA_DIR

log = logging.getLogger(__name__)


class RSSDelivery(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sources = enabled_sources(os.getenv("RSS_DELIVERY_SOURCES", ""))
        config_path = os.getenv("RSS_DIGEST_CONFIG", "")
        data = {}
        if config_path:
            raw = Path(config_path).read_bytes()
            if len(raw) > 65536:
                raise ValueError("digest config exceeds 64 KiB")
            data = json.loads(raw)
        self.digest_config = DigestConfig.from_dict(data)
        self.public_personal = os.getenv("RSS_PERSONAL_PUBLIC", "0") == "1"
        self.store_news = None
        self.store_news_public = os.getenv("STORE_NEWS_PUBLIC", "0") == "1"
        self.store_config = {}
        self.store_backoff = {}
        store_path = os.getenv("STORE_NEWS_CONFIG", "")
        if store_path:
            raw = Path(store_path).read_bytes()
            if len(raw)>65536: raise ValueError("store config too large")
            self.store_config = json.loads(raw)
            if not isinstance(self.store_config,dict) or set(self.store_config)-{"steam_appids","steam_offers"}:
                raise ValueError("invalid store configuration")
            appids = self.store_config.get("steam_appids",[])
            if not isinstance(appids,list) or len(appids)>10 or any(type(a) is not int or a<=0 for a in appids):
                raise ValueError("invalid Steam watched AppIDs")
            offers = self.store_config.get("steam_offers",[])
            if not isinstance(offers,list) or len(offers)>20: raise ValueError("invalid Steam offers")
            for entry in offers:
                reviewed_steam_offer(entry,{},"hk",time.time())
        self.preferences = None
        self.personal_panel = None
        self.panel_checked = False
        self.chart_ready = False
        self.feed_ready = False
        self.store = None
        self.session = None
        self.errors = {}
        self.last_simulation = 0
        self.simulation_lock = asyncio.Lock()

    async def cog_load(self):
        if not self.sources:
            return
        self.store = DigestStore(DATA_DIR / ("rss_simulation.sqlite3" if self.digest_config.simulation else "rss_delivery.sqlite3"))
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
                                            headers={"User-Agent": "Con9sole-Bartender RSS/1.0"},
                                            cookie_jar=aiohttp.DummyCookieJar(), trust_env=False)
        if self.digest_config.simulation or self.public_personal:
            self.preferences = PreferenceStore(DATA_DIR / 'rss_sandbox_preferences.sqlite3')
            self.personal_panel = PersonalPanel(self)
            self.bot.add_view(self.personal_panel)
        if self.preferences:
            self.chart_poll.start()
            if self.store_config:
                self.store_news = StoreNewsStore(DATA_DIR / "store_news.sqlite3")
                self.store_poll.start()
        self.poll.start()
        self.deliver.start()

    async def cog_unload(self):
        if self.personal_panel:
            self.personal_panel.stop()
        self.store_poll.cancel()
        self.chart_poll.cancel()
        self.poll.cancel()
        self.deliver.cancel()
        if self.session:
            await self.session.close()

    def store_news_available(self, interaction):
        return bool(self.store_news is not None and (self.store_news_public or
                    interaction.channel_id == self.digest_config.channel_id))

    def store_news_scope(self, interaction):
        if self.store_news_available(interaction):
            return '商店來源試用：Epic 當期限免、Steam 指定遊戲新聞；Steam 優惠須人工核實。地區可獨立調整；優惠列出上次核對時間，實際資格以帳號商店為準。'
        return '商店來源仍在測試區驗證，暫未加入此處的結果。'

    async def fetch_store_json(self, url):
        from urllib.parse import urlsplit
        from email.utils import parsedate_to_datetime
        origin = urlsplit(url).netloc
        if self.store_backoff.get(origin,0)>time.time():
            raise RuntimeError('store source cooldown')
        async with self.session.get(url,allow_redirects=False) as response:
            if response.status==429:
                value=response.headers.get('Retry-After','1800')
                try: delay=float(value)
                except ValueError:
                    try: delay=parsedate_to_datetime(value).timestamp()-time.time()
                    except (ValueError,TypeError): delay=1800
                self.store_backoff[origin]=time.time()+max(1800,delay)
            response.raise_for_status()
            if response.status!=200: raise ValueError('store redirect or unexpected status')
            raw=bytearray()
            async for chunk in response.content.iter_chunked(16384):
                raw.extend(chunk)
                if len(raw)>MAX_BYTES: raise ValueError('store response too large')
        return json.loads(raw)

    @tasks.loop(minutes=30)
    async def store_poll(self):
        for market in ('hk','tw'):
            bucket='epic:'+market
            try:
                now=time.time()
                rows=epic_offers(await self.fetch_store_json(epic_url(market)),market,now)
                await asyncio.to_thread(self.store_news.replace,bucket,rows,now)
                self.errors.pop(bucket,None)
            except Exception as exc:
                self.errors[bucket]=type(exc).__name__
                log.warning('Store source unavailable: %s %s',bucket,type(exc).__name__)
        appids=set(self.store_config.get('steam_appids',[]))
        appids.update(e['appid'] for e in self.store_config.get('steam_offers',[]))
        for appid in sorted(appids):
            bucket='steam:'+str(appid)
            try:
                data=await self.fetch_store_json(f'https://store.steampowered.com/api/appdetails?appids={appid}&cc=hk&l=tchinese')
                item=data.get(str(appid),{})
                if item.get('success') is not True: raise ValueError('Steam game not available')
                app=item['data']
                if not verified_game(app) or app.get('steam_appid')!=appid: raise ValueError('not the expected base game')
                if appid in self.store_config.get('steam_appids',[]):
                    news=await self.fetch_store_json(f'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={appid}&count=20&maxlength=1500&feeds=steam_community_announcements')
                    now=time.time()
                    rows=steam_news(news,appid,app['name'],now)
                    await asyncio.to_thread(self.store_news.collect_news,bucket,rows,now)
                for market in ('hk','tw'):
                    entries=[e for e in self.store_config.get('steam_offers',[]) if e['appid']==appid]
                    if not entries: continue
                    regional=app
                    if market!='hk':
                        regional=(await self.fetch_store_json(f'https://store.steampowered.com/api/appdetails?appids={appid}&cc={market}&l=tchinese')).get(str(appid),{}).get('data',{})
                    now=time.time()
                    rows=[row for e in entries if (row:=reviewed_steam_offer(e,regional,market,now)) is not None]
                    await asyncio.to_thread(self.store_news.replace,f'steam-offer:{appid}:{market}',rows,now)
                self.errors.pop(bucket,None)
            except Exception as exc:
                self.errors[bucket]=type(exc).__name__
                log.warning('Store source unavailable: %s %s',bucket,type(exc).__name__)

    @tasks.loop(minutes=20)
    async def poll(self):
        for source, url, _ in SOURCES:
            if source not in self.sources:
                continue
            try:
                async with self.session.get(url, max_redirects=5) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError("feed exceeds 2 MiB decompressed limit")
                articles = await asyncio.to_thread(parse_feed, bytes(body))
                await asyncio.to_thread(self.store.ingest, source, articles, time.time())
                self.errors.pop(source, None)
            except Exception as exc:
                self.errors[source] = type(exc).__name__ + ": " + str(exc)[:180]
                log.warning("RSS delivery poll %s: %s", source, self.errors[source])

        self.feed_ready = True

    async def fetch_chart_json(self,url):
        async with self.session.get(url,max_redirects=3) as response:
            response.raise_for_status()
            data=bytearray()
            async for chunk in response.content.iter_chunked(16384):
                data.extend(chunk)
                if len(data)>MAX_BYTES: raise ValueError('chart response too large')
        return json.loads(data)

    @tasks.loop(hours=6)
    async def chart_poll(self):
        try:
            cached=await asyncio.to_thread(self.preferences.get_chart)
            now=time.time()
            if cached and now-cached['fetched']<6*3600: return
            asof,ranks=parse_chart(await self.fetch_chart_json(CHART_URL),now)
            rows=[]
            for row in ranks:
                app=await self.fetch_chart_json(f"https://store.steampowered.com/api/appdetails?appids={row['appid']}&l=tchinese&cc=hk")
                item=app.get(str(row['appid']),{})
                data=item.get('data',{})
                if item.get('success') and verified_game(data):
                    rows.append(dict(row,name=data['name'][:200]))
                if len(rows)==5: break
            if not rows: raise ValueError('no verified game names in chart')
            await asyncio.to_thread(self.preferences.put_chart,dict(asof=asof,fetched=now,rows=rows))
            self.errors.pop('steam_chart',None)
        except Exception as exc:
            self.errors['steam_chart']=type(exc).__name__
            log.warning('Steam chart refresh failed: %s',type(exc).__name__)
        finally:
            self.chart_ready=True

    @staticmethod
    def render(batch, now, label=""):
        reminder = batch['kind'] == 'reminder'
        title = ('⏰ 今日到期提醒' if reminder else '🎮 今日遊戲情報')
        title = (label + '｜' if label else '') + title
        title += '｜' + datetime.fromtimestamp(now, HK).strftime('%m/%d')
        embed = discord.Embed(title=title)
        for article in batch['articles']:
            source = {'ps':'🔵 PS', 'xbox':'🟢 Xbox', '4gamers':'💻 綜合遊戲','steam':'Steam','epic':'Epic'}[article['source']]
            name = source + '｜' + discord.utils.escape_markdown(excerpt(article['title'], 80))
            description = discord.utils.escape_markdown(excerpt(article['summary'], 150))
            offer = article.get('offer')
            if offer:
                description = (f"{OFFER_LABELS[offer['kind']]}｜{discord.utils.escape_markdown(offer['region'])}"
                               f"｜截止 <t:{int(offer['deadline'])}:f>\n" + description)
            if offer and offer.get('checked'):
                description += f"\n商店核對 <t:{int(offer['checked'])}:R>"
            # Encoding brackets prevents external URLs from changing Markdown structure.
            link = '[原文／領取詳情](<' + display_link(article['link']) + '>)'
            value = description[:max(0, 599-len(link))] + '\n' + link
            embed.add_field(name=name[:100], value=value, inline=False)
        embed.set_footer(text='來源內容節錄 · 香港時間 · 非即時逐篇推送')
        return embed

    def target_channel(self):
        channel = self.bot.get_channel(self.digest_config.channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel) or channel.guild.id != config.GUILD_ID or channel.guild.me is None:
            return None
        if self.digest_config.simulation:
            if channel.name != 'rss-模擬區' or channel.permissions_for(channel.guild.default_role).view_channel:
                return None
        permissions = channel.permissions_for(channel.guild.me)
        return channel if permissions.view_channel and permissions.send_messages and permissions.embed_links else None

    @tasks.loop(minutes=1)
    async def deliver(self):
        if not self.digest_config.enabled:
            return
        channel = self.target_channel()
        if channel is None:
            self.errors['digest'] = 'target unavailable, wrong simulation room, public room or missing permissions'
            return
        await self.ensure_personal_panel(channel)
        if self.preferences and self.digest_config.simulation:
            await self.publish_featured(channel)
            local=datetime.fromtimestamp(time.time(),HK)
            # The three-section digest replaces the old long evening card in sandbox.
            if local.hour==19 and local.minute<15: return
        try:
            batch = await asyncio.to_thread(self.store.claim_batch, self.digest_config, self.sources, time.time())
        except Exception:
            log.exception('RSS digest claim failed')
            return
        if batch is None:
            return
        outcome, detail = 'sent', ''
        try:
            message = await channel.send(embed=self.render(batch, time.time(), '🧪 模擬' if self.digest_config.simulation else ''), allowed_mentions=discord.AllowedMentions.none())
            detail = str(message.id)
        except discord.HTTPException as exc:
            outcome = 'retry' if exc.status == 429 else 'uncertain' if exc.status >= 500 else 'failed'
            detail = f'HTTP {exc.status}'
        except Exception as exc:
            outcome, detail = 'uncertain', type(exc).__name__
            log.warning('RSS digest send: %s', detail)
        try:
            await asyncio.to_thread(self.store.finish_batch, batch['slot'], outcome, time.time(), detail)
        except Exception:
            log.exception('RSS digest finalization failed; reserved batch will not be resent')

    @store_poll.before_loop
    @chart_poll.before_loop
    @poll.before_loop
    @deliver.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    def personal_panel_text(self):
        return ('🧪 個人情報測試區\n按「調整偏好」選擇平台、商店、內容類型及關鍵字，再按「我的情報」。\n'
                '結果只對你顯示，偏好會保存。「虛構資料試篩選」只供測試。\n'
                '另有「今日精選」「本月精選」「最近熱門」；熱門採用 Steam 官方榜單。\n'
                '目前不發個人通知，不改正式訂閱。')

    async def ensure_personal_panel(self,channel):
        if self.panel_checked or not self.preferences or not self.digest_config.simulation: return
        self.panel_checked = True
        try:
            if not await asyncio.to_thread(self.preferences.claim_panel,channel.id):
                status=await asyncio.to_thread(self.preferences.panel_status,channel.id)
                if status and status[0]=='posted':
                    message=await channel.fetch_message(status[1])
                    await message.edit(content=self.personal_panel_text(),view=PersonalPanel(self),allowed_mentions=discord.AllowedMentions.none())
                return
            message = await channel.send(self.personal_panel_text(),view=PersonalPanel(self),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.preferences.finish_panel,channel.id,message.id)
            log.info('RSS personal sandbox panel posted: channel=%s message=%s',channel.id,message.id)
        except Exception:
            # Reserve before sending: ambiguous failures must not create repeated panels.
            log.exception('RSS personal panel requires manual verification; admin command can repost')

    async def publish_featured(self,channel):
        if not self.chart_ready or not self.feed_ready: return
        now=time.time()
        local=datetime.fromtimestamp(now,HK)
        previous=await asyncio.to_thread(self.preferences.latest_featured)
        if previous and not (local.hour==19 and local.minute<15): return
        slot=local.date().isoformat()
        try:
            results,snapshot=await sections(self,now)
            if not any(results.values()): return
            if not await asyncio.to_thread(self.preferences.claim_featured,slot): return
            # Keep shared historical snapshots; private button previews never post to chat.
            embeds=[render_featured(kind,rows[:3],now,snapshot,compact=True) for kind,rows in results.items()]
            message=await channel.send('🧪 精選速覽｜今日・本月・最近熱門',embeds=embeds,
                view=PersonalPanel(self),allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(self.preferences.finish_featured,slot,message.id)
            log.info('RSS featured sandbox posted: channel=%s message=%s',channel.id,message.id)
        except Exception:
            log.exception('Featured post requires verification; reserved posts are not automatically resent')

    async def personal_access(self, interaction):
        ready = self.preferences is not None and self.store is not None
        same_guild = interaction.guild_id == config.GUILD_ID
        sandbox = False
        if ready and same_guild and interaction.channel_id == self.digest_config.channel_id:
            target = self.target_channel()
            sandbox = bool(self.digest_config.simulation and target is not None
                           and target.permissions_for(interaction.user).view_channel)
        public = False
        if ready and same_guild and self.public_personal:
            current = getattr(interaction, 'channel', None)
            # No role assignments or permission bypass: use the interaction's actual channel.
            if isinstance(current, discord.TextChannel) and current.guild.id == config.GUILD_ID:
                me = current.guild.me
                public = bool(me is not None and current.permissions_for(interaction.user).view_channel
                              and current.permissions_for(me).view_channel)
        if not (sandbox or public):
            await interaction.response.send_message(rss_text(interaction.user, 'unavailable'), ephemeral=True)
        return bool(sandbox or public)

    async def menu_entry(self, interaction):
        if not await self.personal_access(interaction):
            return
        await interaction.response.send_message(rss_text(interaction.user, 'entry')+'\n'+self.store_news_scope(interaction),
            view=PersonalPanel(self), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def channel_preferences_entry(self, interaction):
        from core.news_channel_ui import open_news_channels
        await open_news_channels(interaction)

    @app_commands.command(name="news_channels", description="選擇接收 PlayStation、Xbox 或 PC 新聞頻道")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def news_channels(self, interaction: discord.Interaction):
        await self.channel_preferences_entry(interaction)

    @app_commands.command(name="news", description="私人查看遊戲情報、精選及個人偏好")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def news(self, interaction: discord.Interaction):
        await self.menu_entry(interaction)

    @app_commands.command(name="rss_personal_panel", description="在 RSS 沙盤張貼個人情報測試入口（管理員）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def personal_entry(self, interaction: discord.Interaction):
        if not (self.digest_config.simulation and interaction.channel_id == self.digest_config.channel_id
                and self.target_channel() is not None):
            await interaction.response.send_message("請在原有私人測試區使用。", ephemeral=True)
            return
        await interaction.response.send_message(self.personal_panel_text(),
            view=PersonalPanel(self), allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="rss_delivery_status", description="查看 RSS 正式派送狀態（管理員）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = ["RSS 摘要：" + ("模擬區運行中" if self.sources and self.digest_config.enabled and self.digest_config.simulation else "已啟用" if self.sources and self.digest_config.enabled else "公開派送關閉"),
                 "來源：" + (", ".join(sorted(self.sources)) or "未啟用收集"),
                 "19:00 沙盤精選速覽；12:30 只提醒晚間前到期嘅已核實優惠。" if self.digest_config.simulation else "19:00 每日摘要（最多 8 條）；12:30 已核實到期提醒。"]
        if self.store_news is not None:
            lines.append('商店來源：'+('公開私人預覽' if self.store_news_public else '限測試區私人預覽'))
            for bucket,checked,count in await asyncio.to_thread(self.store_news.status):
                lines.append(f'{bucket} · {count} 條 · 核對 <t:{int(checked)}:R>')
        if self.preferences:
            lines.append('個人入口：'+str(await asyncio.to_thread(self.preferences.panel_status,self.digest_config.channel_id)))
            lines.append('共用精選：'+str(await asyncio.to_thread(self.preferences.latest_featured)))
        if self.store:
            for source, state, count in await asyncio.to_thread(self.store.report):
                lines.append(f"{source} · {state}: {count}")
            for name, state, attempts in await asyncio.to_thread(self.store.batch_report):
                lines.append(f"{name} · {state} · {attempts} 次嘗試")
        for source, error in self.errors.items():
            lines.append(f"{source}: {error}")
        lines.append("sending／uncertain 要先核對 Discord 訊息；不會自動補發。")
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="rss_digest_preview", description="私人預覽下一份 RSS 摘要，不會發佈或清空佇列")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.store:
            await interaction.followup.send("未啟用 RSS 收集，暫無摘要。", ephemeral=True)
            return
        now = time.time()
        articles = await asyncio.to_thread(self.store.preview, self.digest_config, self.sources, now)
        if not articles:
            await interaction.followup.send("目前冇符合篩選嘅新內容；唔會發空摘要。", ephemeral=True)
            return
        await interaction.followup.send(embed=self.render({'kind':'digest','articles':articles}, now),
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="rss_simulate", description="在私人 RSS 模擬區測試真實新聞版面、篩選及到期提醒")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def simulate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = self.target_channel()
        if not self.digest_config.simulation or channel is None or interaction.channel_id != self.digest_config.channel_id or not self.store:
            await interaction.followup.send("只可喺已設定嘅私人 rss-模擬區使用。",ephemeral=True)
            return
        async with self.simulation_lock:
            now = time.time()
            if now-self.last_simulation < 60:
                await interaction.followup.send("請等一分鐘先再試。",ephemeral=True)
                return
            self.last_simulation = now
            articles = await asyncio.to_thread(self.store.preview,self.digest_config,self.sources,now,snapshot=True)
            if articles:
                await channel.send(embed=self.render({'kind':'digest','articles':articles},now,'🧪 模擬・真實新聞快照'),allowed_mentions=discord.AllowedMentions.none())
            result = await asyncio.to_thread(scenarios,now)
            for kind, at in (('digest',result['evening']),('reminder',result['midday'])):
                await channel.send(embed=self.render(result[kind],at,'🧪 虛構範例・'+('19:00' if kind=='digest' else '12:30')),allowed_mentions=discord.AllowedMentions.none())
            lines = ['🧪 模擬測試結果（虛構資料）']
            lines += [('✅ ' if passed else '❌ ')+name for name,passed in result['checks'].items()]
            lines.append('真實新聞快照：'+str(len(articles))+' 條；模擬不會消耗正式佇列。')
            lines.append('MonitoRSS 繼續派送；未正式取代。')
            await channel.send('\n'.join(lines),allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send('模擬完成，結果已貼喺呢個私人頻道。',ephemeral=True)


async def setup(bot):
    await bot.add_cog(RSSDelivery(bot))
