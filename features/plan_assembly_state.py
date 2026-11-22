"""Consent, waiting and delivery receipts for one scheduled plan occurrence."""
from __future__ import annotations

import math


def new_assembly(host):
    if type(host) is not bool:
        raise ValueError('集合提醒設定無效。')
    return dict(generation=1, host=host, members=[], waiting=[], due={}, nudge={}, retired=[])


def next_occurrence(assembly):
    current = new_assembly(assembly['host'])
    current['generation'] = assembly['generation'] + 1
    current['retired'] = list(assembly['retired'])
    message = assembly['due'].get('message')
    if message and not assembly.get('closed') and message not in current['retired']:
        current['retired'].append(message)
    return current


def close(assembly):
    if not assembly.get('closed'):
        assembly['closed'] = True
        message = assembly['due'].get('message')
        if message and message not in assembly['retired']:
            assembly['retired'].append(message)
        skip_nudge(assembly)


def unopened(plan):
    return bool(plan.get('assembly') and not plan['assembly'].get('opened') and not plan['assembly'].get('closed')
                and plan['status'] in {'open', 'due'}
                and not (plan.get('voice') or plan.get('voice_attempt') or plan.get('session')))


def room_available(plan):
    return bool(plan.get('voice') and plan['status'] in {'gathering', 'live'}
                and not plan.get('assembly', {}).get('closed'))


def _positive_id(value):
    return type(value) is int and value > 0


def _ids(values):
    return (isinstance(values, list) and all(_positive_id(uid) for uid in values)
            and len(set(values)) == len(values))


def validate_assembly(plan):
    a = plan['assembly']
    try:
        confirmed = set(plan['members']) - set(plan.get('unconfirmed', [])) - {plan['owner']}
        if (plan.get('instant') or not _positive_id(a['generation']) or type(a['host']) is not bool
                or any(type(a.get(k, False)) is not bool for k in ('opened', 'closed')) or not _ids(a['retired'])
                or plan.get('message') in a['retired']
                or any(not _ids(a[k]) or not confirmed.issuperset(a[k]) for k in ('members', 'waiting'))):
            raise ValueError('Invalid assembly')
        for kind in ('due', 'nudge'):
            r = a[kind]
            if not isinstance(r, dict):
                raise ValueError('Invalid receipt')
            if not r:
                continue
            state = r['state']
            if state not in {'sending', 'sent', 'unknown', 'failed', 'skipped'} and not (
                    kind == 'nudge' and state == 'requested'):
                raise ValueError('Invalid delivery state')
            if kind == 'nudge' and (not _positive_id(r['actor']) or r['actor'] == plan['owner']
                    or state == 'requested' and (not a['host'] or r['actor'] not in confirmed)):
                raise ValueError('Invalid nudge actor')
            if 'requested_at' in r and (kind != 'nudge' or type(r['requested_at']) not in (int, float)
                    or not math.isfinite(r['requested_at'])):
                raise ValueError('Invalid nudge time')
            if 'message' in r and (
                    state != 'sent' or not _positive_id(r['message']) or r['message'] == plan.get('message')):
                raise ValueError('Invalid receipt message')
            if kind == 'due' and state == 'sent' and (
                    not _positive_id(r.get('message')) or not a.get('closed') and r['message'] in a['retired']):
                raise ValueError('Invalid due message')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError('Invalid plan assembly state; original file preserved') from exc


def occurrence(plan, generation):
    a = plan.get('assembly') if plan else None
    if not a or type(generation) is not int or a['generation'] != generation:
        raise ValueError('約局已更新，請重新開啟原卡。')
    return a


def require_future_reminder(plan, now):
    if now >= plan['start'] or plan['assembly']['due'] or not (unopened(plan) or room_available(plan)):
        raise ValueError('已過到鐘提醒的報名時間，請選「只報名」。')


def set_consent(assembly, user, enabled):
    users = assembly['members']
    if enabled and user not in users:
        users.append(user)
    elif not enabled and user in users:
        users.remove(user)


def skip_nudge(assembly):
    if assembly['nudge'].get('state') == 'requested':
        assembly['nudge']['state'] = 'skipped'


def remove_member(assembly, user):
    set_consent(assembly, user, False)
    if user in assembly['waiting']:
        assembly['waiting'].remove(user)
    if assembly['nudge'].get('actor') == user:
        skip_nudge(assembly)


def apply_action(plan, user, action, generation, now, deadline):
    a = occurrence(plan, generation)
    if now > deadline or not (unopened(plan) or room_available(plan)):
        raise ValueError('此約局的集合已結束。')
    if action in {'host_on', 'host_off'}:
        if user != plan['owner']:
            raise ValueError('只有發起人可以修改召集設定。')
        a['host'] = action == 'host_on'
        if not a['host']:
            skip_nudge(a)
        return
    if user == plan['owner'] or user not in plan['members'] or user in plan.get('unconfirmed', []):
        raise ValueError('請先報名或重新確認此約局。')
    if action in {'due_on', 'due_off'}:
        if action == 'due_on':
            require_future_reminder(plan, now)
        set_consent(a, user, action == 'due_on')
        return
    if not unopened(plan) or now < plan['start']:
        raise ValueError('只可在約定時間到達而尚未開房時使用。')
    if action == 'wait':
        if user not in a['waiting']:
            a['waiting'].append(user)
    elif action == 'nudge':
        if not a['host']:
            raise ValueError('發起人已關閉召集提醒。')
        if now < plan['start'] + 300:
            raise ValueError('約定時間過了五分鐘才可提醒發起人。')
        if a['nudge']:
            raise ValueError('這次約局已有人提出提醒。')
        a['nudge'] = dict(state='requested', actor=user, requested_at=now)
    else:
        raise ValueError('Unknown assembly action')


def transition(plan, kind, expected, new, fields, now, deadline):
    if kind not in {'due', 'nudge'}:
        return False
    a = plan['assembly']
    receipt = a[kind]
    if receipt.get('state') != expected:
        return False
    initial = None if kind == 'due' else 'requested'
    if expected == initial and new in {'sending', 'skipped'}:
        if new == 'sending':
            if not plan['start'] <= now <= deadline:
                return False
            if kind == 'due' and not (unopened(plan) or room_available(plan)):
                return False
            if kind == 'nudge' and not (unopened(plan) and a['host'] and now >= plan['start'] + 300):
                return False
    elif expected != 'sending' or new not in {'sent', 'unknown', 'failed', 'skipped'}:
        return False
    if fields.keys() - {'message'}:
        raise ValueError('Invalid assembly receipt fields')
    receipt.update(state=new, **fields)
    validate_assembly(plan)
    if a.get('closed') and kind == 'due' and new == 'sent' and receipt['message'] not in a['retired']:
        a['retired'].append(receipt['message'])
    return True
