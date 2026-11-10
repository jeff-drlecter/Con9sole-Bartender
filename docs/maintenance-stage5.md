# Stage 5 — maintenance and configuration drift

## Starting point

Checked main `612ed07` and the latest Stage 4 handoff (`bot-integration-stage4.md`). Stage 4 is accepted for its documented scope, including #109 and its live checks. Stages 1–4 are not repeated. Existing `/bot_health` is read-only but had no accepted configuration baseline or restart-safe alert deduplication.

## Implemented scope

- New administrator-only `/maintenance`: status, read-only check, preview/accept baseline, enable/disable background hints, existing private destination discovery and a labelled once-only delivery test. Responses are ephemeral. Fresh REST member **and role permissions** are checked before local configuration writes; Helpers/Mod alone do not confer configuration authority.
- Versioned snapshots in `/data/maintenance.sqlite3`: role permission masks; channel type/parent/permission overwrites; AutoMod rule settings; memberships of Carl-bot, Dyno and Bartender. Raw channel reads retain unknown type 20 instead of silently skipping it. Once identified, core Bot IDs remain tracked across renames/removal (a failed member read is unknown, not healthy).
- Ignore cosmetic role/channel/AutoMod names, channel positions and array ordering. Ignore only Bot-tracked temporary voice rooms, never rooms identified by their names. Guild channel reads exclude Discord threads.
- A preview is bound to actor, destination and the observed snapshot, valid for ten minutes. Accept re-reads settings and destination; stale/mismatched/changed previews cannot advance the baseline. All baseline versions and notification receipts remain retained.
- The existing Fly machine polls every 30 minutes after startup reconciliation. Each check is bounded to 90 seconds; checks are serialized. Missing core cogs, stopped XP/voice-card/title loops, squad errors, ledger read failures and uncertain notification queues require review. Normal pending role jobs/delivery work is left to its existing worker and shown in `/bot_health`.
- Two matching background observations are required before a hint. Manual checks do not send or advance the consecutive-observation count. Drift fingerprints include the configuration digest, so another change to the same role/channel is not hidden by deduplication.
- Every actual send freshly checks that the destination is an admin-only guild text channel (bot roles allowed). Mod/Helper exceptions and individual member `view_channel=True` grants are rejected conservatively. Failures never fall back to a public channel. No role, overwrite, AutoMod or membership is edited by the monitoring code. The separately approved manual destination setup is recorded below.
- A durable `uncertain` receipt precedes sending. A successful response records the message ID. Timeout/cancellation/crash outcomes are never automatically resent, including across restarts or baseline replacement. At 1,000 fingerprints per guild new hints pause rather than evict receipts and risk duplicates; status exposes that condition.
- The delivery acceptance probe is clearly labelled as a test (not an anomaly), uses the same fresh privacy check and durable send intent, and runs at most once per baseline. A repeated invocation cannot resend an uncertain test. Existing private destination discovery reads raw channel settings without changing access.
- Hints contain category counts and bounded IDs, no raw AutoMod expressions, recipient lists or message bodies; mentions are disabled. `/bot_health` includes a cached maintenance summary for administrators.

## Activation and review

1. `/maintenance` → **狀態**. Default is disabled, no implicit trusted baseline.
2. **立即核對**: examine read/health results and compare prior stage handoffs. This sends no channel notification.
3. **預覽新基準**: choose an existing admin-only text channel if the default admin channel fails privacy validation. Do not widen access or change permissions for the monitor. Review the counts and any differences.
4. **確認新基準**, with the exact preview code, within ten minutes. The caller must be the preview actor. This only accepts the observed local baseline.
5. **啟用背景提示**. Use status/check and `/bot_health` to investigate hints. Compare Discord settings and the originating channel before any manual remediation. After an intended change, preview and accept a new baseline explicitly.
6. **測試通知送達** verifies actual delivery once per baseline. Check the destination history; repeated invocation must report an existing receipt.
7. **停用背景提示** pauses this monitor only, preserving receipts and versions. It does not disable Stage 2 anti-scam monitoring.

A failed privacy check requires selecting another already private destination or a separate administrator-reviewed access change; no automatic permission repair exists. An uncertain send requires checking the destination history. Do not delete its receipt to force a retry. A full receipt journal requires a reviewed archival/migration plan; no automatic purge is provided.

## Backup and rollback

