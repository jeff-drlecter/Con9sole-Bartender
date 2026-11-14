"""Member setting boundaries, durable readback and existing persistent entry IDs."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from core.rss_preferences import PreferenceStore
from core.rss_personal_ui import IntelligenceSettings, NewsCardPanel, Choice, PreferencesView
from core.rss_wording import rss_text

class NewsExperienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_are_read_only_until_member_chooses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'preferences.db'
            store = PreferenceStore(path)
            original = store.get(5)
            cog = S(preferences=store, personal_access=AsyncMock(return_value=True),
                    channel_preferences_entry=AsyncMock(), digest_config=S(simulation=False))
            inter = S(user=S(id=5, roles=[]), response=S(send_message=AsyncMock()))
            view = IntelligenceSettings(cog, 5, inter.user)
            await view.filters.callback(inter)
            self.assertEqual(PreferenceStore(path).get(5), original)
            cog.channel_preferences_entry.assert_not_awaited()
            await view.channels.callback(inter)
            cog.channel_preferences_entry.assert_awaited_once_with(inter)
            self.assertEqual(PreferenceStore(path).get(5), original)
            other = S(user=S(id=6), response=S(send_message=AsyncMock()))
            self.assertFalse(await view.interaction_check(other))

    async def test_save_readback_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prefs.db'
            store=PreferenceStore(path)
            cog=S(preferences=store,digest_config=S(simulation=False))
            user=S(id=5,roles=[])
            view=PreferencesView(cog,5,store.get(5),user)
            choice=next(c for c in view.children if isinstance(c,Choice) and c.key=='platforms')
            choice._values=['pc']
            inter=S(user=user,response=S(edit_message=AsyncMock()))
            await choice.callback(inter)
            saved=PreferenceStore(path).get(5)
            self.assertEqual(saved['platforms'],['pc'])
            reopened=inter.response.edit_message.call_args.kwargs['view']
            selected=next(c for c in reopened.children if isinstance(c,Choice) and c.key=='platforms')
            self.assertEqual([o.value for o in selected.options if o.default],['pc'])

    async def test_persistent_ids_and_language_boundaries(self):
        panel=NewsCardPanel(S())
        self.assertTrue(panel.is_persistent())
        self.assertEqual([c.custom_id for c in panel.children],
            ['rss:card:news:v1','rss:card:preferences:v1','rss:card:channels:v1'])
        hk=S(roles=[S(name='語境偏好｜香港',managed=False,permissions=S(value=0))])
        tw=S(roles=[S(name='語境偏好｜台灣',managed=False,permissions=S(value=0))])
        self.assertIn('唔會',rss_text(hk,'settings'))
        self.assertIn('不會',rss_text(tw,'settings'))
        self.assertEqual(rss_text(tw,'settings'),rss_text(S(roles=[]),'settings'))
