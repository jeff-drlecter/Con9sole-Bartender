"""Validate one existing Bot machine; emit only a safe rollback identity.

Read `flyctl machine list --json` from stdin. Never print raw configuration.
"""
import json
import os
import re
import sys


def validate(machines):
    if not isinstance(machines, list) or len(machines) != 1:
        raise ValueError('Expected exactly one existing Bot machine')
    machine = machines[0]
    identity = machine.get('id', '')
    config = machine.get('config', {})
    image = config.get('image', '')
    mounts = config.get('mounts', [])
    if not re.fullmatch('[0-9a-f]+', identity) or machine.get('state') != 'started':
        raise ValueError('Existing Bot machine is not started')
    if not re.fullmatch(r'registry\.fly\.io/con9sole-bartender[:@][A-Za-z0-9:._-]+', image):
        raise ValueError('Rollback image is unavailable or unexpected')
    if len(mounts) != 1 or mounts[0].get('path') != '/data' or not mounts[0].get('volume'):
        raise ValueError('Expected the existing persistent /data volume')
    return {'machine': identity, 'rollback_image': image,
            'persistent_volume': mounts[0]['volume']}


if __name__ == '__main__':
    result = validate(json.load(sys.stdin))
    print(json.dumps(result))
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            # Only validated, newline-free values become workflow outputs.
            out.write('machine=' + result['machine'] + '\n')
