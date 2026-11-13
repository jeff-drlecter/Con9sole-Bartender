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

HK = ZoneInfo('Asia/Hong_Kong')
ACTIVE = {'open', 'due', 'gathering', 'live'}


def confirmed(plan):
    return [uid for uid in plan['members'] if uid not in plan.get('unconfirmed', [])]


def deadline(plan):
    return plan['start'] + (6 * 3600 if plan.get('instant') else 2 * 3600)


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
            for field in ('late', 'unconfirmed'):
                values = p.get(field, [])
                if not isinstance(values, list) or any(type(uid) is not int or uid not in p['members'] for uid in values):
                    raise ValueError('Invalid squad plan RSVP state; original file preserved')
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

    def create(self, *, guild, channel, owner, game, mode, start, party, capacity, instant=False):
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
                        instant=instant, late=[], unconfirmed=[], revision=0)
            state = copy.deepcopy(self.state)
            state['plans'][key] = plan
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

    def act(self, key, user, action, *, admin=False, changes=None):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            if p is None or p['status'] not in ACTIVE or (p['status'] != 'live' and self.clock() > deadline(p)):
                raise ValueError('此約局已結束，請重新約一局。')
            p.setdefault('late', [])
            p.setdefault('unconfirmed', [])
            if action in {'edit', 'cancel'}:
                if p['status'] == 'live':
                    raise ValueError('本局已在進行中；請從語音房管理目前場次。')
                if user != p['owner'] and not (action == 'cancel' and admin):
                    raise ValueError('只有發起人可以修改；管理員可以取消。')
                if action == 'cancel':
                    p['status'] = 'cancelled'
                else:
                    if set(changes or {}) != {'game', 'mode', 'start', 'party', 'capacity'}:
                        raise ValueError('約局資料不完整。')
                    instant = p.get('instant', False) and changes['start'] == p['start']
                    self._validate(changes['start'], changes['party'], changes['capacity'], instant=changes['start'] == p['start'])
                    material = any(changes[k] != p[k] for k in ('game', 'mode', 'start'))
                    if changes['capacity'] is not None and not material and changes['party'] + len(confirmed(p)) > changes['capacity']:
                        raise ValueError('目標人數不可少於現有參加人數。')
                    if material:
                        p.setdefault('changes', []).append({k: copy.deepcopy(p[k]) for k in ('game', 'mode', 'start', 'members')})
                        p['unconfirmed'] = list(p['members'])
                        p.pop('voice', None)
                        p.pop('session', None)
                    p.update(changes)
                    p['instant'] = instant
                    if material or p['status'] != 'gathering':
                        p['status'] = 'due' if p['start'] <= self.clock() else 'open'
            elif action in {'join', 'late'}:
                if user == p['owner']:
                    raise ValueError('你已計入「已有人數」，無需重複加入。')
                existing = user in p['members'] and user not in p['unconfirmed']
                if existing and ((action == 'late') == (user in p['late'])):
                    raise ValueError('你已加入。')
                if not existing and p['capacity'] is not None and p['party'] + len(confirmed(p)) >= p['capacity']:
                    raise ValueError('此約局已滿人。')
                if user not in p['members']:
                    p['members'].append(user)
                p['unconfirmed'] = [uid for uid in p['unconfirmed'] if uid != user]
                p['late'] = [uid for uid in p['late'] if uid != user]
                if action == 'late':
                    p['late'].append(user)
            elif action == 'leave':
                if user not in p['members']:
                    raise ValueError('你尚未按卡加入；發起人可修改原有隊伍人數。')
                p['members'].remove(user)
                p['late'] = [uid for uid in p['late'] if uid != user]
                p['unconfirmed'] = [uid for uid in p['unconfirmed'] if uid != user]
            else:
                raise ValueError('Unknown action')
            p['dirty'] = True
            p['revision'] = p.get('revision', 0) + 1
            self._write(state)
            return copy.deepcopy(p)

    def clean(self, key, revision=None):
        with self.lock:
            if revision is not None and self.state['plans'][key].get('revision', 0) != revision:
                return
            state = copy.deepcopy(self.state)
            state['plans'][key]['dirty'] = False
            self._write(state)

    def for_voice(self, voice):
        return next((p for p in self.all() if p.get('voice') == voice and p['status'] in {'gathering', 'live'}), None)

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
            p.pop('voice', None)
            p.update(status='due' if p['start'] <= self.clock() else 'open', dirty=True,
                     revision=p.get('revision', 0) + 1)
            self._write(state)

    def expire(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            changed = False
            for p in state['plans'].values():
                status = 'expired' if self.clock() > deadline(p) else 'due'
                if p['status'] in {'open', 'due'} and p['start'] <= self.clock() and p['status'] != status:
                    p.update(status=status, dirty=True, revision=p.get('revision', 0) + 1)
                    changed = True
            if changed:
                self._write(state)
