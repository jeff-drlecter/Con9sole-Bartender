"""Public opted-in chat only; reuse the existing journalled executor."""
import time
import uuid
import discord

from config import PUBLIC_CHAT_CHANNEL_ID

OFF_TOPIC=1425179515637727302
PUBLIC_CATEGORY=1013033505476853773


def build(roles,channels,guild,actor):
    role=next((r for r in roles if r.id==OFF_TOPIC),None)
    if role is None or role.managed:raise ValueError('公海角色不存在或屬整合角色。')
    plan=dict(id=uuid.uuid4().hex[:12],scope='participation',guild=guild,actor=actor,stamp=time.time(),ops=[],skipped=[])
    channel = next((c for c in channels if c.id == PUBLIC_CHAT_CHANNEL_ID), None)
    if channel is None:
        raise ValueError('指定公海頻道未能完整讀取。')
    if not isinstance(channel, discord.TextChannel) or channel.category_id != PUBLIC_CATEGORY:
        raise ValueError('指定公海頻道分類／類型已改變，請先核對。')
    ow = channel.overwrites_for(role)
    if ow.view_channel is not True:
        raise ValueError('公海角色目前並非明確允許查看，停止，唔擴大可見範圍。')
    if ow.send_messages is False or ow.send_messages_in_threads is False:
        plan['skipped'].append(f'{channel.name}：有明確發言拒絕，保留')
        return plan
    before = [p.value for p in ow.pair()]
    ow.send_messages = True
    ow.send_messages_in_threads = True
    after = [p.value for p in ow.pair()]
    if before != after:
        plan['ops'].append(dict(kind='overwrite', channel=channel.id, target=role.id,
                                name=f'{channel.name}：已加入公海即可聊天／回覆討論串',
                                before=before, after=after, state='prepared'))
    return plan


async def execute(guild,plan,authorize,*,restore=False):
    from features import anti_scam_fix as journal
    # Old journals can include the forum that has since left the public area.
    for op in plan['ops']:
        if op['kind']!='overwrite' or op['target']!=OFF_TOPIC or op['channel']!=PUBLIC_CHAT_CHANNEL_ID:
            raise ValueError('計劃超出公海參與範圍，請重新預覽。')

    def validate(op,role,channel):
        if not isinstance(channel,discord.TextChannel) or channel.category_id!=PUBLIC_CATEGORY:
            raise ValueError('頻道分類／類型已改變，請先核對。')
    return await journal.execute(guild,plan,authorize,restore=restore,validate=validate)
