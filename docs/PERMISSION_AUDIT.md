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

## AutoMod rule preview

`/anti_scam_rules` fetches current roles, channels and AutoMod rules and privately
exports a JSON draft. It has no create/edit/delete path. Candidate rules remain
`enabled=false`, and candidate initial actions are alert-only. The draft includes
possible later block+alert actions for unverified explicit URLs, not an approval
to enable them. Verified only exempts that URL rule; all-user spam monitoring has
no explicit role exemptions. Existing rules remain unchanged. Custom keyword
quota, missing targets and duplicate names are review blockers.

Explicit URL matching is not a complete phishing classifier: bare domains,
obfuscation, images and DMs are excluded. Local Python regex examples do not
constitute Discord Rust-regex acceptance or live-message tests. No auto-Verified,
role revocation, punishment or threat-feed integration is part of this release.
Discord's native Administrator/Manage Server AutoMod exemptions still apply.
Sources: https://support.discord.com/hc/en-us/articles/4421269296535-AutoMod-FAQ
and https://discord.com/safety/auto-moderation-in-discord .

## Alert-only activation

`/anti_scam_monitor mode:enable` creates the two approved alert-only rules;
`status` is the default read-only operation; `disable` only disables matching
rules owned by this tool. A persistent receipt records intent before POST,
creator/rule IDs and actor. Unknown outcomes are never blindly recreated;
matching rules may be reconciled by exact name, bot creator and payload only
when an intent receipt exists. Rules modified outside the tool stop processing.
Existing unrelated rules are never edited/deleted. Creation and enabled-state
changes are re-read. Native rule names and ID receipts prevent duplicates.

Enable requires the configured private text destination to exist, with no
non-staff ordinary role access and no member-specific View Allow. Private
message content is not fetched; no artificial scam/spam messages are sent.
No block/timeout actions, Verified revocations or automatic verification are
included. Native AutoMod admin exemptions and explicit-URL coverage gaps remain.

## Opted-in unverified participation

`/participation_fix` previews/applies/restores only Send Messages and Send
Messages in Threads for the off-topic role on the two reviewed public chat/forum
IDs. It never edits View Channel, attachment/embed rights, the NSFW channel,
other categories or onboarding. Explicit role-specific send denials are skipped.
Plans reuse durable ownership-aware journaling and are scope-bound; moved or
retyped channels stop apply. This is independent of AutoMod enforcement mode.

Manual TempVC creation no longer depends on Verified. Ordinary members must be
current cached members, not screening-pending/timed-out/bots, able to view the
source, inherit View/Connect/Speak from the destination category, and access a
matching hub there. No eligible category means use an appropriate game/public
channel first. Authority is rechecked after owned-room lookup and inside the
create lock. Existing owned rooms are only returned when still accessible.
Existing admin/Manage Channels creation and staff teardown controls remain.

Important combination limitation: leaving attachment/embed bits unchanged does
not guarantee text-only access. An unverified off-topic+legacy-PGA combination
already has these base grants; allowing Send makes them usable. Verified-based
attachment/link enforcement is a separate pending scope; current AutoMod remains
alert-only. Do not describe this participation change as strict text-only access.
