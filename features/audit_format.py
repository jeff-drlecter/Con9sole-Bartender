"""Readable identities and change summaries; mentions are rendered but never pinged."""
import re
import discord


def safe(value,limit=900):
    text=discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))
    text=text.replace('<@','<@\u200b').replace('<#','<#\u200b')
    return text[:limit]+('…' if len(text)>limit else '')


def who(user):
    name=getattr(user,'display_name',None) or getattr(user,'global_name',None) or getattr(user,'name',None)
    return (f'**{safe(name,80)}** · ' if name else '')+f'<@{int(user.id)}>'


def role_label(role,*,deleted=False):
    name=safe(getattr(role,'name',None) or '未快取名稱',80)
    return f'**{name}**（已刪除｜ID `{role.id}`）' if deleted else f'**{name}** · <@&{int(role.id)}>'


def where(channel):
    return f'**{safe(channel.name,100)}** · <#{int(channel.id)}>' if channel else '未連接'


PERMISSIONS={
    'administrator':'管理員','view_audit_log':'查看審核紀錄','manage_guild':'管理伺服器',
    'manage_roles':'管理身份組','manage_channels':'管理頻道','manage_webhooks':'管理 Webhook',
    'view_channel':'查看頻道','send_messages':'發送訊息','manage_messages':'管理訊息',
    'read_message_history':'讀取訊息紀錄','embed_links':'嵌入連結','attach_files':'附加檔案',
    'mention_everyone':'提及所有人及身份組','kick_members':'踢出成員','ban_members':'封鎖成員',
    'moderate_members':'禁言成員','connect':'連接語音','speak':'語音發言','stream':'分享畫面',
    'mute_members':'靜音成員','deafen_members':'拒聽成員','move_members':'移動語音成員',
    'create_instant_invite':'建立邀請','add_reactions':'新增反應','change_nickname':'更改自己暱稱',
    'manage_nicknames':'管理成員暱稱','use_application_commands':'使用應用程式指令',
    'create_public_threads':'建立公開討論串','create_private_threads':'建立私人討論串',
    'send_messages_in_threads':'在討論串發送訊息','manage_threads':'管理討論串',
    'read_messages':'查看頻道','priority_speaker':'優先發言','send_tts_messages':'發送文字轉語音',
    'external_emojis':'使用外部表情符號','external_stickers':'使用外部貼圖',
    'view_guild_insights':'查看伺服器分析','use_voice_activation':'使用語音活動偵測',
    'manage_expressions':'管理表情及貼圖','request_to_speak':'要求發言','manage_events':'管理活動',
    'use_embedded_activities':'使用活動','view_creator_monetization_analytics':'查看收益分析',
    'use_soundboard':'使用音效板','create_expressions':'建立表情及貼圖','create_events':'建立活動',
    'use_external_sounds':'使用外部音效','send_voice_messages':'發送語音訊息',
    'set_voice_channel_status':'設定語音頻道狀態','send_polls':'建立投票',
    'use_external_apps':'使用外部應用程式','pin_messages':'釘選訊息','bypass_slowmode':'略過慢速模式',
}


def permission_names(value):
    return [PERMISSIONS.get(name,name.replace('_',' ')) for name,enabled in value if enabled]


def format_value(key,value):
    if key=='roles' and value is not None:
        return ', '.join(role_label(role) for role in value) or '無'
    if isinstance(value,discord.Permissions): return '、'.join(permission_names(value)) or '無'
    if isinstance(value,bool): return '開啟' if value else '關閉'
    if value is None: return '無'
    if key=='category_id': return f'<#{int(value)}>'
    return safe(value,180)


def changes(before,after,fields):
    result=[]
    for key,label in fields:
        old,new=getattr(before,key,None),getattr(after,key,None)
        if old==new: continue
        if key=='permissions' and isinstance(old,discord.Permissions) and isinstance(new,discord.Permissions):
            added=permission_names(discord.Permissions(new.value & ~old.value))
            removed=permission_names(discord.Permissions(old.value & ~new.value))
            if added: result.append('允許：'+'、'.join(added))
            if removed: result.append('取消：'+'、'.join(removed))
        else: result.append(f'{label}：{format_value(key,old)} → {format_value(key,new)}')
    return result


ACTIONS={
    'role_create':'建立身份組','role_update':'修改身份組','role_delete':'刪除身份組',
    'member_update':'修改成員資料','member_role_update':'更改成員身份組',
    'kick':'踢出成員','ban':'封鎖成員','unban':'解除封鎖','member_prune':'清理不活躍成員',
    'member_move':'移動語音成員','member_disconnect':'中斷成員語音',
    'channel_create':'建立頻道','channel_update':'修改頻道','channel_delete':'刪除頻道',
    'overwrite_create':'新增頻道權限','overwrite_update':'修改頻道權限','overwrite_delete':'刪除頻道權限',
    'guild_update':'修改伺服器','message_delete':'刪除訊息','message_bulk_delete':'批次刪除訊息',
    'thread_create':'建立討論串','thread_update':'修改討論串','thread_delete':'刪除討論串',
    'emoji_create':'新增表情符號','emoji_update':'修改表情符號','emoji_delete':'刪除表情符號',
    'webhook_create':'建立 Webhook','webhook_update':'修改 Webhook','webhook_delete':'刪除 Webhook',
}


def identity_footer(description):
    parts=[]
    for label,pattern in [('成員',r'<@!?(\d+)>'),('身份組',r'<@&(\d+)>'),('頻道',r'<#(\d+)>')]:
        ids=list(dict.fromkeys(re.findall(pattern,description)))
        if ids: parts.append(label+' '+','.join(ids[:3])+('…' if len(ids)>3 else ''))
    return '｜'.join(parts)
