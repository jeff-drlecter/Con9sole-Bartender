"""Public read-only entry security and localization, isolated from module stubs."""
import subprocess
import sys
import unittest

class PublicRSSTests(unittest.TestCase):
    def test_public_entry_access_and_private_results(self):
        result = subprocess.run([sys.executable, '-c', r'''
import asyncio,tempfile
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch,AsyncMock
import config
from cogs.rss_delivery import RSSDelivery
from core.rss_digest import DigestStore
from core.rss_preferences import PreferenceStore,DEFAULT
from core.rss_personal_ui import show_news,PreferencesView,KeywordModal
from core.rss_wording import rss_text
class Channel:
    guild=S(id=config.GUILD_ID,me=object())
    visible=True
    def permissions_for(self,user): return S(view_channel=self.visible)
async def main():
    with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'RSS_DELIVERY_SOURCES':'','RSS_DIGEST_CONFIG':'','RSS_PERSONAL_PUBLIC':'1'}):
        cog=RSSDelivery(S())
        cog.store=DigestStore(Path(tmp)/'news.db')
        path=Path(tmp)/'prefs.db'
        cog.preferences=PreferenceStore(path)
        # A normal member needs no administrator, helper or game role.
        user=S(id=1,roles=[])
        i=S(user=user,guild_id=config.GUILD_ID,channel_id=456,channel=Channel(),
            response=S(send_message=AsyncMock(),defer=AsyncMock()),followup=S(send=AsyncMock()))
        with patch('cogs.rss_delivery.discord.TextChannel',Channel):
            assert await cog.personal_access(i)
            await cog.menu_entry(i)
            assert i.response.send_message.call_args.kwargs['ephemeral']
            assert i.response.send_message.call_args.kwargs['allowed_mentions'].everyone is False
            i.channel.visible=False
            assert not await cog.personal_access(i)
            i.channel.visible=True
            i.guild_id=0
            assert not await cog.personal_access(i)
            i.guild_id=config.GUILD_ID
            cog.public_personal=False
            assert not await cog.personal_access(i)
            cog.public_personal=True
            # Public browsing also works when production delivery is selected.
            cog.digest_config.simulation=False
            assert await cog.personal_access(i)
            assert await PreferencesView(cog,1,DEFAULT).interaction_check(i)
            assert not await PreferencesView(cog,2,DEFAULT).interaction_check(i)
        before=(cog.store.report(),cog.store.batch_report())
        await show_news(cog,i)
        assert i.followup.send.call_args.kwargs['ephemeral']
        assert before==(cog.store.report(),cog.store.batch_report())
        cog.preferences.put(1,dict(DEFAULT,platforms=['pc'],stores=['epic'],kinds=['keep']))
        cog.preferences.put(2,dict(DEFAULT,platforms=['ps']))
        cog.preferences=PreferenceStore(path) # reopen like a restart
        assert cog.preferences.get(2)['platforms']==['ps']
        await show_news(cog,i,True)
        assert len(i.followup.send.call_args.kwargs['embed'].fields)==1
        assert 'Epic' in i.followup.send.call_args.kwargs['embed'].fields[0].name
        assert before==(cog.store.report(),cog.store.batch_report())
        neutral=rss_text(user,'preferences')
        hk=S(id=1,roles=[S(name='語境偏好｜香港',managed=False,permissions=S(value=0))])
        tw=S(id=1,roles=[S(name='語境偏好｜台灣',managed=False,permissions=S(value=0))])
        assert rss_text(tw,'preferences')==neutral and rss_text(hk,'preferences')!=neutral
        assert '想睇' in KeywordModal(cog,1,DEFAULT,hk).include.label
        assert '想看' in KeywordModal(cog,1,DEFAULT,tw).include.label
asyncio.run(main())
'''],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
