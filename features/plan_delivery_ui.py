"""Owner-bound preview and settings for the existing plan flow."""
import discord
import config
from core.ui import SafeView, SafeModal
from features.language_preferences import language
from features.plan_delivery import options


def text(member, neutral, hk):
    return hk if language(member) == 'hk' else neutral


def summary(member, data, settings):
    safe = lambda s: discord.utils.escape_mentions(discord.utils.escape_markdown(str(s)))
    when = text(member, '現在玩', '而家玩') if data.get('instant') else f"<t:{int(data['start'])}:F>"
    cap = '不限' if data['capacity'] is None else str(data['capacity'])
    event = (f"{settings['minimum']} 人成局，達標後自動建立活動（需保持原頻道可見範圍）。"
             if settings['auto_event'] else '不自動建立活動。')
    if language(member) == 'hk':
        event = (f"{settings['minimum']} 人成局，夠人就自動建立活動（要保持原頻道可見範圍）。"
                 if settings['auto_event'] else '唔自動建立活動。')
    notice = text(member, '開啟', '開啟') if settings['host_notices'] else text(member, '關閉', '關閉')
    return (f"🎮 **{safe(data['game'])}** · {when}\n{safe(data['mode']) or '平台／模式未填'}\n"
            f"原有 {data['party']} 人 · 最高 {cap} 人\n{event}\n"
            + text(member, f"有人報名時提醒我：{notice}（原頻道短訊息，其他有權限成員可見）。\n",
                   f"有人報名時提我：{notice}（原頻道短訊息，其他有權限成員睇到）。\n")
            + text(member, '原有隊友不用重複報名；報名不等於到場。', '原有隊友唔使重複報名；報名唔等於到場。'))


class Draft(SafeView):
    def __init__(self, cog, channel, owner, data, settings=None):
        super().__init__(timeout=180)
        self.cog, self.channel, self.owner = cog, channel, owner
        self.data = dict(data)
        self.assembly_host = None if data.get('instant') else True
        if self.assembly_host is None:
            self.remove_item(self.assembly)
        self.settings = settings or options(data['party'], data['capacity'], instant=data.get('instant', False))
        self.used = False
        self.auto.disabled = bool(data.get('instant') or self.settings['minimum'] is None)
        self.publish.label = text(owner, '確認發起', '確認發起')
        self.notice.label = text(owner, '切換報名提醒', '切換報名提醒')

    def summary(self):
        preview = summary(self.owner, self.data, self.settings)
        if self.assembly_host is None:
            return preview
        enabled = '開啟' if self.assembly_host else '關閉'
        return preview + '\n' + text(self.owner,
            f'預約時間到及隊友催開局時，在原頻道 @ 我：{enabled}。',
            f'夠鐘同隊友催開局時，喺原頻道 @ 我：{enabled}。')

    @discord.ui.button(label='切換集合提醒', row=1)
    async def assembly(self, i, button):
        if self.assembly_host is not None and await self.authorize_update(i):
            self.assembly_host = not self.assembly_host
            await i.edit_original_response(content=self.summary(), view=self)

    async def interaction_check(self, i):
        # Discord calls this before the callback. Do not perform REST reads here:
        # modal buttons need their initial response, and cancel only closes a draft.
        if (i.user.id != self.owner.id or self.used
                or i.guild is None or i.guild.id != config.GUILD_ID):
            await i.response.send_message(text(i.user, '草稿已關閉或不屬於你。', '草稿已關閉或者唔屬於你。'), ephemeral=True)
            return False
        return True

    async def authorize_update(self, i):
        from features.plan_services import fresh_source, AccessError
        if not await self.interaction_check(i):
            return False
        await i.response.defer(ephemeral=True)
        try:
            member, _ = await fresh_source(i.guild, i.user.id, self.channel.id)
            if self.used:
                await i.followup.send('草稿已關閉。', ephemeral=True)
                return False
            self.owner = member
            return True
        except (AccessError, discord.HTTPException, OSError):
            await i.followup.send(text(i.user, '無法核對原頻道，草稿未發起。', '核對唔到原頻道，草稿未發起。'), ephemeral=True)
            return False

    @discord.ui.button(label='確認發起', style=discord.ButtonStyle.success)
    async def publish(self, i, button):
        if not await self.interaction_check(i):
            return
        self.used = True
        from cogs.squad_plans import PlanForm
        from datetime import datetime
        from features.squad_plans import HK
        seed = dict(game=self.data['game'], mode=self.data['mode'], party=self.data['party'],
                    missing='' if self.data['capacity'] is None else self.data['capacity'] - self.data['party'])
        if not self.data.get('instant'):
            seed['start'] = datetime.fromtimestamp(self.data['start'], HK).strftime('%Y-%m-%d %H:%M')
        form = PlanForm(self.cog, self.channel, instant=self.data.get('instant', False), seed=seed,
                        confirmed=True, delivery_options=self.settings, assembly_host=self.assembly_host)
        await form.on_submit(i)

    @discord.ui.button(label='成局／最高人數')
    async def numbers(self, i, button):
        if await self.interaction_check(i):
            await i.response.send_modal(Numbers(self, i.user))

    @discord.ui.button(label='切換自動活動')
    async def auto(self, i, button):
        if not await self.authorize_update(i):
            return
        if not self.data.get('instant') and self.settings['minimum'] is not None:
            self.settings['auto_event'] = not self.settings['auto_event']
        await i.edit_original_response(content=self.summary(), view=self)

    @discord.ui.button(label='切換報名提醒')
    async def notice(self, i, button):
        if not await self.authorize_update(i):
            return
        self.settings['host_notices'] = not self.settings['host_notices']
        await i.edit_original_response(content=self.summary(), view=self)

    @discord.ui.button(label='取消', row=1)
    async def cancel(self, i, button):
        if not await self.interaction_check(i):
            return
        self.used = True
        await i.response.edit_message(content='草稿已取消。', view=None)


