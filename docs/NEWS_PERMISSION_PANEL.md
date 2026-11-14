# News channel permission management

`/news_permissions` opens a private administrator-only preview with buttons to
refresh, apply the displayed plan, or restore that plan. After restart, restore
using `/news_permissions action:restore plan_id:<id>`. Plans belong to the invoking
administrator and guild; application expires after 30 minutes. The panel expires
after ten minutes. Current Administrator/Manage Server authority is re-fetched on
entry and before every write. The existing permission-audit lock and durable
write-ahead journal are reused.

Only View Channel overwrites on the three fixed PS, Xbox and PC news channels
can change. Everyone is denied, the matching opt-in role is allowed, and Helpers
plus nonmatching news roles are neutral. Old news-sub/no-news-sub and Verified
allows are cleared; their explicit denies remain. Other permission bits, role
membership, category settings and the official Discord information channel are
not edited. Staff/service grants remain. Unknown ordinary-role or member allows
block application for review. No roles are deleted, and this is not recurring
automatic enforcement. Members still use `/news_channels` to select categories.

Changed snapshots, moved/synced channels, invalid subscription roles and ambiguous
write outcomes stop execution. Restore checks the current overwrite before
reversing only attempted operations. Discord does not offer atomic comparison
and update; concurrent manual changes can still race between read and write.
Do not change these permissions concurrently. The fingerprint is intentionally
conservative: unrelated role changes can require a fresh preview.

The new cog has no startup mutations, persistent background task, announcements
or member messages. Deployment uses the existing full-service Fly workflow and
therefore restarts Bartender. Existing transient panels may need reopening and
Bot interactions can briefly be unavailable. No voice-room, reservation, RSS or
recruitment implementation is modified. Their live continuity is not established
by the permission tests.

Validation: focused tests cover preview isolation, bit preservation, apply and
restore, changed snapshots, authority revocation, ambiguous HTTP/write outcomes,
restore conflicts, member/unknown role grants, missing/synced channels, invalid
roles, official-channel exclusion and panel ownership. These are program tests,
not ordinary-member or iPhone visibility tests.