This release adds a separate SQLite database and leaves existing schemas untouched. Existing application rollback may leave this extra file in place; never replace or delete production state without a backup. To make a consistent backup, use SQLite's `Connection.backup()` from a read-only source connection, not a live copy of only the `.sqlite3` file. Keep the backup private, run `PRAGMA integrity_check` on the backup, and verify baseline/receipt rows before any restore. Offline tests restore a copied test database and check retained baseline history and integrity. **No production restore or Fly volume snapshot has been performed or verified by this stage.** Deployment-image rollback does not restore data; restoring an old monitor DB may erase newer send receipts and cause duplicates, so disable the monitor and reconcile those receipts first.

## Validation and activation

- Local compile and 576 tests passed, including unknown channels, core membership reads, canonical snapshots, stale authority, preview expiry/actor/content checks, retained versions, SQLite backup integrity, privacy failures, two-observation gating, same-target changes, no-blind-retry after timeout/cancellation/restart, and real extension reload cleanup.
- Initial deployment #111 succeeded: main `e2da188`, Fly workflow `42828745123`, including machine-status verification. On 2026-11-10 21:55–22:01 HK, live owner `/maintenance` status/check and `/bot_health` responded privately; ledgers OK, all core loops running and zero pending/uncertain notification work. Both `admins-指令` and `chatroom-logging` were rejected as notification destinations because non-admin roles can view them. No permission changes or notifications were sent.
- Follow-up #112 (`626934d`) adds private destination discovery and labelled delivery acceptance; PR CI passed (`42829739414`), Fly workflow `42829861789` passed all steps including machine-status verification. At 22:03 HK, private destination discovery responded successfully and returned existing game/archive-style channels. At 22:05, `server-log` was also correctly rejected for non-admin visibility. The old 21:59 read-only observation survived the #112 deployment, demonstrating persistence of monitor state.
- The user approved the proposed dedicated destination by continuing after the explicit channel/access question. On 2026-11-10 22:16 HK, created `bot-維護` (`1569717305489752216`) as a standalone private text channel: @everyone denied view, Bartender selected as the only explicit role, owner/Administrator implicit access, no Mod/Helpers grants. This approved manual channel setup is the sole access change for Stage 5; existing channel/role policies were preserved. The Bot's fresh privacy validation passed.
- At 22:16–22:17, previewed and accepted baseline **#1**, covering **83 roles, 160 channels, 5 AutoMod rules, 3 core Bots**. The destination is the new private channel. The labelled delivery probe was actually observed there once at 22:17; its command acknowledged successful sending.
- At 22:18, a repeated delivery-probe invocation returned the existing-receipt refusal; there was still one actual test message. Enabled background monitoring (30-minute interval); status showed baseline #1, sent 1 / uncertain 0 and a passed fresh destination privacy check. A subsequent read-only comparison passed with no drift or health findings.
- The activation PR final checklist records the deployment/restart result after this documentation-triggered deployment, including retained baseline/enabled state and repeated-probe refusal across restart. This avoids a second documentation-only deployment just to record the first. A real production drift incident is not manufactured for testing: the live labelled probe validates delivery, while offline tests exercise two-poll anomaly gating, changed values and uncertain-send failure paths. Native mobile, real security incident injection and production disaster recovery remain outside this acceptance.

## Coverage limits

This is in-process monitoring: a stopped Fly machine, disconnected Bot, missing monitor extension or total network outage cannot reliably send a Discord hint. GitHub Actions deployment verification and manual Fly/Discord checks remain necessary. No external uptime service, paid service or scheduled ChatGPT task is added; no dollar-cost guarantee is made.

Snapshots are sequential REST reads, not atomic Discord transactions. Consecutive checks reduce transient noise; they cannot prove every operation succeeded. Changes between observations can be missed. Missing access is reported as unknown. Core Bot member reads fail closed; a Bot removal is not silently accepted as a healthy baseline.

Not covered: Carl/Dyno dashboard settings, external Bot runtime logic, guild-wide security/onboarding settings, role hierarchy order, general member role assignments, archived/private thread membership, webhooks/invite inventories, native mobile UI, production disaster recovery and out-of-process uptime. Names/positions are deliberately excluded. Apart from the explicitly approved new private destination, this stage does not change existing channel/member permissions, XP, subscription logic, anti-scam actions or HK/TW preferences.
