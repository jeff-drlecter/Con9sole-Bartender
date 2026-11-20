"""Exercise menu dispatch and cross-channel posting with real discord.py types."""
import subprocess
import sys
import unittest


class SquadPlanMenuTests(unittest.TestCase):
    def test_menu_destination_and_permission_rechecks(self):
        check = subprocess.run([sys.executable, '-c', r'''
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import config
from cogs.squad_plans import SquadPlans, PlanChannelView, PlanForm, PlanMenu
from features.squad_plans import PlanBook
from features.menu_views import QuickBarView

def channel(ident, name, visible=True):
    c = MagicMock(spec=discord.TextChannel)
    c.id, c.name, c.mention, c.category = ident, name, f'<#{ident}>', None
    perms = discord.Permissions.none()
    for key in ('view_channel', 'send_messages', 'embed_links', 'read_message_history'):
        setattr(perms, key, visible)
    c.permissions_for.return_value = perms
    c.send = AsyncMock(return_value=N(id=99))
    return c

def interaction(source, guild):
    return N(guild=guild, guild_id=config.GUILD_ID, channel=source, channel_id=source.id,
             user=N(id=3), response=N(send_message=AsyncMock(), send_modal=AsyncMock(), defer=AsyncMock(), is_done=lambda:False),
             edit_original_response=AsyncMock(),
             followup=N(send=AsyncMock()))

async def main():
    source = channel(1, '新成員')
    target = channel(2, 'fc-吹水組隊')
    hidden = channel(4, 'gta-吹水組隊', False)
    host = N(id=3, bot=False, display_name='姐夫', name='jefframe')
    guild = N(id=config.GUILD_ID, fetch_member=AsyncMock(return_value=host), fetch_roles=AsyncMock(return_value=[]), fetch_channel=AsyncMock(side_effect=lambda ident:{1:source,2:target,4:hidden}[ident]), text_channels=[source, target, hidden], me=N(id=9),
              get_channel=lambda ident: {1:source, 2:target, 4:hidden}.get(ident))
    for ch in (source,target,hidden):ch.guild=guild
    with tempfile.TemporaryDirectory() as directory, \
         patch('cogs.squad_plans.is_verified_member', return_value=True), \
         patch('cogs.squad_plans.is_server_admin', return_value=False):
        cog = N(book=PlanBook(Path(directory)/'plans.json', clock=lambda:1900000000),
                lock=asyncio.Lock(), refresh=AsyncMock())
        i = interaction(source, guild)
        await SquadPlans.menu_entry(cog, i)
        assert isinstance(i.response.send_message.call_args.kwargs['view'], PlanMenu)
        i.response.send_message.reset_mock()
        await SquadPlans.choose_destination(cog, i)
        picker = i.response.send_message.call_args.kwargs['view']
        assert isinstance(picker, PlanChannelView)
        assert [o.value for o in picker.children[0].options] == ['2']
        assert i.response.send_message.call_args.kwargs['ephemeral']

        direct = interaction(target, guild)
        await SquadPlans.choose_destination(cog, direct)
        assert isinstance(direct.response.send_modal.call_args.args[0], PlanForm)

        form = PlanForm(cog, target)
        for field, value in ((form.game, 'FC'), (form.start, '明天22:00'), (form.party, '1')):
            field._value = value
        with patch('cogs.squad_plans.parse_start', return_value=1900003600):
            await form.on_submit(i)
            target.send.assert_not_awaited()
            assert not cog.book.all()
            draft = i.edit_original_response.call_args.kwargs['view']
            assert '有人報名時提醒我' in draft.summary()
            await draft.publish.callback(i)
        target.send.assert_awaited_once()
        source.send.assert_not_awaited()
        posted = target.send.await_args.kwargs
        assert posted['allowed_mentions'].to_dict() == {'parse': []}
        assert posted['embed'].fields[1].value == '姐夫（jefframe）'
        stored = PlanBook(cog.book.path).all()[0]
        assert stored['channel'] == target.id and stored['owner'] == host.id
        assert stored['owner_label'] == '姐夫（jefframe）'

        original = N(author=N(id=9), content='', edit=AsyncMock())
        target.fetch_message = AsyncMock(return_value=original)
        cog.bot = N(user=original.author, get_channel=lambda _: target)
        cached = N(name='jefframe', display_name='Jefframe')
        guild.get_member = lambda uid: cached if uid == host.id else None
        async def refreshed_owner(plan):
            assert await SquadPlans.refresh(cog, plan)
            edited = original.edit.await_args.kwargs
            assert edited['allowed_mentions'].to_dict() == {'parse': []}
            return edited['embed'].fields[1].value
        assert await refreshed_owner(stored) == '姐夫（jefframe）'
        legacy = stored.copy()
        del legacy['owner_label']
        assert await refreshed_owner(legacy) == 'Jefframe'
        guild.get_member = lambda _: None
        assert await refreshed_owner(legacy) == '用戶 ID 3'
        disguised = dict(stored, owner_label='**<@123456789012345678>**\n@everyone <#33>')
        text = await refreshed_owner(disguised)
        assert not any(token in text for token in ('<@', '<#', '@everyone', '\n', '**'))
        assert '123456789012345678' in text and 'everyone' in text
        target.send.assert_awaited_once()

        target.send.reset_mock()
        target.permissions_for.return_value.send_messages = False
        denied = interaction(source, guild)
        await PlanForm(cog, target).on_submit(denied)
        target.send.assert_not_awaited()
        denied.edit_original_response.assert_awaited_once()

        with patch('cogs.squad_plans.is_verified_member', return_value=False):
            denied = interaction(source, guild)
            await SquadPlans.menu_entry(cog, denied)
            denied.response.send_modal.assert_not_awaited()
            assert 'view' not in denied.response.send_message.call_args.kwargs

        menu = MagicMock()
        menu.enforce_menu_button_cooldown = AsyncMock(return_value=False)
        view = QuickBarView(menu)
        item = next(b.item for b in view.children if b.item.id == 'squad_plans')
        assert item.row == 0 and item.cog == 'SquadPlans'
        routed = interaction(source, guild)
        feature = N(menu_entry=AsyncMock())
        routed.client = N(get_cog=lambda name: feature if name == 'SquadPlans' else None)
        await view.handle_item(routed, item)
        feature.menu_entry.assert_awaited_once_with(routed)
        menu.enforce_menu_button_cooldown.assert_not_awaited()
        assert view.is_persistent()
        assert sum(b.row == 0 for b in view.children) == 3
asyncio.run(main())
'''], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
