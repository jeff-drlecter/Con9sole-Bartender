"""Versioned reasons for member role changes performed through this bot's UI."""
from dataclasses import dataclass
import re


_PREFIX = 'con9sole:member-role:v1'
_MAX_ID = (1 << 64) - 1
_OPERATIONS = {
    'self': {'verification_grant', 'language_grant', 'language_revoke', 'news_grant', 'news_revoke'},
    'helper': {'role_grant', 'role_revoke', 'verification_revoke'},
    'admin': {'role_grant', 'role_revoke', 'bulk_role_grant', 'bulk_role_revoke', 'verification_revoke'},
}


@dataclass(frozen=True)
class RoleAuditReason:
    actor_id: int
    actor_kind: str
    operation: str


def encode_role_audit_reason(actor_id: int, actor_kind: str, operation: str) -> str:
    if type(actor_id) is not int or not 0 < actor_id <= _MAX_ID:
        raise ValueError('Invalid Discord actor ID')
    if operation not in _OPERATIONS.get(actor_kind, ()):
        raise ValueError('Unsupported role audit operation for actor')
    return f'{_PREFIX} {actor_id} {actor_kind} {operation}'


def parse_role_audit_reason(reason: str | None) -> RoleAuditReason | None:
    """Call only after verifying the Discord audit executor is this bot."""
    if not isinstance(reason, str) or len(reason) > 100:
        return None
    fields = reason.split(' ')
    if len(fields) != 4 or fields[0] != _PREFIX:
        return None
    _, actor, actor_kind, operation = fields
    if not re.fullmatch('[1-9][0-9]{0,19}', actor):
        return None
    actor_id = int(actor)
    if actor_id > _MAX_ID or operation not in _OPERATIONS.get(actor_kind, ()):
        return None
    return RoleAuditReason(actor_id, actor_kind, operation)
