# Member-selected news channels

The native optional-area question expands its old single news answer into three
independent choices: PlayStation, Xbox and PC (including Steam/Epic as those new
sources pass release acceptance). Chat, streaming and tester options and their
original IDs/mappings remain unchanged. The retired all-news show/hide question
is removed to avoid competing role assignments. All choices remain optional.

The existing ps-news, xbox-news and 電腦-news channels are retained. Each uses a
new zero-permission news role, scoped by channel View Channel overrides. Other
permission bits and all unrelated channels remain unchanged. Default visibility
is denied, ordinary legacy/game-role grants are removed from these three channels,
and only the matching news role unlocks each. Existing staff and Bot readers
retain their visibility. Individual ordinary-member exceptions cause preflight
failure instead of being silently overwritten.

The one-time apply script backs up native onboarding, channel overwrites, role
metadata and previous-reader IDs in `/data/news_channel_categories/before.json`.
It preserves previous actual readership by assigning corresponding news roles;
it never replaces a member's whole role list. New role names must be unique and
permissionless and must not appear in unrelated channel overrides. It rereads
configuration before writes and verifies native mappings and modeled access
against real channel overwrites. No member names, IDs, tokens or backup contents
are printed in deployment logs. Once applied, later deploys do not reapply it.

`/news_channels` and /menu → 更多玩法 → 資訊與設定 → 新聞頻道接收 provide a private
selector using actual current roles, including for migrated members. Clearing all
choices removes only the three news roles. Every operation verifies the owner,
guild, current role permissions/hierarchy and unrelated-channel scope before
using per-role add/remove endpoints, then rereads membership. Existing game,
Verified, Helper and other roles are preserved. Personal RSS filters are separate.

Native questionnaire answer history is separate from manually migrated role state;
the Bot selector reads authoritative current roles. Reopening the selector shows
current selections. Changing a subscription does not mean a member received a
phone notification; Discord's own channel notification settings still apply.

Tests distinguish optional-area serialization, actual role change endpoints and
modeled channel permissions from ordinary-member/iPhone UI testing. Configuration
changes do not authorize an announcement and do not change MonitoRSS publishing,
RSS source release flags or the proposed digest dispatch destination.
