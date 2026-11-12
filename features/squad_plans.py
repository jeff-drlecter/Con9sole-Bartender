"""Scheduled squads; declared friends are separate from Discord RSVPs."""
from __future__ import annotations

import copy
import re
import time
import uuid
from datetime import datetime, timedelta
from threading import RLock
from zoneinfo import ZoneInfo

from core.json_storage import atomic_write_json, load_json_object

HK = ZoneInfo('Asia/Hong_Kong')


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
        raise ValueError('請選未來14日內嘅時間；過咗今晚請填「明天 22:00」。')
    return int(start.timestamp())


def counts(party, missing):
    try:
        party = int(str(party).strip() or '1')
        missing = None if not str(missing).strip() else int(str(missing).strip())
    except ValueError:
        raise ValueError('人數請填整數。') from None
    if not 1 <= party <= 99 or (missing is not None and not 1 <= missing <= 99):
        raise ValueError('已有幾人（包括自己）及仲差幾人，請填1至99。')
    return party, None if missing is None else party + missing


class PlanBook:
    def __init__(self, path, clock=time.time):
        self.path, self.clock, self.lock = path, clock, RLock()
        self.state = load_json_object(path, lambda: {'plans': {}})

    def _write(self, state):
        atomic_write_json(self.path, state)
        self.state = state

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.state['plans'].get(key))

    def all(self):
        with self.lock:
            return copy.deepcopy(list(self.state['plans'].values()))

    def create(self, *, guild, channel, owner, game, mode, start, party, capacity):
        with self.lock:
            self._validate(start, party, capacity)
            if sum(p['owner'] == owner and p['status'] in {'posting', 'open'} and p['start'] > self.clock()
                   for p in self.state['plans'].values()) >= 3:
                raise ValueError('你已有3個未開始嘅約局，請先修改或取消舊約局。')
            key = uuid.uuid4().hex
            plan = dict(id=key, guild=guild, channel=channel, owner=owner,
                        game=game, mode=mode, start=start, party=party,
                        capacity=capacity, members=[], status='posting', message=None, dirty=False)
            state = copy.deepcopy(self.state)
            state['plans'][key] = plan
            self._write(state)
            return copy.deepcopy(plan)

    def publish(self, key, message):
        with self.lock:
            state = copy.deepcopy(self.state)
            state['plans'][key].update(message=message, status='open')
            self._write(state)

    def _validate(self, start, party, capacity):
        if not self.clock() < start <= self.clock() + 14 * 86400:
            raise ValueError('請選未來14日內嘅時間。')
        if not 1 <= party <= 99 or (capacity is not None and not party < capacity <= party + 99):
            raise ValueError('人數無效。')

    def act(self, key, user, action, *, admin=False, changes=None):
        with self.lock:
            state = copy.deepcopy(self.state)
            p = state['plans'].get(key)
            if p is None or p['status'] != 'open' or p['start'] <= self.clock():
                raise ValueError('呢個約局已結束或已到開始時間。')
            if action in {'edit', 'cancel'}:
                if user != p['owner'] and not (action == 'cancel' and admin):
                    raise ValueError('只有發起人可以修改；管理員可以取消。')
                if action == 'cancel':
                    p['status'] = 'cancelled'
                else:
                    if set(changes or {}) != {'game', 'mode', 'start', 'party', 'capacity'}:
                        raise ValueError('約局資料不完整。')
                    self._validate(changes['start'], changes['party'], changes['capacity'])
                    if changes['capacity'] is not None and changes['party'] + len(p['members']) > changes['capacity']:
                        raise ValueError('目標人數少過現有已參加人數。')
                    p.update(changes)
            elif action == 'join':
                if user == p['owner']:
                    raise ValueError('你已計入「已有幾人」，唔使再加入。')
                if user in p['members']:
                    raise ValueError('你已經加入咗。')
                if p['capacity'] is not None and p['party'] + len(p['members']) >= p['capacity']:
                    raise ValueError('呢個約局已滿人。')
                p['members'].append(user)
            elif action == 'leave':
                if user not in p['members']:
                    raise ValueError('你未有按卡加入；發起人可用修改調整已有人數。')
                p['members'].remove(user)
            else:
                raise ValueError('Unknown action')
            p['dirty'] = True
            self._write(state)
            return copy.deepcopy(p)

    def clean(self, key):
        with self.lock:
            state = copy.deepcopy(self.state)
            state['plans'][key]['dirty'] = False
            self._write(state)

    def expire(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            changed = False
            for p in state['plans'].values():
                if p['status'] == 'open' and p['start'] <= self.clock():
                    p.update(status='started', dirty=True)
                    changed = True
            if changed:
                self._write(state)
