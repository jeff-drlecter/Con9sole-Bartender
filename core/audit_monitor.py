"""Independent, persistent single-card incident notifications for audit logging."""
from __future__ import annotations

import time

import discord

from core.json_storage import atomic_write_json, load_json_object

ALERT_CHANNEL = 1569717305489752216
GRACE_SECONDS = 90


def findings(health, *, sender_running, heartbeat, write_failed, now=None):
    now = time.time() if now is None else now
    result=[]
    if not sender_running: result.append('日誌派送循環已停止')
    elif heartbeat and now-heartbeat>120: result.append('日誌派送超過 120 秒未完成一輪')
    if write_failed: result.append('最近一次事件未能寫入持久佇列')
    if health['states'].get('uncertain',0): result.append(f"結果未明：{health['states']['uncertain']} 筆，需人工核對")
    if health['states'].get('pending',0)>=100: result.append(f"待送積壓：{health['states']['pending']} 筆")
    if health.get('oldest_pending') and now-health['oldest_pending']>120:
        result.append('最舊待送事件已超過 120 秒')
    if health.get('oldest_sending') and now-health['oldest_sending']>120:
        result.append('有派送中事件超過 120 秒未確認')
    return result


class IncidentCard:
    """No outbox dependency. Persist before send; uncertain sends never auto-duplicate."""
    def __init__(self,path):
        self.path=path
        self.state=load_json_object(path,dict)
        if self.state.get('delivery')=='sending':
            self.state['delivery']='uncertain'
            self.save()

    def save(self): atomic_write_json(self.path,self.state)

    async def publish(self,channel,issues,*,demo=False,now=None):
        now=time.time() if now is None else now
        if issues:
            if not self.state.get('since'): self.state['since']=now
            self.state['issues']=issues
            self.save()
            if not demo and now-self.state['since']<GRACE_SECONDS:
                return 'grace'
        elif not self.state.get('since'):
            return 'healthy'
        elif self.state.get('status')!='異常' and self.state.get('delivery') not in {'sending','uncertain'}:
            self.state.update(since=None,issues=[])
            self.save()
            return 'resolved_during_grace'
        status='異常' if issues else '已恢復'
        text=('🧪【模擬驗收】' if demo else '')+f'📋 **日誌監察｜{status}**\n'
        text+='\n'.join(issues) if issues else '先前異常已解除；待查紀錄仍須逐項人工處理。'
        text+=f'\n開始：<t:{int(self.state["since"])}:f>｜檢查：<t:{int(now)}:f>\n使用 `/logging` 核對；此卡會原位更新。'
        signature=(status,tuple(issues))
        last=(self.state.get('status'),tuple(self.state.get('published_issues',[])))
        if signature==last:
            return 'unchanged'
        mid=self.state.get('message_id')
        if mid:
            try:
                await channel.get_partial_message(mid).edit(content=text,allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                self.state.pop('message_id',None)
                self.state['delivery']='pending'
                self.save()
                return await self.publish(channel,issues,demo=demo,now=now)
        elif self.state.get('delivery') in {'sending','uncertain'}:
            return 'uncertain'
        else:
            self.state['delivery']='sending'; self.save()
            try:
                message=await channel.send(text,allowed_mentions=discord.AllowedMentions.none(),silent=True)
            except discord.HTTPException as exc:
                self.state['delivery']='pending' if 400<=exc.status<500 else 'uncertain'
                self.save(); raise
            except BaseException:
                self.state['delivery']='uncertain'; self.save(); raise
            self.state['message_id']=message.id
        self.state.update(status=status,published_issues=list(issues),delivery='sent')
        if not issues: self.state['since']=None
        self.save()
        return 'updated' if mid else 'sent'
