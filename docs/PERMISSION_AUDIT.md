# Anti-scam Update — Permission Audit

Admin command: `/permission_audit`, or More → Management tools → 權限審核.
Requires current Administrator or Manage Server in the configured guild. The
actor is fetched again before attachment delivery. Helpers/Mods cannot export.
The report is an ephemeral ZIP with Markdown findings and versioned JSON.
No permissions, roles, messages or XP are changed. A guild-wide 60-second
cooldown and single-flight lock prevent repeated exports. No credentials,
message history or full member lists are exported. Private configuration is
only delivered to the authorized invoking administrator.

Coverage:
- Fresh REST roles and guild channels, including categories, forum/media
  settings supported by the installed discord.py, voice and text settings.
- Complete explicit permission overwrites, including uncached member targets.
- Onboarding prompts/options and AutoMod rule metadata where API access exists.
  Missing support/HTTP failures are recorded instead of treated as empty.
- Raw role permission scenarios for everyone-only and everyone+Verified.
  These are NOT actual per-member effective access: member overrides, owner,
  timeouts, implicit channel dependencies and thread membership are excluded.
- Administrator bypass and combined role allow/deny precedence are respected.
- No archived/private thread enumeration, per-member role census, DM visibility,
  Bot application-command authorization, or external moderation policy audit.
- Guild metadata is from the gateway cache; roles/channels are fetched sequentially,
  so this is a time-bounded snapshot rather than an atomic transaction.

Findings are conservative. Privileged roles, member overrides and unsynced
channels are review items, not proven bugs. Everyone management/mention powers,
missing Verified, and onboarding granting sensitive roles require investigation.
The unverified PTT finding compares an everyone-only voice scenario against the
approved goal of voice activity without Verified; role combinations can differ.
This release exports evidence and does not implement auto-verification, link
blocking, role revocation, or any server permission changes.

## Narrow remediation

`/anti_scam_fix action:preview` creates an actor/guild-bound, 30-minute plan.
`action:apply plan_id:<id>` applies only that saved plan. `action:restore` reverses
attempted/verified operations only when the current value still matches the
recorded result (or already matches the original). Each operation has a durable
write-ahead receipt and readback. Conflicts/unknown results stop apply and block
blind replay; partial results are retained. Discord has no atomic compare-and-swap
for permissions, so manual concurrent edits must be avoided during execution.

Scope is fixed reviewed ordinary game role IDs plus Verified mention overwrites,
and the @everyone voice-activation bit. Staff/managed candidates are skipped.
No visibility, connect, speak, membership, onboarding or moderation powers change.
Existing private/VIP explicit voice denials remain. New category-inheriting rooms
receive the base voice-activation permission unless an explicit deny overrides it.
The plan JSON contains full before/after values and states; do not publish it.
