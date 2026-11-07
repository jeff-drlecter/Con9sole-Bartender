# Current replacement status — 2026-11-07 (Hong Kong)

**NO-GO for active Amari replacement.** OFF diagnostics are deployed; Amari remains authoritative. The sections below the historical divider are a dated audit trail, not the current gap list.

| Area | Current evidence | Remaining acceptance |
| --- | --- | --- |
| XP ledger, rewards, notices, cooldowns and recovery primitives | Implemented; 262 local tests pass | Actual Discord scoring, voice and role recovery drill |
| Raw XP migration | Offline strict importer, cutoff replay and verified SQLite restore implemented | Authoritative full member-ID/XP/weekly export; shared freeze/cutover evidence |
| Real leaderboard | 120 unique ranks observed; XP/level curve agrees | Public rows have no reliable member IDs; Unknown rows are treated as departed per owner instruction; no identity guessing |
| Diagnostic message links | PR54 deployed successfully, Fly run42337400816 | Live metadata confirms selected battle uses a webhook; strict matching application/webhook/author identity support added, raw format still unverified |
| Reconnect source subscriptions | Ready/resume reconciliation added with archived/foreign/404 tests | Live reconnect observation |
| Battle parser and repeated button actions | Exact source allowlist; unrecognized cards do not earn XP | Original gateway payloads, same-card reuse behavior and actual preview award |
| Activation | Hard-disabled | All migration and live acceptance evidence above |

No real scores or reward roles have been migrated. An API access/export limitation prevents proving lossless transfer; it does not justify a level-only import. Best-effort fixture redaction is not guaranteed anonymity.

---
# Historical audit trail (superseded where the current table differs)

# Independent replacement audit — PR53

Date: 2026-11-06 (Asia/Hong_Kong). User explicitly requested an independent auditor alongside implementation.

**Verdict: NO-GO for replacing Amari.** The draft may be tested off/preview. Neither the original 226 passing tests nor the new audit regressions prove full product/data parity. No production cutover, Amari setting change or real score migration has occurred.

## Findings and disposition

| Finding | Priority | Disposition |
| --- | --- | --- |
| Independent progression curve changed level speed | P1 | Replaced with formula matching current official XP Info table. Checked 1–100 and 390–490, including highest reward400. Runtime verification remains open. |
| Level-only import loses within-level progress and weekly balance | P1 | Discord commit path blocked. Complete raw-XP importer is not yet implemented or proven. |
| Activation accepted two booleans and any nonempty reward mapping | P1 | Hard release gate `REPLACEMENT_READY=False`; true flags cannot bypass it. Gate may only be changed after evidence below passes. |
| Older concurrent role event could overwrite newer level | P1, reproduced | Global role-effect lock, latest durable total reread, current Discord member fetched before actual role mutation. Deterministic auditor race tests pass. |
| Config mutation during awaited role REST calls | P2 | Mode, source, exclusions and reward mappings use role-lock→ledger-lock ordering. Confirmed pause waits for current side effects, then blocks subsequent writes. |
| Mute/stream events reset every attendee's voice timer | P1 | Reconcile actual eligible set; unaffected peers retain time. 3→2, deaf2→1 and mute/stream regressions pass. |
| Cached voice attendance earned XP during gateway disconnect | P1 | Explicit disconnect fence, readiness guard, clear on ready/resume and no offline backfill. |
| Imported Amari snapshot plus retained preview double counts overlap | P1 | Identified and documented; level-only write blocked. Requires provenance/cutoff-aware migration, not additive snapshot import. |
| No verified XP/config/role recovery and reverse cutover | P1 operational | OPEN. Pause/image rollback is not recovery. Keep activation blocked. |
| Parser fixtures invented rather than captured from gateway | P2 | OPEN. Browser observation only establishes public results exist; no actual payload or real preview award has been verified. |
| Queued older events could duplicate latest milestone announcements | P2 | Durable notice watermark; suppress across process/Ledger restart, retry failed HTTP on later reconciliation. |
| Failed role assignment still announced membership | P2 | Notice watermark seeded before role write; role failure returns before announcing. Retry regression passes. |
| Reward roles could contain moderation powers | P2 | Reject moderation/channel/webhook/message/thread management powers in addition to admin/manage-guild/manage-roles; recheck for real Discord members during reconciliation. |

