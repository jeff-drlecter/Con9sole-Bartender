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
    group_id: int | None = None


def encode_role_audit_reason(actor_id: int, actor_kind: str, operation: str, *, group_id: int | None = None) -> str:
    if type(actor_id) is not int or not 0 < actor_id <= _MAX_ID:
        raise ValueError('Invalid Discord actor ID')
    if operation not in _OPERATIONS.get(actor_kind, ()):
        raise ValueError('Unsupported role audit operation for actor')
    reason = f'{_PREFIX} {actor_id} {actor_kind} {operation}'
    if group_id is not None:
        if not operation.startswith('bulk_') or type(group_id) is not int or not 0 < group_id <= _MAX_ID:
            raise ValueError('Invalid bulk selection role')
        reason += f' {group_id}'
    return reason


def parse_role_audit_reason(reason: str | None) -> RoleAuditReason | None:
    """Call only after verifying the Discord audit executor is this bot."""
    if not isinstance(reason, str) or len(reason) > 100:
        return None
    fields = reason.split(' ')
    if len(fields) not in (4, 5) or fields[0] != _PREFIX:
        return None
    _, actor, actor_kind, operation, *group = fields
    if not all(re.fullmatch('[1-9][0-9]{0,19}', value) for value in (actor, *group)):
        return None
    actor_id = int(actor)
    if actor_id > _MAX_ID or operation not in _OPERATIONS.get(actor_kind, ()):
        return None
    group_id = int(group[0]) if group else None
    if group_id is not None and (not operation.startswith('bulk_') or group_id > _MAX_ID):
        return None
    return RoleAuditReason(actor_id, actor_kind, operation, group_id)
