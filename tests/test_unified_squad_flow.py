"""Run real Discord view classes without connecting or sending external messages."""
import subprocess
import sys
import unittest


class UnifiedFlow(unittest.TestCase):
    def test_linked_voice_reuses_original_card_and_preserves_roster(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import config
from cogs.squad_cards import SquadCards
from cogs.squad_plans import PlanView, StartView, SquadPlans
from cogs.tempvc import TempVC
from features.squad_plans import PlanBook

async def main():
    with tempfile.TemporaryDirectory() as folder:
        book=PlanBook(Path(folder)/'plans.json',clock=lambda:10000)
        p=book.create(guild=config.GUILD_ID,channel=20,owner=3,game='FC',mode='Clubs',start=10100,party=1,capacity=None)
        key=p['id'];book.publish(key,99)
        for uid in range(4,8):book.act(key,uid,'join')
        book.link_voice(key,3,50)
        plans=N(book=book,refresh=AsyncMock())
        original=N(id=99,author=N(id=9),content='',edit=AsyncMock())
        old=N(id=88,author=N(id=9),content='',edit=AsyncMock())
        destination=N(id=20,fetch_message=AsyncMock(side_effect=lambda ident:{99:original,88:old}[ident]),send=AsyncMock())
        voice=N(id=50,category=N(name='EA SPORTS FC'),members=[N(id=3,display_name='host',bot=False)])
        bot=N(user=N(id=9),get_channel=lambda ident:{20:destination,50:voice}.get(ident),get_cog=lambda name:plans if name=='SquadPlans' else None,is_ready=lambda:True)
        cog=N(bot=bot,save=lambda:None,notify_interested=AsyncMock())
        session=dict(id='voice-session',started=10000,participants={'3':'host'},destination=20,first_member=3)
        async def close(destination,original,session,*args):session['footprint']=900
        cog.finish_footprint=AsyncMock(side_effect=close)
        with patch('cogs.squad_cards.run_stats',new=AsyncMock(return_value=None)), patch('cogs.squad_cards.interest_topic',return_value=None):
            await SquadCards.render(cog,voice,session)
            destination.send.assert_not_awaited()
            assert session['message']==99 and session['plan_id']==key
            assert book.get(key)['status']=='live'
            assert book.get(key)['members']==[4,5,6,7]
            assert isinstance(original.edit.await_args.kwargs['view'],PlanView)
            session['ended']=10100
            await SquadCards.render(cog,voice,session,ended=True)
            assert book.get(key)['status']=='ended' and book.get(key)['footprint']==900
            assert book.get(key)['members']==[4,5,6,7]
            cog.finish_footprint.assert_awaited_once()
            plans.refresh.assert_awaited_once()

        # Adopt an already-published automatic card without creating another post.
        p=book.create(guild=config.GUILD_ID,channel=20,owner=3,game='FC',mode='Clubs',start=10100,party=1,capacity=None)
        book.publish(p['id'],99);book.link_voice(p['id'],3,50)
        session=dict(id='existing-session',started=10000,participants={'3':'host'},destination=20,message=88,first_member=3)
        with patch('cogs.squad_cards.run_stats',new=AsyncMock(return_value=None)), patch('cogs.squad_cards.interest_topic',return_value=None):
            await SquadCards.render(cog,voice,session)
            assert '前往原卡' in old.edit.await_args.kwargs['content']
            assert session['message']==99
            destination.send.assert_not_awaited()

        # A stale start confirmation cannot create a room after cancellation.
        p=book.create(guild=config.GUILD_ID,channel=20,owner=8,game='FC',mode='Clubs',start=10100,party=1,capacity=None)
        book.publish(p['id'],100);book.act(p['id'],8,'cancel')
        temp=N(room_for_plan=AsyncMock())
        start_cog=N(book=book,lock=asyncio.Lock(),bot=N(get_cog=lambda name:temp))
        i=N(user=N(id=8),guild_id=config.GUILD_ID,channel_id=20,response=N(defer=AsyncMock(),send_message=AsyncMock()),followup=N(send=AsyncMock()))
        view=StartView(start_cog,p['id'],8)
        with patch('cogs.squad_plans.allowed',return_value=True):
            await view.start.callback(i)
        temp.room_for_plan.assert_not_awaited()

        # Fresh permissions and game category prevent borrowing a different game room.
        member=MagicMock(spec=discord.Member);member.id=3;member.pending=False;member.bot=False;member.is_timed_out.return_value=False
        category=N(id=40,permissions_for=lambda _:N(view_channel=True,connect=True,speak=True))
        interaction=N(guild=N(fetch_member=AsyncMock(return_value=member)),guild_id=config.GUILD_ID,user=N(id=3),channel=N(category=category))
        temp=N(_find_owned_room=AsyncMock(return_value=N(category_id=41)),_create_manual_temp_vc=AsyncMock())
        with patch('cogs.tempvc.user_can_run_tempvc',return_value=True),patch('core.permissions.is_verified_member',return_value=True),patch('cogs.tempvc._category_from_ctx_channel',return_value=category):
            try:await TempVC.room_for_plan(temp,interaction)
            except ValueError:pass
            else:raise AssertionError('must reject another game category')
        temp._create_manual_temp_vc.assert_not_awaited()
asyncio.run(main())
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
