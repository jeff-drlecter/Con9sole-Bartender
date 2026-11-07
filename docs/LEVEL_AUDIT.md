# Owner-approved hybrid baseline update — 2026-11-07

The owner explicitly accepts public-leaderboard XP with unique current account-alias reconciliation and highest role-floor fallback, instead of waiting for an official lossless export. This supersedes the earlier requirement for an ID-bearing API export as a prerequisite for **this approximate baseline operation**. Ambiguous alias matches/duplicate public owners use role floors; public scores below a known role are held; unknown/departed rows are excluded, and members without evidence are not assigned invented zero baselines.

The full observed120 ranks must be present, captured recently, and all ten actual level-role IDs verified. The source capture time is preserved, never refreshed by re-submitting old data. Plans capture per-member source kind, roster hash and role mapping. Commit uses role/ledger locks, rechecks current identities/roles, creates a verified backup, replaces the baseline transactionally and archives the pre-capture shadow ledger. Post-capture accepted events are replayed; cooldowns are retained. Retrying the same plan is idempotent. Old Amari weekly balances remain unknown; historical bonus remains separate. Formal role/announcement activation remains gated independently.

# Current replacement status — 2026-11-07 (Hong Kong)

**Preview enabled; formal role/announcement replacement remains gated.** The owner-approved approximate baseline is complete. The historical divider below contains old blockers and must not be read as current migration policy.

| Area | Verified current state | Remaining work |
| --- | --- | --- |
| Baseline | Full120 public rows captured;87 unique current aliases plus5 role floors committed, with verified backup and archived shadow; live Top10 agrees |19 unmatched public ranks held;101 members without evidence unchanged;12 Unknown treated departed |
| XP rules | Text/activity share60s,1 baseXP, no extra activity daily cap; Booster×2; voice25XP/300s with2 eligible humans | Live voice/reconnect and role recovery drill |
| Activity | Actual ordinary/pet application response payloads and single award verified | Historical shared-text cooldown evidence and bonus commit |
| Historical audit | Full1,898-scope text audit complete; shared-CD net replay and archived/live reconciliation verified | Retained-history ordinary-rate compensation completed for two verified members, with backup; historical Booster/deleted-message data not inferred |
| Rewards | Missing-role reconciliation fails closed; complete10-role preflight and safe configuration command added | All10 mappings passed live hierarchy/permissions and were configured in preview; all-member reconciliation/restore drill remains |
| Weekly | New calendar weeks retained; old Amari weekly XP unknown | Never fabricate old weekly balances |
| Activation | Hard-disabled independently of baseline | Finish live acceptance and recovery evidence; disable Amari rewards before takeover |

The signed-in Developer Portal limitation no longer blocks the authorized hybrid baseline. No further API export is required for that completed operation. Public exact scores and role-floor approximations retain their separate provenance.

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

## Owner cooldown policy — 2026-11-07

Bot activity is an additional path through the same 60-second text engagement cooldown; neither path gets a separate claim. Voice remains independently every 300 seconds. Owner rejected the additional 60-per-day bot cap; the default and live configuration must use activity_daily_cap=0 (unlimited). A 65-event regression verifies no daily cap while text shares the activity cooldown and voice retains its own interval. Optional positive caps remain backward-compatible for explicit future configuration only.

## Historical request and read-only collector — 2026-11-07

Owner requests Amari baseline migration plus Adventure Frontier compensation from 2026-08-18 00:00 Hong Kong. A separate persistent history audit database records immutable card IDs, timestamps and hashes, fixed source/cutoff scope and resumable cursors. Raw content/account names are not retained. Ordinary cards provide historical ID/name-hash collision evidence; late-edited cards never supply an owner association. Pets resolve only after all source collection and require a unique historical owner plus an exact current account-name hash. Renamed/departed/ambiguous identities stay unawarded. Current preview text/activity events are considered when excluding nearby candidates.

This is read-only collection and provisional game-only counting, not compensation or snapshot import. All candidates still lack historical Amari text-award evidence and historical Booster evidence. No changes to live XP, cooldowns, weekly periods or reward roles occur. An exact ID-bearing Amari baseline is still required; leaderboard display names are not safe ID evidence. Unknown rows are treated as departed per owner instruction. Validation: 276 tests pass, including collector isolation, crash/resume/idempotent observations, owner collisions and exclusion of late-edit identity evidence.

## Retained historical text evidence — 2026-11-07

The read-only history_text command fixes its user scope and baseline cutoff before scanning. It enumerates current message-capable channels, active threads and public/private archived threads, refuses missing permissions, persists only target user/message IDs and timestamps, and checkpoints atomically with observations. Status and replay also recheck the saved scope's permissions. Replays exclude users outside that fixed scope.

The evidence preview greedily replays text plus recognized game cards under the shared cooldown, subtracting text-only accepted events. A game that merely displaces a later text award is not counted as an extra XP. Post-baseline cards are excluded and an ambiguous initial cooldown is held. Results are **base-XP candidates**, never automatic bonus writes: retained history cannot recover deleted messages or historical Booster membership. No current cooldown, total, weekly score, roles or announcements are changed.

## Historical compensation preview and guarded writer

The history_bonus preview includes the exact net base-XP changes, evidence hash, member scope, baseline, time range and policy. The owner authorized historical compensation under the original ordinary1-XP/shared60s policy. After the full retained-history scan, the release gate permits that base-only compensation. It does not infer missing messages or historical Booster bonuses; an exact preview digest, explicit base_only flag and verified backup remain required. The formal replacement gate remains false.

The prepared writer creates a verified backup and atomically adds compensated totals plus administrator adjustment records and a durable full-manifest marker in existing settings (no schema change). Same-manifest retries are no-ops; another historical batch is rejected. It preserves current weekly counters, cooldowns, receipts and events, seeds notice watermarks and leaves mode OFF. Tests cover restore and rollback when a later member fails. No compensation had been applied when this preview was prepared; live execution is recorded separately.

## Live voice timer defect and correction

The real existing call exposed zero new voice XP. Inspection of the installed discord.py Guild class confirms that afk_channel_id is not a public property; afk_channel is the supported property. The old timer and diagnostic used the unsupported attribute, which raises AttributeError. Production now reads the public AFK channel object; a regression uses an actual Guild instance, avoiding the fake attribute that masked this bug.

The independent auditor also reproduced a second failure: a voice listener could remove another member's clock while the first award awaited SQLite, causing KeyError and stopping the loop. The timer now revalidates current membership and missing clocks, checks gateway/cohort again under the credit lock, never revives removed clocks after awaiting, and preserves newly added listener clocks. Five independent interleaving regressions cover departure, deafening, disconnect, lock wait and new joins. All320 offline tests pass; live25XP/5-minute acceptance is still required after this correction.
