"""Recover only pre-existing verified level roles after an explicit test drill."""
import asyncio
from features.level_baseline import role_mapping


async def restore(guild,ledger,marker,role_safe):
    if marker['state'] not in ('pending','rollback'):return marker
    mapping=role_mapping([dict(id=r.id,name=r.name) for r in guild.roles])
    if {str(k):v for k,v in mapping.items()}!=marker['mapping']:raise ValueError('Complete drill role mapping changed')
    allowed=set(mapping.values());original=set(marker['roles'])
    if not original or not original<=allowed:raise ValueError('Drill role mapping changed')
    roles=[guild.get_role(rid) for rid in original]
    if any(r is None or not role_safe(r,guild.me) for r in roles):raise ValueError('Drill role became unsafe')
    member=await guild.fetch_member(marker['user'])
    joined=member.joined_at.timestamp() if member.joined_at else None
    if marker['state']=='rollback':
        if joined==marker['rollback_joined_at']:
            stale=[r for r in roles if r.id in marker['stale_grants'] and r in member.roles]
            if stale:await member.remove_roles(*stale,reason='Con9sole 取消過期測試角色還原')
            verified=await guild.fetch_member(marker['user'])
            if verified.joined_at and verified.joined_at.timestamp()==joined and any(r.id in marker['stale_grants'] for r in verified.roles):raise ValueError('Stale drill grant removal not confirmed')
        result={**marker,'state':'aborted_rejoined'}
        await asyncio.to_thread(ledger.configure,guild.id,role_drill=result)
        return result
    if joined is None or joined!=marker['joined_at']:
        if marker.get('grant_intent'):
            rollback={**marker,'state':'rollback','rollback_joined_at':joined,'stale_grants':marker['grant_intent']}
            await asyncio.to_thread(ledger.configure,guild.id,role_drill=rollback)
            await restore(guild,ledger,rollback,role_safe)
            raise ValueError('Rejoined member: interrupted drill grants removed')
        result={**marker,'state':'aborted_rejoined'}
        await asyncio.to_thread(ledger.configure,guild.id,role_drill=result)
        raise ValueError('Drill member left/rejoined; old role not restored')
    current={r.id for r in member.roles if r.id in allowed}
    if current-original:raise ValueError('Concurrent level role change; reviewed restore required')
    missing=[r for r in roles if r.id not in current]
    if missing:
        marker={**marker,'grant_intent':[r.id for r in missing]}
        await asyncio.to_thread(ledger.configure,guild.id,role_drill=marker)
        await member.add_roles(*missing,reason='Con9sole 測試角色還原')
    verified=await guild.fetch_member(marker['user'])
    final_joined=verified.joined_at.timestamp() if verified.joined_at else None
    if final_joined!=marker['joined_at']:
        rollback={**marker,'state':'rollback','rollback_joined_at':final_joined,'stale_grants':[r.id for r in missing]}
        await asyncio.to_thread(ledger.configure,guild.id,role_drill=rollback)
        await restore(guild,ledger,rollback,role_safe)
        raise ValueError('Drill member rejoined during restore; stale grants rolled back')
    if {r.id for r in verified.roles if r.id in allowed}!=original:raise ValueError('Drill restore not confirmed')
    result={**marker,'state':'restored'}
    await asyncio.to_thread(ledger.configure,guild.id,role_drill=result)
    return result
