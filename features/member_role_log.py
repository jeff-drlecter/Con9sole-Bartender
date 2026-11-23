"""Render private member-role changes using the executor on that audit entry."""

import config
from core.permissions import is_helper, is_server_admin
from features.audit_format import role_label, user_identity, who
from features.role_audit_reason import parse_role_audit_reason

_ACTION_LABELS = {
    'verification_grant': '我是人類', 'verification_revoke': '撤回會員驗證',
    'role_grant': '派發身份組', 'role_revoke': '移除身份組',
    'bulk_role_grant': '批量派發身份組', 'bulk_role_revoke': '批量移除身份組',
    'language_grant': '語言偏好', 'language_revoke': '語言偏好',
    'news_grant': '新聞頻道選擇', 'news_revoke': '新聞頻道選擇',
}


def role_changes(before_roles, after_roles):
    before = {role.id: role for role in before_roles}
    after = {role.id: role for role in after_roles}
    added = [after[rid] for rid in sorted(after.keys() - before.keys())]
    removed = [before[rid] for rid in sorted(before.keys() - after.keys())]
    return added, removed


def role_delta_key(member_id, added, removed):
    if not (member_id and (added or removed)):
        return None
    return ':'.join((str(member_id), ','.join(str(r.id) for r in added), ','.join(str(r.id) for r in removed)))


def role_change_lines(added, removed):
    lines = []
    if added:
        lines.append('🟢 新增身份組：' + ', '.join(map(role_label, added)))
    if removed:
        lines.append('🔴 移除身份組：' + ', '.join(map(role_label, removed)))
    return lines


def attribution(entry, bot_id, actor, actor_id, target_id, added, removed):
    """Only our bot can attest to an interaction. Never redistribute free-form reasons."""
    if not actor_id:
        return '來源未確認', '未能從審核紀錄確認'
    if actor_id == bot_id:
        source = parse_role_audit_reason(entry.reason)
        unknown = ('俱樂部助手執行', '未有可核實的發起人紀錄')
        if not source or not target_id or (source.actor_kind == 'self' and source.actor_id != target_id):
            return unknown
        changed = added if source.operation.endswith('_grant') else removed
        if len(added) + len(removed) != 1 or not changed:
            return unknown
        if source.operation.startswith('verification_') and changed[0].id != config.VERIFIED_ROLE_ID:
            return unknown
        label = {'self': '會員自助', 'helper': 'Helper 經 Bot', 'admin': '管理員經 Bot'}[source.actor_kind]
        member = entry.guild.get_member(source.actor_id)
        return f'{label}（{_ACTION_LABELS[source.operation]}）', who(member) if member else user_identity(source.actor_id)
    if getattr(actor, 'bot', None) is True:
        return '其他 Bot 執行', '未有可核實的發起人紀錄'
    if getattr(actor, 'bot', None) is not False:
        return 'Discord 審核只提供執行帳戶', '未確認'
    if is_server_admin(actor):
        source = 'Discord 直接操作（記錄時為管理員）'
    elif is_helper(actor):
        source = 'Discord 直接操作（記錄時為 Helper）'
    else:
        source = 'Discord 帳戶直接操作'
    return source, who(actor)
