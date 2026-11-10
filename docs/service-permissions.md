# Stage 1 service permissions — 2026-11-10

Live evidence: Carl dashboard has member/message/voice logs, moderation logging to
server-log and a reaction-role panel in sorting-hat. No autoroles/sticky roles.
Dyno dashboard: only Autoresponder and Custom Commands enabled, both with zero
records; all moderation, logging and autorole modules disabled. Dyno's admin and
management permissions were removed through Discord settings; its basic message
profile and a narrow admins-command overwrite were saved. `?dinfo` replied with an
embed after removal. Other bot roles remain unchanged pending channel preparation.

Carl retains logging/audit, reaction-role and enabled moderation command powers.
Bartender retains roles, channel/temporary-room creation, moving members, messages,
threads, invites and Manage Guild for existing AutoMod/audit tools. Neither profile
includes Administrator or Manage Webhooks. Bartender has no kick/ban/timeout power.

`/service_access` only prepares channel overwrites for the two fixed managed bot
roles, while they still have Administrator. It does not assign roles to members or
remove Administrator. No ordinary roles, @everyone or VIP member rules change.
Plans contain at most twenty writes. Pre-write/readback journaling and unknown-
result stops are shared with the existing migration. Synced children are covered
by parents unless their required capability set differs. Member-denied required
permissions block preparation. Verify simulates the real bot's role combination
using the proposed non-admin profile, and checks per-member overwrites.

After zero missing capabilities, apply the documented role mask through Discord
settings and perform functional checks. Do not describe a permission simulation as
a completed functional test or close Stage 1 on the simulation alone.