## Actual XP table evidence

Read current official `https://amaribot.com/xp-info` via the user's browser. Its table matches:

| Level | Total XP |
| --- | --- |
| 1 | 35 |
| 2 | 55 |
| 3 | 115 |
| 5 | 355 |
| 15 | 3,955 |
| 50 | 48,055 |
| 75 | 109,555 |
| 100 | 196,055 |
| 390 | 3,026,455 |
| 400 | 3,184,055 |
| 490 | 4,782,455 |

The closed-form curve is inferred from these displayed values, not from hidden application code. Website says its values are estimated; live runtime comparison is still mandatory. Current signed-in account's Developer Portal states no access and directs to its support team. No keys were created, copied or exposed. Historical API documentation alone is not proof of current export access.

## Required acceptance evidence

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Data completeness | Every in-scope user ID/raw XP/level/within-level progress/weekly XP and relevant rewards; counts, checksum, source time | Missing |
| Runtime progression | Amari rank examples across low/high levels; actual normal/Booster text and eligible voice awards | Missing |
| Cutoff accounting | Explicit timestamp T, no overlap/loss across snapshot, shadow and new events; no additive double counting | Missing |
| Reward integrity | All10 mappings, safe roles/hierarchy, current authoritative membership, pre/post role snapshot | Partial code; live check missing |
| Third-party activity | Captured sanitized ordinary/pet/kill/death/rescue/edit fixtures; correct real ID and single preview award | Missing |
| Failure/recovery | Durable data backup+restore, external role restore, restart/outage/403/database failures, inverse migration of new XP | Missing |
| Deployment capacity | Live current Fly memory/CPU/storage and normal command behavior under representative load | Missing |
| Announcement policy | Accepted generic milestone behavior or exact original templates/modes/ping; failure semantics | Decision/implementation gap |

All gates must have concrete evidence before changing `REPLACEMENT_READY`. There is no admin UI override for missing evidence.

## Functional differences still requiring a decision or implementation

- Only generic milestone notices currently; ten existing custom announcement strings are captured but not automatically restored. No custom announcement editor, all-level mode or weekly winner announcement.
- No complete raw-XP/weekly import/export or role/XP recovery tool. Legacy level-only CSV is preview-only.
- New policy retains XP on leave while current Amari clears it. This is a deliberate proposed change, not parity.
- Text and bot activities share a cooldown and activities have a daily limit; these are new anti-farm policies.
- Voice amount25/5minutes is based on documented multiplier×interval, not observed live credit. Filtering policies may differ from Amari.
- Rank card is a private embed, not Amari's customizable image. Ranking UI is Top10, without exact personal rank or historical-week selector.
- Generic role/channel multipliers and original command aliases are not all implemented. Current Con9sole settings only require Booster×2; broader Amari feature parity is not claimed.

## Residual reliability boundaries

- Roles/announcements are retried on the next qualifying reconciliation, not by a durable background repair queue. This remains an activation-readiness gap for users who stop generating events after a failure.
- Discord REST send and SQLite notice acknowledgement cannot be atomic. A process crash after send but before marking the watermark may duplicate a notice. Tests cover queued-event duplicates and HTTP failure retry, not impossible global exactly-once semantics.
- A successful role add/remove sequence is externally non-atomic. Serial ordering and authoritative rereads reduce risk but do not substitute for a recovery drill.

## Review independence

The auditor read implementation/docs, independently reproduced the stale-role downgrade and added `tests/test_level_audit.py`; the implementer changed production code. Auditor tests use no production secrets/data and do not log into Discord. Final production replacement verdict remains NO-GO regardless of offline pass count.

## Continuation — executable transfer/recovery and parity work

The follow-up implementation adds `features/level_migration.py` plus offline-only `scripts/level_transfer.py`:

