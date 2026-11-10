"""Bounded, memory-only repeated-text evidence; never enforcement."""
from collections import OrderedDict, deque
import hashlib
import unicodedata


class RepeatedMessages:
    window = 15
    threshold = 5
    cooldown = 120
    capacity = 10000

    def __init__(self):
        self.members = OrderedDict()

    def observe(self, user, message, content, now):
        normalized = ' '.join(unicodedata.normalize('NFKC', content).casefold().split())
        if not normalized:
            return None
        digest = hashlib.sha256(normalized.encode()).digest()
        for key in list(self.members):
            if now - self.members[key]['seen'] > self.cooldown:
                del self.members[key]
            else:
                break
        row = self.members.setdefault(user, dict(events=deque(maxlen=100), seen=now, alert=-float('inf')))
        self.members.move_to_end(user)
        row['seen'] = now
        while len(self.members) > self.capacity:
            self.members.popitem(last=False)
        events = row['events']
        while events and now - events[0][0] > self.window:
            events.popleft()
        if any(e[1] == message for e in events):
            return None
        events.append((now, message, digest))
        count = sum(e[2] == digest for e in events)
        if count < self.threshold or now - row['alert'] < self.cooldown:
            return None
        # Reserve before network IO; ambiguous sends are never retried blindly.
        row['alert'] = now
        return count
