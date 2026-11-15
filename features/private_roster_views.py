"""Reload card-bound lists on every private action; never trust an old roster."""
import sqlite3
import discord
from core.ui import SafeView
from core.private_source import Source, SourceUnavailable, visible_people
from features import squad_interest, squad_participants
from features.menu_stats import run_stats
from features.notification_words import text


class RosterPages(SafeView):
    kind = 'participants'
    def __init__(self, source, *, source_view=None, member=None):
        super().__init__(timeout=180)
        self.source, self.source_view, self.member = source, source_view, member
        self.page, self.pages, self.roster = 0, [''], []
        self.source_message = None
        for label, delta in [('previous', -1), ('next', 1), ('refresh', 0)]:
            button = discord.ui.Button(label=text(member, label), row=0)
            async def move(i, delta=delta): await self.move(i, delta)
            button.callback = move
            self.add_item(button)
        self.previous, self.next_page = self.children[:2]
        if self.kind == 'roster' and source_view:
            for choice, label in [('once','下次通知我'), ('always','長期跟局')]:
                button = discord.ui.Button(label=label, row=1)
                async def choose(i, choice=choice):
                    if not await self.interaction_check(i): return
                    await self.source_view.toggle(i, choice, source_message=self.source_message, roster_pages=self)
                button.callback = choose
                self.add_item(button)

    async def interaction_check(self, i):
        if i.user.id != self.source.owner:
            await i.response.send_message(text(i.user, 'owner'), ephemeral=True)
            return False
        return True  # load() or toggle guard performs all source checks after acknowledgement.

    async def load(self, i):
        member, channel, message = await self.source.resolve(i)
        self.member = member
        if self.kind == 'roster':
            prefs = await run_stats(squad_interest.preferences, self.source_view.topic['id'])
            roster = await visible_people(i.guild, channel, prefs)
            self.roster = [(uid, f'{name}（{text(member, prefs[uid])}）') for uid, name in roster]
            lines = [f'<@{uid}> · {name}' for uid, name in self.roster]
        else:
            snapshot = await run_stats(squad_participants.get, self.source.message, self.source.guild, self.source.channel)
            if snapshot is None:
                legacy = squad_participants.compact_legacy(message.embeds[0].copy()) if message.embeds else []
                snapshot = dict(names={}, legacy=legacy)
            roster = await visible_people(i.guild, channel, snapshot['names'])
            lines = [f'<@{uid}> · {name}' for uid, name in roster]
            lines.extend(discord.utils.escape_mentions(discord.utils.escape_markdown(raw)) for raw in snapshot['legacy'])
        # Check again after data/member reads. Failed loads never leave a reusable old result.
        self.member, _, self.source_message = await self.source.resolve(i)
        pages = ['']
        for index,line in enumerate(lines):
            if self.kind=='roster' and index and index%20==0:pages.append('')
            for start in range(0, len(line), 2800):
                piece = line[start:start+2800]
                if len(pages[-1])+len(piece)+1 > 3000: pages.append('')
                pages[-1] += ('\n' if pages[-1] else '')+piece
        self.pages = pages
        self.page = min(self.page, len(pages)-1)
        for button, key in zip(self.children[:3], ('previous','next','refresh')): button.label=text(self.member,key)
        self.previous.disabled=self.page==0
        self.next_page.disabled=self.page==len(pages)-1

    def embed(self):
        embed=discord.Embed(title=text(self.member,self.kind),description=self.pages[self.page] or text(self.member,'no_roster'))
        embed.set_footer(text=text(self.member,'page',page=self.page+1,total=len(self.pages)))
        return embed

    async def render(self, i, *, replace=False, delta=0, content=None):
        try:
            await self.load(i)
            self.page=max(0,min(len(self.pages)-1,self.page+delta))
            self.previous.disabled=self.page==0;self.next_page.disabled=self.page==len(self.pages)-1
            kwargs=dict(content=content,embed=self.embed(),view=self,allowed_mentions=discord.AllowedMentions.none())
        except (SourceUnavailable, OSError, ValueError, sqlite3.Error):
            self.pages=[''];self.roster=[];self.source_message=None
            kwargs=dict(content=text(i.user,'denied'),embed=None,view=None,allowed_mentions=discord.AllowedMentions.none())
        if replace: await i.edit_original_response(**kwargs)
        else: await i.followup.send(**kwargs,ephemeral=True)

    async def move(self, i, delta):
        if not await self.interaction_check(i): return
        await i.response.defer(ephemeral=True)
        await self.render(i,replace=True,delta=delta)


class InterestRosterPages(RosterPages):
    kind='roster'
    def __init__(self,user_id,roster,label,*,source_view=None,source_message=None):
        # roster is deliberately ignored: old snapshots are not an authorization input.
        source=Source(user_id,source_view.topic['guild_id'],source_message.channel.id,source_message.id)
        super().__init__(source,source_view=source_view)
        self.label=label


class ParticipantPages(RosterPages):
    def __init__(self,interaction,snapshot=None):
        super().__init__(Source(interaction.user.id,interaction.guild_id,interaction.channel_id,interaction.message.id),member=interaction.user)