class Numbers(SafeModal):
    def __init__(self, view, member):
        super().__init__(title=text(member, '成局／最高人數', '成局／最高人數'))
        self.view = view
        self.minimum = discord.ui.TextInput(label='成局人數（留空停用活動）', required=False,
            default=str(view.settings['minimum']) if view.settings['minimum'] else '', max_length=3)
        self.capacity = discord.ui.TextInput(label='最高人數（留空不限）', required=False,
            default=str(view.data['capacity']) if view.data['capacity'] else '', max_length=3)
        self.add_item(self.minimum); self.add_item(self.capacity)
    async def on_submit(self, i):
        if not await self.view.authorize_update(i):
            return
        v = self.view
        try:
            minimum = int(self.minimum.value) if self.minimum.value.strip() else None
            capacity = int(self.capacity.value) if self.capacity.value.strip() else None
            if capacity is not None and not v.data['party'] < capacity <= v.data['party'] + 99:
                raise ValueError('最高人數須大於原有人數，並最多多 99 人。')
            settings = options(v.data['party'], capacity, instant=v.data.get('instant', False),
                minimum=minimum, auto=bool(minimum and v.settings['auto_event'] and not v.data.get('instant')),
                notices=v.settings['host_notices'])
        except ValueError as exc:
            await i.followup.send(str(exc), ephemeral=True); return
        v.data['capacity'], v.settings = capacity, settings
        v.auto.disabled = bool(v.data.get('instant') or minimum is None)
        await i.edit_original_response(content=v.summary(), view=v)


class Settings(SafeView):
    def __init__(self, cog, plan, member):
        super().__init__(timeout=180)
        self.cog, self.key, self.owner = cog, plan['id'], member.id
        self.revision = plan.get('revision', 0)
        self.settings = dict(plan.get('delivery', {}).get('settings') or
                             options(plan['party'], plan['capacity'], instant=plan.get('instant', False), auto=False, notices=False))
        self.member = member
        self.auto.disabled = bool(plan.get('instant') or self.settings['minimum'] is None)
    async def interaction_check(self, i):
        p = self.cog.book.get(self.key)
        if (i.user.id != self.owner or not p or p['owner'] != self.owner
                or i.guild_id != p['guild']):
            await i.response.send_message(text(i.user, '請開啟自己的約局設定。', '請開啟自己嘅約局設定。'), ephemeral=True); return False
        if p.get('revision', 0) != self.revision:
            await i.response.send_message(text(i.user, '約局或權限已變更，請從原卡重新開啟。', '約局或者權限已變，請喺原卡重新開啟。'), ephemeral=True); return False
        return True
    def summary(self, p):
        e = p.get('delivery', {}).get('event', {})
        labels = dict(blocked='來源可見範圍或活動權限未符合，已停用自動活動', unknown='建立結果待核對，不會重建',
            unknown_sync='同步結果待核對', failed='交付失敗，需核對權限及紀錄', conflict='活動有人工修改，已停止同步',
            deleted='活動已刪除，不會重建', linked='已連結活動', cancelled='活動已取消', completed='活動已結束')
        return summary(self.member, p, self.settings) + '\n' + labels.get(e.get('state'), '')
    async def save(self, i, changes):
        if not await self.interaction_check(i):
            return
        await i.response.defer(ephemeral=True)
        async with self.cog.lock:
            from features.plan_services import source, AccessError
            try:
                member, channel = await source(self.cog, i.guild, self.owner, self.cog.book.get(self.key))
                from cogs.squad_plans import allowed
                from types import SimpleNamespace
                if not allowed(SimpleNamespace(guild_id=i.guild_id, user=member, channel=channel)):
                    raise AccessError('denied')
                settings = dict(self.settings, **changes)
                p = self.cog.book.delivery_settings(self.key, self.owner, settings, expected_revision=self.revision)
                # Cancellation/change synchronization occurs in the existing tick.
                await self.cog.refresh(p)
            except (ValueError, AccessError, discord.HTTPException, OSError):
                await i.edit_original_response(content=text(i.user, '設定未更新，請從原卡重新開啟。', '設定未更新，請喺原卡重新開啟。'), view=None); return
        view = Settings(self.cog, p, i.user)
        await i.edit_original_response(content=view.summary(p), view=view)
    @discord.ui.button(label='切換報名提醒')
    async def notice(self, i, button):
        await self.save(i, dict(host_notices=not self.settings['host_notices']))
    @discord.ui.button(label='切換自動活動')
    async def auto(self, i, button):
        await self.save(i, dict(auto_event=not self.settings['auto_event']))
    @discord.ui.button(label='修改成局人數')
    async def minimum(self, i, button):
        if not await self.interaction_check(i):
            return
        view = self
        class Minimum(SafeModal):
            def __init__(self):
                super().__init__(title='成局人數')
                self.value = discord.ui.TextInput(label='成局人數', default=str(view.settings['minimum'] or ''), max_length=3)
                self.add_item(self.value)
            async def on_submit(self, i):
                try:
                    minimum = int(self.value.value)
                except ValueError:
                    await i.response.send_message('請填整數。', ephemeral=True); return
                await view.save(i, dict(minimum=minimum))
        await i.response.send_modal(Minimum())
