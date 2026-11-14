"""Fresh news permission inventory without dropping unsupported channel types.

discord.py Guild.fetch_channels rejects the whole response if one unrelated
channel has a new type. Keep every raw overwrite for scope checks, and only
construct supported TextChannel objects for the three channels we may edit.
"""
from types import SimpleNamespace

import discord
from features.news_channel_categories import CHANNELS


def convert_inventory(guild, rows):
    result = []
    seen = set()
    for row in rows:
        cid = int(row['id'])
        if cid in seen:
            raise ValueError('頻道清單包含重複項目，請稍後再試。')
        seen.add(cid)
        if cid in CHANNELS.values():
            if row['type'] not in (0, 5):
                raise ValueError('指定新聞頻道類型已改變，請先核對。')
            result.append(discord.TextChannel(state=guild._state, guild=guild, data=row))
        else:
            overwrites = {}
            for item in row.get('permission_overwrites', []):
                if item['type'] not in (0, 1):
                    raise ValueError('未能辨識頻道權限目標，請先核對。')
                target = discord.Object(id=int(item['id']),
                    type=discord.Role if item['type'] == 0 else discord.Member)
                overwrites[target] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(int(item['allow'])), discord.Permissions(int(item['deny'])))
            result.append(SimpleNamespace(id=cid, overwrites=overwrites))
    return result


async def fetch_news_channels(guild):
    # Reuse the Bot HTTP client, authentication and rate limits. No user tokens.
    rows = await guild._state.http.get_all_guild_channels(guild.id)
    return convert_inventory(guild, rows)
