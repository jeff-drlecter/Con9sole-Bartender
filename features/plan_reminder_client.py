"""02 UI boundary. Proposed v1 capability; 03 owns all reads and writes.

No fallback to PlanBook, ReminderView, files, SQL or an empty success response.
See docs/PRIVATE_CENTER_02_HANDOFF.md before 06 enables the integration.
"""
from urllib.parse import urlparse
import math


class ReminderUnavailable(Exception):
    pass


def service(bot):
    cog=bot.get_cog('SquadPlans')
    api=getattr(cog,'personal_reminders_v1',None)
    if (api is None or type(getattr(api,'version',None)) is not int or api.version!=1
            or not callable(getattr(api,'list_for_member',None))
            or not callable(getattr(api,'set_for_member',None))):
        raise ReminderUnavailable()
    return api


async def query(bot,guild,actor):
    try:
        result=await service(bot).list_for_member(guild,actor)
        if not isinstance(result,dict) or result.get('complete') is not True:
            raise ReminderUnavailable()
        rows=result['rows']
        if not isinstance(rows,list): raise ReminderUnavailable()
        safe=[]
        for row in rows:
            if (not isinstance(row,dict) or not isinstance(row.get('id'),str)
                    or not 0 < len(row['id']) <= 100
                    or not isinstance(row.get('game'),str) or not isinstance(row.get('version'),str)
                    or not isinstance(row.get('status'),str)
                    or not row['version'] or any(type(row.get(k)) is not bool for k in ('enabled','can_enable','can_disable'))):
                raise ReminderUnavailable()
            start=row.get('start')
            if start is not None and (type(start) not in (int,float) or not math.isfinite(start)):
                raise ReminderUnavailable()
            safe.append({k:row.get(k) for k in ('id','game','start','status','enabled','can_enable','can_disable','version','url')})
        if len({r['id'] for r in safe})!=len(safe): raise ReminderUnavailable()
        return safe
    except Exception as exc:
        raise ReminderUnavailable() from exc


async def set_choice(bot,guild,actor,key,enabled,version):
    # Opaque version includes registration epoch, not just a displayed plan revision.
    result=await service(bot).set_for_member(guild,actor,key,enabled=enabled,expected_version=version)
    if not isinstance(result,dict) or result.get('status') not in ('updated','conflict','denied','unavailable'):
        raise ReminderUnavailable()
    return result


def card_url(value,guild_id):
    """Only a service-authorized Discord card link, not arbitrary supplied URLs."""
    if not isinstance(value,str): return None
    parsed=urlparse(value)
    parts=parsed.path.split('/')
    if (parsed.scheme=='https' and parsed.netloc=='discord.com' and not parsed.query and not parsed.fragment
            and len(parts)==5 and parts[1]=='channels' and parts[2]==str(guild_id)
            and all(x.isdecimal() for x in parts[3:])):
        return value
    return None