- Strict JSON, exact ID/XP types, independent roster/count matching, exact level/within-level validation, source freeze/cutover provenance.
- Atomic raw-XP replacement of preview totals. Accepted post-cutover journal events are replayed once; earlier shadow scores are discarded. Late pre-cutover message events are rejected by source timestamp.
- Shared cooldowns and same-day activity caps reconstructed from bridge events. Post-cutover manual adjustments/departures refuse migration pending an explicit policy instead of silently losing data.
- Original Amari weekly counter preserved as `amari-legacy`; it is not mislabeled as a known calendar week. Zero-XP members are included in the independent scope.
- SQLite backup API, standalone DELETE-journal artifacts, SHA256 and exact staged-byte validation, sidecar rejection, schema/integrity checks, all-table guild checks, restore forced off, and mandatory current-state checkpoint before restore.
- Level-role restore **plan** only, with canonical ID normalization and rejection of duplicate/unsafe role IDs. Actual Discord role application remains a separate live acceptance item.
- Durable role-repair jobs with backoff and version-specific acknowledgement. Failed users cannot monopolize the first repair batch. No further user interaction is required for retry while gateway is ready/active.
- Personal total rank, paginated rankings, historical ISO week/legacy counter selection, weekly top3 preview/publication command, ten original custom notices and editable all/milestone/off announcement policy.
- The latest observed original level log contains ordinary levels14/28/44/3/4/8/46/16/35/6, so the compatibility default is now all-level notices, ping on. `clear_on_leave` matches the verified Amari setting on, with optional retention and pre-clear archive. These replace the prototype's proposed policy differences.

Read-only public leaderboard observation covered **120 unique ranks**, including **12 Unknown entries**. All120 displayed XP/level pairs satisfy the current curve. The page provides no stable Discord IDs, so this is useful runtime level evidence, **not** a complete identity-safe migration export. Unknown names are not guessed or matched by rank.

Independent auditor added `tests/test_level_migration_audit.py` and reproduced/fixed reset cooldowns/caps, lost post-T adjustments, incompatible schema restore, normalized role-ID mistakes and a WAL overlay checksum bypass. All source fixes were performed by the implementer; auditor maintained its own tests.

These are implemented/tested primitives. No real source freeze, real score import, live role restore or inverse writeback to Amari has occurred. CLI requires Bot stopped and feature off; its `--offline` flag is an operator attestation, not proof that an external process has stopped. Never run it concurrently with the Bot.

### OFF diagnostic release acceptance

260 offline tests pass, including14 independent original audit regressions and10 independent migration audit regressions. Inspector now refuses exports outside the exact source allowlist; both view-channel and history permissions are required. Default unsupported messages return structural metadata only. Explicit private raw payload export is restricted to Administrator and the trusted Bot/thread. Standard fixture text is labeled as best-effort replacement requiring review, not guaranteed anonymization. No capture is automatically written to git.

Conditional approval is for OFF diagnostic deployment and existing-core smoke tests only. Main source settings/scores remain Amari-owned. No migration CLI, source freeze or activation is part of this release.

## Application response source correction — 2026-11-07

Live OFF diagnostics report Bot=True and Webhook=True for the selected game card. Discord documents interaction followups at `/webhooks/{application_id}/{interaction_token}` and exposes server-supplied `application_id` on messages. Accept this path only when application ID, webhook ID and author ID all match, plus the existing exact source allowlist. Arbitrary incoming webhooks remain rejected. Official references: https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx and https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx . Actual three-ID agreement and parser acceptance require live validation.

## Real game payload acceptance — 2026-11-07

PR56 deployment completed (Fly run42338138300). The selected original application response passed exact application/webhook/author agreement and source configuration while mode stayed OFF. Standard inspection confirmed trusted source, recognized normal battle format and an existing Discord member identity match. Pet inspection initially failed; explicit Administrator-only private raw inspection showed the owner line is followed by level/species details. Parser now anchors the first line, rejects pet fallback when mentions exist, and redacted real normal/pet projections are regression fixtures. No real account name or source message ID is committed in the fixtures.

This proves read-only source/normal-identity acceptance, not an actual XP award, pet binding, repeated-card behavior or successful Amari cutover. Those checks remain open.
