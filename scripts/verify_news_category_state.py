"""Read the completed migration marker. Never recover or apply Discord settings.

Standalone stdlib code so the checked-out verifier can run on the old machine
before the new image is deployed. No tokens, network, or writes are needed.
"""
import json
from pathlib import Path


CHANNELS = {'ps': 1364201334798290994, 'xbox': 1379699174668505098,
            'pc': 1364210080043630612}


def verify(path):
    state = json.loads(Path(path).read_text())
    roles = state.get('role_ids', {})
    if (state.get('version') != 1 or state.get('channel_ids') != CHANNELS
            or set(roles) != set(CHANNELS)):
        raise ValueError('News migration marker missing or incompatible; review privately before deployment.')
    ids = [str(value) for value in roles.values()]
    if (any(not value.isdecimal() or int(value) <= 0 for value in ids)
            or len(set(map(int, ids))) != len(CHANNELS)):
        raise ValueError('News migration role mapping is invalid; no migration attempted.')
    return state


if __name__ == '__main__':
    verify('/data/news_channel_categories/applied.json')
    print('Existing news migration marker verified. No Discord settings or messages changed.')
