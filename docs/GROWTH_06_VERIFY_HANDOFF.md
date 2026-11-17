# C9-GROWTH-06-VERIFY — current review and blocked evidence

2026-11-17 Hong Kong. This is a review candidate, **not approval to merge or deploy**.
No production configuration, data, routes, roles, XP, notifications or Bot process
has been changed. Private operational aggregates stay in Jeff's private handoff,
not in this public repository, PR or Actions logs.

## Version and receipt register

| Item | Exact evidence | Result |
|---|---|---|
| Main | `9565192ac5d9027b1468b51efc7108a8f3c57388`, tree `a3ca530a926842797a182a20c55641e7e7517f26` | Re-fetched on 2026-11-17 |
| Last deployment | [43898217858](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43898217858), job `133407458246` | Success; log readback `runtime_commit=9565192ac5d9027b1468b51efc7108a8f3c57388` at 2026-11-16 23:38:51 HKT. Historical runtime evidence, not a fresh process-env read |
| 04 | [#193](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/193), `feat/growth-baseline-04`, head `f253d17d9a576c00d9733168ff954a97f2e20a48`, base same main | One design document; implementation intentionally pending A |
| 05 | [#194](https://github.com/jeff-drlecter/Con9sole-Bartender/pull/194), `task/growth-1000-05-content-experiment`, head `8b16d06f7496aba8b2ecdd6243ff8e9c4bbcf502`, base same main | One plan document with six drafts; not published or scheduled by this task |
| 04 CI | [44027229149](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/44027229149), job `133850370551` | Existing-code CI, compile, locked install/audit and container pass; not evidence that the proposed baseline exists |
| 05 CI | [44028064168](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/44028064168), job `133853090410` | Same distinction for document-only delivery |

No tracked AGENTS.md exists in the fetched main tree. Jeff's supplied project
instructions apply. #181–185 and #187 were integrated through #188; their Draft
status does not authorize replay. Earlier deployment status in
`CURRENT_INTEGRATION_STATUS.md`, the source PRs and candidate sections is
**historical**. Preserve those records; use #188–192 and the latest runtime
evidence for the superseding state. There was no new deployment in this task.

The two new document branches have disjoint paths and merge without conflicts:
local `git merge-tree --write-tree` result
`61959d0261002ecaac4065af98bb777e5b7f1e04`. This is only a tree-level compatibility
check, not feature integration acceptance. No shared production Python file changed
in #193/#194. Re-check heads/main after 04 supplies code.

## A: conclusions that source and private UI support

- `CommunityOutcomes` runs every 5 seconds plus voice events; it requires ready
  Bot, configured guild, SquadCards and SquadPlans. A successful empty scan writes
  a heartbeat. Health availability and coverage are not a server-wide census.
- The loop traverses `SquadCards.state['sessions']` only. `natural` requires id
  and message; `linked` requires matching plan id, guild, session id and `live`.
  Ended/waiting/unknown, missing channel and AFK are skipped before `observe()`.
  They need not appear in the stored unknown-source report. Historical skip
  reasons are not persisted; do not backfill them.
- SquadCards production starts from configured category-to-destination routes;
  `reconcile()` considers voice channels in those categories and excludes AFK.
  Unconfigured voice categories do not automatically produce tracked sessions.
  Live route configuration and permissions still need private runtime/Discord GET
  evidence. No route bug has been demonstrated merely by reading this condition.
- `SquadCards.last_error` is set on failures but not cleared by successful ticks;
  it has no timestamp. A warning can be stale. Conversely, absence of a warning
  does not prove every card was delivered.
- `outcome_observer_runs.failures` is cumulative; no per-error timestamps and no
  guild column are stored there. Distinguish latest run, cumulative total, latest
  success and current cog state. Raw logs are needed to date/classify failures.
- Coverage intervals were introduced to main by #188, commit
  `87dc4569606ea6806ff2e4a6fa1136791815d343`, deployed 2026-11-16 HKT in
  [43800236045](https://github.com/jeff-drlecter/Con9sole-Bartender/actions/runs/43800236045).
  DB `since`, natural/coplay start and coverage feature activation are different
  clocks. Never divide coverage seconds by an earlier DB lifetime to infer uptime.
- Owner-only private `/bot_health`, `/observed_returns` and `/community_outcomes`
  were read in the Tester area this round. These are existing features, not the
  unimplemented 04 baseline. Exact time/aggregate results are in the private
  handoff. No ordinary-member, Helper or pure-Tester acceptance is claimed.

### A remains partial

Historical access note: Fly and GitHub web sessions initially presented sign-in
walls. After Jeff signed in, Fly machine/image, volume/configuration and retained
logs were read on 2026-11-17 HKT. The running image tag matches the full main SHA
above. The configured persistent mount is `/data`; this is not a fresh process-env
or resolved-path read. Existing volume snapshots were listed, not restored or
validated for SQLite/WAL consistency. Exact operational details remain private.

The inspected Fly pages expose no private execution terminal. The available
GitHub connector reads code/Actions but has no private runtime shell or
workflow-dispatch operation.
No credential extraction, protection bypass, second Bot, restart, repair or
migration was attempted. Local `/data` is absent and must not be confused with
the production volume. The last deployed SHA is verified historically; fresh
`APP_COMMIT`, current resolved data paths, route/channel permissions, session
state, raw table aggregates, card-post correlation, complete
membership enumeration and personal-invite exclusion are **not yet verified**.

### Dated logs and isolated reproductions

Retained logs supplied dated evidence for two failures. With the project's locked
`discord.py==2.7.1`, synthetic payloads reproduce both locally without network or
production writes:

- `cogs/tempvc.py:199`: one unrelated channel with `type=20` in the all-channel
  response causes `Guild.fetch_channels()` to raise `InvalidData` before category
  filtering. `_try_order_temp_channels` catches it and returns; the synthetic
  bulk-position mutation count remains zero. This proves failed cosmetic sorting,
  not failed room creation or missing attendance. `core/news_channel_inventory.py`
  already handles unsupported types for its own news scope, but is not a general
  temp-VC replacement. Hand this exact condition to 01 for 03 coordination; no
  route/session code was changed here.
- `cogs/community_audit.py:336`: a channel-target audit entry with null `target_id`
  raises `TypeError` while resolving `entry.target`, before the outer `getattr`
  can supply its default. A synthetic action 11/null-target entry reproduces the
  error with zero `emit` calls. The real event's action was not in the trace; do
  not assert that its action was 11. The affected audit event does not complete
  this listener's output. No evidence links this to outcome collection loss.

Gateway resume records were also found. `CommunityOutcomes.on_disconnect()`
increments the cumulative failure counter; unsuccessful not-ready scans can do
so too. Resume chronology is consistent with the observed counter increase,
but per-run DB evidence is still required before assigning an exact cause/count.
The selected last-24-hour Grafana search for `"Outcome"` returned no data; this
is limited to that query, window and retained logs, not proof of no failure.
Later resume records must not be retroactively assigned to earlier UI totals.

The private UI's empty eligible cohort does not distinguish an empty raw table,
all-test/excluded records, guild/window mismatch or a query omission. Do not
select a cause until the raw evidence is read. No collector-loss bug is confirmed.
Old pre-observation cards/logs cannot be used as missing-event evidence.

### Prepared diagnostic, not executed against production

`scripts/inspect_growth_readonly.py` is a standalone standard-library inspector.
It never imports Bot/config/store constructors. SQLite uses `mode=ro`,
`query_only=ON`, one read transaction per DB and closes it. It reads WAL normally;
do not use `immutable=1`, checkpoint, or copy a live `.sqlite3` without its WAL.
Use a live DB with WAL in place or an existing validated SQLite-backup-API snapshot.
JSON and separate DBs are not a single global snapshot.

It reports table counts/time ranges, guild/test/origin/source groups, window
eligibility, missing/future/orphan attendance, coverage union/range, latest run
versus cumulative failures, sanitized session states/routes and card-post states.
Optional public invite codes are compared within `[start,end)`; personal codes
are excluded from the combined count; cross-code accounts use one DISTINCT union.
It prints no member/session/plan IDs, names, message content, token values or raw
exceptions. Route channel IDs and aggregates are still private: **do not attach
its production output to this public PR, repo or Actions log**.

Invocation in an already authorized private runtime terminal, after independently
confirming the actual data root and full APP_COMMIT:

```sh
python scripts/inspect_growth_readonly.py --data-dir ACTUAL_DATA_ROOT \
  --guild GUILD_ID --start UNIX_START --end UNIX_END --as-of UNIX_AS_OF \
  --public-code PUBLIC_CODE_1 --public-code PUBLIC_CODE_2
```

Use explicit numeric times; never leave placeholders in an actual command.
The inspector does not perform Discord GETs, enumerate members or infer first
participation. Its `eligible_rows_exist` result requires comparison with earliest
known/legacy anchors in `observed_returns.returns`; it is not itself a bug verdict.
Missing/incompatible sources return unavailable/null, not zero. Outside-root
overrides require separate review rather than silently reading an unrelated path.

## Contract decisions for 04 / 01

The #193 minimum design is accepted as a **development contract**, subject to A's
explicit unknowns. It is not acceptance of an implementation or production data.

1. Recent 7/28 **completed HK days**, `[start,end)` with end at today's HK midnight;
   show today's partial period separately. This is distinct from existing
   first-observation D0/D1–D7/D1–D28 cohorts and their maturity boundaries.
2. Union attendance and visits by guild/user after actual timestamp, stored source,
   test-session and explicit excluded-channel filters. Count linked/natural union
   once; do not add their distinct-account totals. Unknown history remains unknown.
3. REST member pagination must exhaust normally, with unique IDs and capture
   start/end, method, reported count, drift and completeness. Cache/role totals
   are not a fallback census. Non-Bot accounts are not independently verified humans.
4. Confirmed owned test accounts require an explicit private ID registry and
   provenance. No complete registry is supplied by this task. Staff/Tester roles
   alone are not exclusions; a normal daily-use account is not automatically a test
   account. Missing registry/failed counts use null/unverified, not zero.
5. Current-member intersection is exact only for a complete enumeration; otherwise
   show lower bound/unknown and do not infer departure. No XP/role/notification side
   effects. Fresh Admin authorization before and after every output; personal owner
   and guild check on buttons, HK/TW/neutral copy, ephemeral and no mentions.
6. Keep heartbeat health, observed route/session scope and qualified attendance
   separate. Current skip counts are snapshots, not history. No additive migration
   or new persistent diagnostic collection is justified by the evidence yet.
7. The 05 invite-join cohort → first observed participation interface is **not yet
   delivered by #193**. 01 must coordinate its precise scope with 04; do not silently
   promise an available endpoint. Attendance alone does not prove first-ever play,
   independent humans, campaign causality or full-server coverage.

04 still owes code, full head/base, modified interfaces, actual implementation
tests, migration/re-run/rollback evidence if any, and unverified identity scenarios.
It may use this contract for preparation while missing A evidence stays unknown;
do not mark A complete or B accepted.

## 05 review / required amendments

Accepted plan mechanics: same-window comparisons; separate views, join events and
current membership; explicit unknown attribution/reentry; cross-code de-duplication;
shared-profile-code attribution limits; no fake game event; six drafts separate
from publication; private evidence withheld from public files. No publication is
authorized by this review.

Before final acceptance, 05 should address:

- UI now presents changed community/Bot display names. Reconcile the opening
  "retain" statement and P05 naming with 01's latest authorized naming evidence;
  do not use this old document to reverse changes or independently rename anything.
- Make the P05 neutral-language choice clearly a preference question. Current
  `/language` exposes HK/TW choices; neutral is the default/conflict fallback,
  not an offered third setting. Do not imply that three selectable settings exist.
- Specify first-participation window `[joined, joined + 7*86400)` consistently,
  including the exact-boundary test and mature-as-of rule. This rolling join cohort
  is not interchangeable with 04's HK-calendar return cohorts.
- Describe results as first **observed qualifying non-Bot account attendance**
  after joining, with test-registry/coverage/prior-history limitations, not proof
  of distinct real people or first-ever gameplay. Leave it unknown until the
  agreed interface and evidence exist.
- P01/P04 remain blocked until real host consent, game/platform compatibility,
  date/time, minimum/maximum/vacancies, effective card and newcomer access are
  supplied by 03 through 01. Runtime personal-code exclusion and historical
  source-row-to-code mapping remain unverified; lifetime uses cannot resolve them.

## Checks, compatibility, rollback and remaining gate

The new inspector is manual/offline only; no workflow, Bot cog, command, schema or
production file is modified. Tests use temporary stores, including a real open-WAL
database: no DB/WAL byte changes, no writes permitted, snapshot isolation, missing
and corrupt sources, guild/time/test/source filters, session-contract parity,
cross-code union, personal-code exclusion and secret/identity non-disclosure.
Exact head/full regression/CI results belong in this Draft PR's current evidence.
An initial default-interpreter regression attempt lacked project dependencies and
is not a passing run; repeat with the hash-locked isolated environment.

No migration. Closing/reverting this candidate removes the manual tool/docs/tests;
preserve all production records, XP and notification receipts. No runtime rollback
was run and no new backup was claimed. A future code deployment would need a fresh
activity/receipt snapshot, WAL-consistent backup and recoverable image/volume,
plus 04 final-code acceptance. Current changes have no live process impact because
they are **not deployed**. iPhone Mirroring skipped, not passed.

Return to 01: A partial / private runtime access required; B blocked on 04 code
and 05 corrections. This document is prepared for the existing Chats; no claim
is made that a message was sent to them or they started the follow-up.
