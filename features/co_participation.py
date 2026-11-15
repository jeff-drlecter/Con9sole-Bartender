"""Observed overlapping presence, not RSVP, full teams, XP or proof of gameplay.

Only confirmed milestones persist. Incomplete windows are intentionally process-local.
"""
from itertools import combinations

THRESHOLD = 120
MAX_SAMPLE_GAP = 10
REJOIN_GRACE = 30
RULE = 'same-pair-120s-v1'


class CoParticipation:
    def __init__(self):
        self.rooms = {}
        self.last_sample = None

    def reset(self):
        self.rooms.clear()
        self.last_sample = None

    def sample(self, samples, locations, now):
        """samples: {(guild, session, voice): set(current human IDs)}.

        A stable pair must overlap at both ends of each <=10-second interval.
        One-person disconnects can pause up to 30 seconds; no gap time counts.
        Cross-room movement, both absent, unknown samples and restart reset progress.
        """
        if self.last_sample is not None and not 0 <= now-self.last_sample <= MAX_SAMPLE_GAP:
            self.reset()
        self.last_sample = now
        self.rooms = {key: value for key, value in self.rooms.items() if key in samples}
        milestones = []
        for key, members in samples.items():
            room = self.rooms.setdefault(key, dict(pairs={}, qualified=None))
            if room['qualified'] is not None:
                milestones.append((key, room['qualified']))
                continue
            pairs = room['pairs']
            for pair, progress in list(pairs.items()):
                present = set(pair) <= members
                moved = any(locations.get(uid) not in (None, key[2]) for uid in pair)
                if moved or not set(pair) & members:
                    del pairs[pair]
                    continue
                if not present:
                    if progress['break'] is None:
                        progress['break'] = now
                    if now-progress['break'] > REJOIN_GRACE:
                        del pairs[pair]
                    progress['last'] = now
                    continue
                if progress['break'] is not None:
                    if now-progress['break'] > REJOIN_GRACE:
                        del pairs[pair]
                        continue
                    progress['break'] = None  # resumed; this interval is not credited
                else:
                    progress['seconds'] += now-progress['last']
                progress['last'] = now
                if progress['seconds'] >= THRESHOLD:
                    room['qualified'] = now
                    milestones.append((key, now))
                    pairs.clear()
                    break
            if room['qualified'] is None:
                for pair in combinations(sorted(members), 2):
                    pairs.setdefault(pair, dict(seconds=0, last=now, **{'break': None}))
        return milestones
