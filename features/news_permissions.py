"""Three news channels only: View Channel plans with durable receipts."""
import hashlib
import json
import time
import uuid

import discord
import config
from features.news_channel_categories import CHANNELS, ROLE_NAMES

VIEW = discord.Permissions(view_channel=True).value
SCOPE = 'news_channel_view_v1'


def role_target(target):
    return isinstance(target, discord.Role) or getattr(target, 'type', None) is discord.Role


def fingerprint(roles, channels):
    payload = {
        'roles': sorted((r.id, r.name, r.permissions.value, r.managed) for r in roles),
        'channels': sorted((c.id, c.category_id, c.type.value, c.permissions_synced,
            sorted((t.id, role_target(t), *(p.value for p in ow.pair()))
                   for t, ow in c.overwrites.items()))
            for c in channels if c.id in CHANNELS.values()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build(roles, channels, guild, actor, role_ids):
    if guild != config.GUILD_ID or set(role_ids) != set(CHANNELS):
        raise ValueError('新聞分類設定不完整。')
    ids = {key: int(value) for key, value in role_ids.items()}
    by_id = {r.id: r for r in roles}
    if len(set(ids.values())) != 3:
        raise ValueError('新聞分類身份組重複。')
    for key, rid in ids.items():
        role = by_id.get(rid)
        if role is None or role.name != ROLE_NAMES[key] or role.managed or role.permissions.value:
            raise ValueError('新聞分類身份組已改變，請先檢查。')
    helpers = set(config.HELPER_ROLE_IDS)
    if not helpers.issubset(by_id) or guild not in by_id:
        raise ValueError('未能完整讀取 Helpers 或 everyone。')
    if any(by_id[rid].permissions.administrator for rid in helpers):
        raise ValueError('Helpers 有管理員權限，頻道限制無法生效。')
    plan = dict(id=uuid.uuid4().hex[:12], scope=SCOPE, guild=guild, actor=actor,
                stamp=time.time(), ops=[], skipped=[], fingerprint=fingerprint(roles, channels),
                role_ids=ids, parents={}, blockers=[])
    selected = {c.id: c for c in channels if c.id in CHANNELS.values()}
    if set(selected) != set(CHANNELS.values()):
        raise ValueError('未能完整讀取三個新聞頻道。')
    for channel in channels:
        if channel.id not in CHANNELS.values() and any(
                role_target(t) and t.id in ids.values() for t in channel.overwrites):
            plan['blockers'].append('新聞身份組涉及其他頻道，請先檢查。')
    legacy = {r.id for r in roles if r.name in ('news-sub', 'no-news-sub')}
    known = helpers | legacy | {config.VERIFIED_ROLE_ID} | set(ids.values())
    for key, cid in CHANNELS.items():
        channel = selected[cid]
        if not isinstance(channel, discord.TextChannel) or channel.permissions_synced:
            raise ValueError('新聞頻道類型或分類同步狀態已改變，停止。')
        plan['parents'][str(cid)] = channel.category_id
        desired = {guild: False, **{rid: None for rid in known}, ids[key]: True}
        for target, ow in channel.overwrites.items():
            if ow.view_channel is not True or target.id in desired and role_target(target):
                continue
            role = by_id.get(target.id) if role_target(target) else None
            trusted = role is not None and (role.id == config.MOD_ROLE_ID or role.is_bot_managed() or
                role.permissions.administrator or role.permissions.manage_guild or
                role.permissions.manage_channels or role.permissions.manage_roles)
            if not trusted:
                plan['blockers'].append(f'{channel.name}：另有 {getattr(target, "name", target.id)} 查看允許，需先核對。')
        for rid, value in desired.items():
            role = by_id.get(rid)
            if role is None:
                continue
            ow = discord.PermissionOverwrite.from_pair(*channel.overwrites_for(role).pair())
            # Preserve explicit denials on old/Verified identities. Helpers and
            # the new opt-in roles must be neutral outside their own category.
            if rid in (legacy | {config.VERIFIED_ROLE_ID}) - helpers and ow.view_channel is False:
                continue
            before = [p.value for p in ow.pair()]
            ow.view_channel = value
            after = [p.value for p in ow.pair()]
            if before != after:
                label = {True: '允許', False: '拒絕', None: '中立'}[value]
                plan['ops'].append(dict(kind='overwrite', channel=cid, target=rid,
                    name=f'{channel.name}／{role.name}：查看 → {label}',
                    before=before, after=after, state='prepared'))
    return plan


async def execute(guild, plan, authorize, *, restore=False):
    from features import anti_scam_fix as journal
    from core.news_channel_ui import settings
    from core.news_channel_inventory import fetch_news_channels
    if plan.get('scope') != SCOPE or plan['guild'] != guild.id:
        raise ValueError('計劃範圍不符。')
    if not restore:
        fresh = build(await guild.fetch_roles(), await fetch_news_channels(guild),
                      guild.id, plan['actor'], settings())
        if fresh['blockers']:
            raise ValueError('仍有額外查看權限需要核對，未套用。')
        if fresh['fingerprint'] != plan['fingerprint'] or fresh['role_ids'] != plan['role_ids']:
            raise ValueError('設定已改變，請重新檢查；未套用。')
        expected = [(o['channel'], o['target'], o['before'], o['after']) for o in fresh['ops']]
        actual = [(o['channel'], o['target'], o['before'], o['after']) for o in plan['ops']]
        if expected != actual:
            raise ValueError('修改清單不符，請重新檢查。')

    def validate(op, role, channel):
        if op['kind'] != 'overwrite' or op['channel'] not in CHANNELS.values():
            raise ValueError('操作超出三個新聞頻道。')
        if any((a ^ b) & ~VIEW for a, b in zip(op['before'], op['after'])):
            raise ValueError('操作涉及查看以外權限。')
        if channel is None or not isinstance(channel, discord.TextChannel) or channel.permissions_synced:
            raise ValueError('頻道類型或同步狀態已改變。')
        if channel.category_id != plan['parents'][str(channel.id)]:
            raise ValueError('頻道已移動，停止。')

    return await journal.execute(guild, plan, authorize, restore=restore,
                                 validate=validate, max_seconds=150)
