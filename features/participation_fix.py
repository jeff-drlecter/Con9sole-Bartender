"""Public opted-in chat only; reuse the existing journalled executor."""
import time
import uuid
import discord

OFF_TOPIC=1425179515637727302
PUBLIC_CATEGORY=1013033505476853773
TARGETS={1013033957383741542,1279353169671098408}


def build(roles,channels,guild,actor):
    role=next((r for r in roles if r.id==OFF_TOPIC),None)
    if role is None or role.managed:raise ValueError('公海角色不存在或屬整合角色。')
    plan=dict(id=uuid.uuid4().hex[:12],scope='participation',guild=guild,actor=actor,stamp=time.time(),ops=[],skipped=[])
    for c in channels:
        if c.id not in TARGETS:continue
        if c.category_id!=PUBLIC_CATEGORY or not isinstance(c,(discord.TextChannel,discord.ForumChannel)):
            raise ValueError('指定公海頻道分類／類型已改變，請先核對。')
        ow=c.overwrites_for(role)
        if ow.view_channel is not True:
            raise ValueError('公海角色目前並非明確允許查看，停止，唔擴大可見範圍。')
        if ow.send_messages is False or ow.send_messages_in_threads is False:
            plan['skipped'].append(f'{c.name}：有明確發言拒絕，保留');continue
        before=[p.value for p in ow.pair()]
        ow.send_messages=True;ow.send_messages_in_threads=True
        after=[p.value for p in ow.pair()]
        if before!=after:plan['ops'].append(dict(kind='overwrite',channel=c.id,target=role.id,name=f'{c.name}：已加入公海即可聊天／回覆討論串',before=before,after=after,state='prepared'))
    if not TARGETS.issubset({c.id for c in channels}):raise ValueError('指定公海頻道未能完整讀取。')
    return plan


async def execute(guild,plan,authorize,*,restore=False):
    from features import anti_scam_fix as journal
    def validate(op,role,channel):
        if op['kind']!='overwrite' or op['target']!=OFF_TOPIC or op['channel'] not in TARGETS:
            raise ValueError('計劃超出公海參與範圍。')
        if not restore and (channel is None or channel.category_id!=PUBLIC_CATEGORY or not isinstance(channel,(discord.TextChannel,discord.ForumChannel))):
            raise ValueError('頻道分類／類型已改變，停止套用。')
    return await journal.execute(guild,plan,authorize,restore=restore,validate=validate)
