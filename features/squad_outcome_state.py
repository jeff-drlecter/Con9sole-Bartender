"""Read-only evidence contract. Intent, room use and co-play are separate facts.

No new thresholds, notifications, XP or historical attendance reconstruction.
"""
from features.squad_plans import deadline


def plan_outcome(plan):
    if plan.get('status') in ('live', 'ended') and plan.get('session'):
        return 'opened'
    if plan.get('status') == 'cancelled':
        return 'cancelled'
    if plan.get('status') == 'expired':
        return 'unopened'
    return 'unknown'


def evidence(plan, *, as_of):
    """Internal roster-free query; caller must authorize any member-facing access."""
    status = plan.get('status')
    return dict(outcome=plan_outcome(plan), matured=deadline(plan) <= as_of,
                phase=({'open': 'scheduled', 'due': 'recruiting', 'gathering': 'waiting_in_voice',
                        'live': 'room_in_use', 'ended': 'ended', 'cancelled': 'cancelled',
                        'expired': 'unopened'}.get(status, 'unknown')),
                session=plan.get('session'), attendance=None, co_participation=None)


def session_origin(session, plan, guild_id):
    """Missing/mismatched links are unknown, never reclassified as natural voice."""
    if session.get('ended') is not None:
        return 'ended'
    if session.get('plan_id'):
        if (plan and plan.get('guild') == guild_id and plan.get('id') == session['plan_id']
                and plan.get('status') == 'live' and plan.get('session') == session.get('id')):
            return 'linked'
        return 'unknown'
    # Existing card is evidence that the existing one-human opening flow ran.
    return 'natural' if session.get('id') and session.get('message') else 'waiting'
