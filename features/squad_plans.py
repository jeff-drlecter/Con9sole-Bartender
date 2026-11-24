"""Scheduled squads; declared friends are separate from Discord RSVPs."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from threading import RLock
from pathlib import Path
from zoneinfo import ZoneInfo

from core.json_storage import atomic_write_json
from features import plan_assembly_state as assembly_state
from features.community_directory import stable_key

HK = ZoneInfo('Asia/Hong_Kong')
ACTIVE = {'open', 'due', 'gathering', 'live'}


def confirmed(plan):
    return [uid for uid in plan['members'] if uid not in plan.get('unconfirmed', [])]


def deadline(plan):
    return plan['start'] + (6 * 3600 if plan.get('instant') else 2 * 3600)


def queue_community_room(plan):
    room = plan.get('voice')
    if room and plan.get('community_key'):
        pending = plan.setdefault('community_rooms_pending', [])
        if room not in pending:
            pending.append(room)


def parse_start(value, now=None):
    now = now or datetime.now(HK)
    if now.tzinfo is None:
        raise ValueError('Time must include a timezone')
    now = now.astimezone(HK)
    value = value.strip().replace('：', ':')
    match = re.fullmatch(r'(?:(今晚|今天|今日|明晚|明天|聽日|\d{4}-\d{2}-\d{2})\s*)?(\d{1,2}):(\d{2})', value)
    if not match:
        raise ValueError('請填「22:00」、「明天 22:00」或「2026-11-15 22:00」。')
    day, hour, minute = match.groups()
    try:
        date = now.date()
        if day in {'明晚', '明天', '聽日'}:
            date += timedelta(days=1)
        elif day and day[0].isdigit():
            date = datetime.strptime(day, '%Y-%m-%d').date()
        start = datetime(date.year, date.month, date.day, int(hour), int(minute), tzinfo=HK)
    except ValueError:
        raise ValueError('日期或時間無效；請用24小時制，例如22:00。') from None
    if not now < start <= now + timedelta(days=14):
        raise ValueError('請選未來14日內的時間；今天的時間已過時，請填「明天 22:00」。')
    return int(start.timestamp())


def counts(party, missing):
    try:
        party = int(str(party).strip() or '1')
        missing = None if not str(missing).strip() else int(str(missing).strip())
    except ValueError:
        raise ValueError('人數請填整數。') from None
    if not 1 <= party <= 99 or (missing is not None and not 1 <= missing <= 99):
        raise ValueError('已有人數（包括自己）及尚欠人數，請填1至99。')
    return party, None if missing is None else party + missing


class PlanBook:
    def __init__(self, path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, RLock()
        self.delivery_boot = uuid.uuid4().hex
        # Existing reservations must never be silently replaced with an empty book.
        raw = self.path.read_bytes() if self.path.exists() else None
        state = json.loads(raw) if raw is not None else {'plans': {}, 'schema': 2}
        if not isinstance(state, dict) or not isinstance(state.get('plans'), dict):
            raise ValueError('Invalid squad plan book; original file preserved')
        if type(state.get('schema', 1)) is not int or state.get('schema', 1) not in (1, 2):
            raise ValueError('Unsupported squad plan schema; original file preserved')
        for key, p in state['plans'].items():
            if not isinstance(p, dict) or p.get('id') != key:
                raise ValueError('Invalid squad plan identity; original file preserved')
            for name in ('guild', 'channel', 'owner', 'party'):
                if type(p.get(name)) is not int or p[name] <= 0:
                    raise ValueError('Invalid squad plan fields; original file preserved')
            if type(p.get('start')) not in (int, float) or not math.isfinite(p['start']) or p['start'] <= 0:
                raise ValueError('Invalid squad plan time; original file preserved')
            if (not isinstance(p.get('members'), list)
                    or any(type(uid) is not int or uid <= 0 for uid in p['members'])
                    or len(set(p['members'])) != len(p['members'])
                    or p.get('status') not in ACTIVE | {'posting', 'started', 'history', 'expired', 'ended', 'cancelled'}):
                raise ValueError('Invalid squad plan state; original file preserved')
            if (not isinstance(p.get('game'), str) or not p['game'].strip()
                    or not isinstance(p.get('mode'), str)
                    or p.get('message') is not None and (type(p['message']) is not int or p['message'] <= 0)
                    or p.get('capacity') is not None and (type(p['capacity']) is not int or p['capacity'] <= p['party'])):
                raise ValueError('Invalid squad plan content; original file preserved')
            withdrawn = p.get('withdrawn', [])
            if not isinstance(withdrawn, list) or any(type(uid) is not int or uid <= 0 for uid in withdrawn):
                raise ValueError('Invalid squad reminder withdrawals; original file preserved')
            for field in ('late', 'unconfirmed', 'reminders'):
                values = p.get(field, [])
                if not isinstance(values, list) or any(type(uid) is not int or uid not in p['members'] for uid in values):
                    raise ValueError('Invalid squad plan RSVP state; original file preserved')
            if 'assembly' in p:
                assembly_state.validate_assembly(p)
            if 'community_key' in p:
                stable_key(p['community_key'])
            pending = p.get('community_rooms_pending', [])
            if not isinstance(pending, list) or any(type(room) is not int or room <= 0 for room in pending):
                raise ValueError('Invalid pending community room IDs; original file preserved')
            if 'delivery' in p:
                from features.plan_delivery import validate_delivery
                validate_delivery(p)
        self.state = state
        if state.get('schema', 1) < 2:
            backup = self.path.with_suffix(self.path.suffix + '.before-unified-v2')
            if raw is not None and backup.exists() and backup.read_bytes() != raw:
                backup = backup.with_suffix(backup.suffix + '.' + uuid.uuid4().hex)
            if raw is not None and not backup.exists():
                with backup.open('xb') as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            state = copy.deepcopy(state)
            for p in state['plans'].values():
                if p['status'] == 'started':
                    p['status'] = 'due' if self.clock() <= deadline(p) else 'history'
                p['dirty'] = bool(p.get('message'))
            state['schema'] = 2
            self._write(state)

    def _write(self, state):
        atomic_write_json(self.path, state)
        self.state = state

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.state['plans'].get(key))

    def all(self):
        with self.lock:
            return copy.deepcopy(list(self.state['plans'].values()))

    def create(self, *, guild, channel, owner, game, mode, start, party, capacity, instant=False,
               analytics_test=False, delivery_options=None, owner_label=None, assembly_host=None, community_key=None):
        with self.lock:
            if instant:
                start = int(self.clock())
            self._validate(start, party, capacity, instant=instant)
            if not instant and sum(p['guild'] == guild and p['owner'] == owner and p['status'] in {'posting', 'open'} and p['start'] > self.clock()
                   for p in self.state['plans'].values()) >= 3:
                raise ValueError('你已有3個尚未開始的約局，請先修改或取消舊約局。')
            if instant and any(p['guild'] == guild and p['owner'] == owner
                    and p['status'] in ACTIVE | {'posting'} and p['start'] <= self.clock()
                    and (p['status'] == 'live' or self.clock() <= deadline(p)) for p in self.state['plans'].values()):
                raise ValueError('你已有正在召集的約局，請先從「我的約局」繼續或取消。')
            key = uuid.uuid4().hex
            plan = dict(id=key, guild=guild, channel=channel, owner=owner,
                        game=game, mode=mode, start=start, party=party,
                        capacity=capacity, members=[], status='posting', message=None, dirty=False,
                        instant=instant, late=[], unconfirmed=[], reminders=[], withdrawn=[], revision=0)
            if not instant and assembly_host is not None:
                plan['assembly'] = assembly_state.new_assembly(assembly_host)
            if owner_label:
                plan['owner_label'] = owner_label
            if community_key is not None:
                plan['community_key'] = stable_key(community_key)
            state = copy.deepcopy(self.state)
            state['plans'][key] = plan
            plan.update(created_at=self.clock(), analytics_test=bool(analytics_test), origin='instant' if instant else 'scheduled')
            if delivery_options is not None:
                from features.plan_delivery import options, new_delivery
                validated = options(party, capacity, instant=instant,
                    minimum=delivery_options['minimum'], auto=delivery_options['auto_event'],
                    notices=delivery_options['host_notices'])
                plan['delivery'] = new_delivery(validated)
            self._write(state)
            return copy.deepcopy(plan)

    def publish(self, key, message):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'][key]
            p.update(message=message, status='due' if p['start'] <= self.clock() else 'open')
            self._write(state)

    def _validate(self, start, party, capacity, *, instant=False):
        if not instant and not self.clock() < start <= self.clock() + 14 * 86400:
            raise ValueError('請選未來14日內的時間。')
        if not 1 <= party <= 99 or (capacity is not None and not party < capacity <= party + 99):
            raise ValueError('人數無效。')

    def act(self, key, user, action, *, admin=False, changes=None, generation=None):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            if p is None or p['status'] not in ACTIVE or (p['status'] != 'live' and self.clock() > deadline(p)):
                raise ValueError('此約局已結束，請重新約一局。')
            if generation is not None:
                assembly_state.occurrence(p, generation)
            p.setdefault('late', [])
            p.setdefault('unconfirmed', [])
            p.setdefault('reminders', [])
            p.setdefault('withdrawn', [])
            if action in {'edit', 'cancel'}:
                if p['status'] == 'live':
                    raise ValueError('本局已在進行中；請從語音房管理目前場次。')
                if user != p['owner'] and not (action == 'cancel' and admin):
                    raise ValueError('只有發起人可以修改；管理員可以取消。')
                if action == 'cancel':
                    queue_community_room(p)
                    p['status'] = 'cancelled'
                    if 'assembly' in p:
                        assembly_state.close(p['assembly'])
                else:
                    if set(changes or {}) != {'game', 'mode', 'start', 'party', 'capacity'}:
                        raise ValueError('約局資料不完整。')
                    instant = p.get('instant', False) and changes['start'] == p['start']
                    self._validate(changes['start'], changes['party'], changes['capacity'], instant=changes['start'] == p['start'])
                    material = any(changes[k] != p[k] for k in ('game', 'mode', 'start'))
                    if changes['capacity'] is not None and not material and changes['party'] + len(confirmed(p)) > changes['capacity']:
                        raise ValueError('目標人數不可少於現有參加人數。')
                    if material:
                        queue_community_room(p)
                        p.setdefault('changes', []).append({k: copy.deepcopy(p[k]) for k in ('game', 'mode', 'start', 'members')})
                        p['unconfirmed'] = list(p['members'])
                        p.pop('voice', None)
                        p.pop('session', None)
                        if 'assembly' in p:
                            p['assembly'] = assembly_state.next_occurrence(p['assembly'])
                    if p.get('delivery'):
                        settings = p['delivery']['settings']
                        if settings['minimum'] is not None and settings['minimum'] == p['capacity']:
                            settings['minimum'] = changes['capacity']
                            if settings['minimum'] is None:
                                settings['auto_event'] = False
                        elif changes['capacity'] is not None and settings['minimum'] is not None and settings['minimum'] > changes['capacity']:
                            raise ValueError('最高人數不可少於成局門檻，請先修改成局人數。')
                    p.update(changes)
                    p['instant'] = instant
                    if material or p['status'] != 'gathering':
                        p['status'] = 'due' if p['start'] <= self.clock() else 'open'
            elif action in {'remind_on', 'remind_off'}:
                if user not in confirmed(p):
                    raise ValueError('請先報名或重新確認此約局。')
                if action == 'remind_on':
                    if p['status'] == 'live':
                        raise ValueError('本局已開始；不會補發開局提醒。')
                    p['reminders'] = sorted(set(p['reminders']) | {user})
                    p['withdrawn'] = [uid for uid in p['withdrawn'] if uid != user]
                else:
                    p['reminders'] = [uid for uid in p['reminders'] if uid != user]
                    p['withdrawn'] = sorted(set(p['withdrawn']) | {user})
            elif action in {'join', 'late', 'join_due', 'join_only'}:
                choice = action in {'join_due', 'join_only'}
                if choice and 'assembly' not in p:
                    raise ValueError('此約局未有集合提醒，請從原卡報名。')
                if action == 'join_due':
                    assembly_state.require_future_reminder(p, self.clock())
                if user == p['owner']:
                    raise ValueError('你已計入「已有人數」，無需重複加入。')
                existing = user in p['members'] and user not in p['unconfirmed']
                if choice and existing:
                    assembly_state.set_consent(p['assembly'], user, action == 'join_due')
                    if p != self.state['plans'][key]:
                        self._write(state)
                    return copy.deepcopy(p)
                if existing and ((action == 'late') == (user in p['late'])):
                    raise ValueError('你已加入。')
                if not existing and p['capacity'] is not None and p['party'] + len(confirmed(p)) >= p['capacity']:
                    raise ValueError('此約局已滿人。')
                newly_registered = user not in p['members']
                if newly_registered:
                    p['members'].append(user)
                p['unconfirmed'] = [uid for uid in p['unconfirmed'] if uid != user]
                p['late'] = [uid for uid in p['late'] if uid != user]
                if action == 'late':
                    p['late'].append(user)
                if choice:
                    assembly_state.set_consent(p['assembly'], user, action == 'join_due')
                from features.plan_delivery import record_join
                record_join(p, user, new=newly_registered, clock=self.clock(), boot=self.delivery_boot)
            elif action == 'leave':
                if user not in p['members']:
                    raise ValueError('你尚未按卡加入；發起人可修改原有隊伍人數。')
                p['members'].remove(user)
                if 'assembly' in p:
                    assembly_state.remove_member(p['assembly'], user)
                p['reminders'] = [uid for uid in p['reminders'] if uid != user]
                p['withdrawn'] = sorted(set(p['withdrawn']) | {user})
                p['late'] = [uid for uid in p['late'] if uid != user]
                p['unconfirmed'] = [uid for uid in p['unconfirmed'] if uid != user]
            else:
                raise ValueError('Unknown action')
            p['dirty'] = True
            p['revision'] = p.get('revision', 0) + 1
            self._write(state)
            return copy.deepcopy(p)

    def assembly_action(self, key, user, action, generation):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            if not p:
                raise ValueError('找不到此約局。')
            assembly_state.apply_action(p, user, action, generation, self.clock(), deadline(p))
            if p != self.state['plans'][key]:
                if action in {'wait', 'nudge', 'host_on', 'host_off'}:
                    p.update(dirty=True, revision=p.get('revision', 0) + 1)
                self._write(state)
            return copy.deepcopy(p)

    def assembly_receipt(self, key, generation, kind, expected, new, **fields):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            if not p or type(generation) is not int or p.get('assembly', {}).get('generation') != generation:
                return False
            if not assembly_state.transition(p, kind, expected, new, fields, self.clock(), deadline(p)):
                return False
            self._write(state)
            return True

    def assembly_retire_done(self, key, message_id):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            retired = p.get('assembly', {}).get('retired', []) if p else []
            if type(message_id) is not int or message_id not in retired:
                return False
            retired.remove(message_id)
            self._write(state)
            return True

    def delivery_settings(self, key, user, settings, *, expected_revision):
        from features.plan_delivery import options, new_delivery
        with self.lock:
            p = self.get(key)
            if not p or p['owner'] != user or p['status'] not in {'open', 'due', 'gathering', 'live'}:
                raise ValueError('只有發起人可修改目前約局設定。')
            if p.get('revision', 0) != expected_revision:
                raise ValueError('約局已更新，請重新開啟設定。')
            validated = options(p['party'], p['capacity'], instant=p.get('instant', False),
                minimum=settings['minimum'], auto=settings['auto_event'], notices=settings['host_notices'])
            if 'delivery' not in p:
                p['delivery'] = new_delivery(validated)
                p['delivery']['seen'] = list(p['members'])
            d = p['delivery']
            d['settings'] = validated
            if not validated['host_notices']:
                for item in d['notices']:
                    if item['state'] == 'queued':
                        item['state'] = 'skipped_disabled'
            p.update(dirty=True, revision=p.get('revision', 0) + 1)
            state = copy.deepcopy(self.state); state['plans'][key] = p; self._write(state)
            return copy.deepcopy(p)

    def set_reminder(self,key,user,enabled,*,expected_revision):
        with self.lock:
            p=self.get(key)
            if p['revision']!=expected_revision: raise ValueError('revision_changed')
            if enabled:return self.act(key,user,'remind_on')
            if user not in p['members']:raise ValueError('not_registered')
            p['reminders']=[u for u in p.get('reminders',[]) if u!=user]
            p['withdrawn']=sorted(set(p.get('withdrawn',[]))|{user})
            p['revision']+=1
            state=copy.deepcopy(self.state);state['plans'][key]=p;self._write(state)
            return p

    def availability(self,key,value):
        with self.lock:
            state=copy.deepcopy(self.state);p=state['plans'][key]
            p['availability']=value
            if value in {'card_deleted','denied','unknown_result'}:p['dirty']=False
            self._write(state)

    def clean(self, key, revision=None):
        with self.lock:
            if revision is not None and self.state['plans'][key].get('revision', 0) != revision:
                return
            state = copy.deepcopy(self.state)
            state['plans'][key]['dirty'] = False
            self._write(state)

    def for_voice(self, voice):
        return next((p for p in self.all() if p.get('voice') == voice and p['status'] in {'gathering', 'live'}), None)

    def set_community(self, key, user, community_key, *, expected):
        with self.lock:
            p = self.get(key)
            if (not p or p['owner'] != user or p['status'] not in ACTIVE
                    or p['status'] != 'live' and self.clock() > deadline(p)):
                raise ValueError('只有發起人可以修改進行中約局的公會。')
            if any(p.get(k) != expected.get(k) for k in ('message', 'channel', 'voice', 'game', 'community_key')):
                raise ValueError('本局已更新，請重新開啟公會選單。')
            if p.get('community_key') == community_key:
                return p
            queue_community_room(p)
            if community_key is None:
                p.pop('community_key', None)
            else:
                p['community_key'] = stable_key(community_key)
                queue_community_room(p)
            p.update(dirty=True, revision=p.get('revision', 0) + 1)
            state = copy.deepcopy(self.state)
            state['plans'][key] = p
            self._write(state)
            return copy.deepcopy(p)

    def community_room_synced(self, key, room, expected):
        with self.lock:
            p = self.get(key)
            if (not p or room not in p.get('community_rooms_pending', [])
                    or any(p.get(k) != expected.get(k) for k in ('voice', 'status', 'community_key'))):
                return
            p['community_rooms_pending'].remove(room)
            if not p['community_rooms_pending']:
                del p['community_rooms_pending']
            state = copy.deepcopy(self.state)
            state['plans'][key] = p
            self._write(state)

    def link_voice(self, key, user, voice):
        with self.lock:
            p = self.get(key)
            if not p or p['owner'] != user or p['status'] not in {'open', 'due', 'gathering'}:
                raise ValueError('只有發起人可為尚未開始的約局連接語音。')
            if self.clock() > deadline(p):
                raise ValueError('此約局已逾時，請重新約一局。')
            other = self.for_voice(voice)
            if other and other['id'] != key:
                raise ValueError('此語音房已連接另一個約局。')
            p.update(voice=voice, status='gathering', dirty=True, revision=p.get('revision', 0) + 1)
            queue_community_room(p)
            if 'assembly' in p:
                p['assembly']['opened'] = True
                if self.clock() >= p['start']:
                    p['assembly']['card_due'] = True
                assembly_state.skip_nudge(p['assembly'])
            p.pop('voice_attempt', None)
            state = copy.deepcopy(self.state)
            state['plans'][key] = p
            self._write(state)
            return p

    def begin_voice_attempt(self, key, user):
        """Unknown channel creation results require review, never blind recreation."""
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'][key]
            if p['owner'] != user or p['status'] not in {'open', 'due', 'gathering'} or self.clock() > deadline(p):
                raise ValueError('此約局已無法開局，請重新開啟原卡。')
            if p.get('voice_attempt'):
                raise ValueError('上次建立語音房的結果尚未確認，請由管理員核對；不會重複建房。')
            p['voice_attempt'] = self.clock()
            self._write(state)

    def sync_session(self, key, voice, session, *, ended=False, footprint=None):
        with self.lock:
            p = self.get(key)
            if not p or p.get('voice') != voice or p['status'] not in {'gathering', 'live'}:
                return None
            if p.get('session') not in (None, session):
                return None
            if p.get('session') == session and p['status'] == 'live' and not ended:
                return p
            p.update(status='ended' if ended else 'live', session=session, dirty=True,
                     revision=p.get('revision', 0) + 1)
            if ended:
                queue_community_room(p)
                if 'assembly' in p:
                    assembly_state.close(p['assembly'])
                p['footprint'] = footprint
            state = copy.deepcopy(self.state)
            state['plans'][key] = p
            self._write(state)
            return p

    def release_voice(self, key):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'][key]
            if p['status'] != 'gathering':
                return
            queue_community_room(p)
            p.pop('voice', None)
            p.update(status='due' if p['start'] <= self.clock() else 'open', dirty=True,
                     revision=p.get('revision', 0) + 1)
            self._write(state)

    def expire(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            changed = False
            now = self.clock()
            for p in state['plans'].values():
                overdue = now > deadline(p)
                if overdue and 'assembly' in p and not p['assembly'].get('closed'):
                    assembly_state.close(p['assembly'])
                    changed = True
                status = 'expired' if overdue else 'due'
                if p['status'] in {'open', 'due'} and p['start'] <= now and p['status'] != status:
                    p.update(status=status, dirty=True, revision=p.get('revision', 0) + 1)
                    changed = True
                elif ('assembly' in p and p['status'] in {'gathering', 'live'} and p.get('voice')
                        and now >= p['start'] and not p['assembly'].get('card_due')):
                    # The room keeps its status at the RSVP cutoff, but its original card changes controls.
                    p['assembly']['card_due'] = True
                    p.update(dirty=True, revision=p.get('revision', 0) + 1)
                    changed = True
            if changed:
                self._write(state)


def reminder_recipients(plan):
    """Explicit consent, confirmed for the current revision; old records default off."""
    return set(confirmed(plan)) & set(plan.get('reminders', [])) - set(plan.get('withdrawn', []))


def notification_exclusions(plan):
    return set(plan.get('withdrawn', [])) | set(plan.get('unconfirmed', []))


def public_status(plan):
    """02 read-only summary: no identities, roster, or consent data."""
    return dict(id=plan['id'], status=plan['status'], game=plan['game'], mode=plan['mode'],
                start=plan['start'], registered=len(confirmed(plan)), party=plan['party'],
                capacity=plan['capacity'], attendance=None, revision=plan.get('revision', 0))
