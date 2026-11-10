# Anti-scam Update — Stage 1 acceptance record

Status: applied and Bot least-privilege migration verified on 2026-11-10; human-account functional acceptance remains open.

## Fixed decisions

- Ordinary members can chat, use voice and interact with the Bot; Verified is not a participation gate.
- Attach Files / Embed Links are the only bits this tool changes. Posting a URL is separate; AutoMod remains alert-only.
- Preserve four reviewed VIP exceptions: 1380168909671370824, 1380173835474571406, 1380176573189197922, 1380176879562002462. These share the VIP category and intentionally deny Verified; Booster privileges remain a documented exception. Unknown additional VIP channels stop the planner.
- Keep all view/send/connect/speak, onboarding mappings, member overrides and unrelated permissions unchanged.
- Preserve non-admin Bot and staff attachment/embed capabilities. Fresh bot membership is fetched from managed-role bot IDs; actual human staff role combinations are fetched through the member endpoint. Both are included in the precondition fingerprint; the plan aborts on simulated service capability loss.

## Procedure

`/stage1_permissions` defaults to preview. Apply requires the same actor/guild-bound saved plan ID and an unchanged fresh permissions/membership fingerprint. Existing journal stores each attempted write before the API call; ambiguous outcomes stop subsequent writes. Use this same command's restore action; the generic command rejects this scope.

Categories update synced children; no duplicate direct child writes are planned. Unsynced children get their own mask-only changes. Simulation and final conservative capability proof include all eligible role subsets by omitting ordinary role denials (a denial must not hide a grant available without it). Managed human Booster roles are included; actual Bot roles and explicit staff roles are excluded from ordinary membership.

## Completion checklist

- [x] Four historical VIP exceptions reviewed and decision recorded.
- [x] Planner, rollback journal integration, precondition checks and offline regression tests prepared.
- [x] Fresh live preview and inspect diff; historical snapshot is not authority to apply.
- [x] Apply attachment/embed policy and read back each change.
- [x] Post-apply zero non-exception ordinary grants; no Bot/staff capability loss.
- [ ] Live ordinary/Verified/Mod/Helpers and Bot functional acceptance.
- [x] Service-specific least-privilege configuration for Carl-bot, Dyno, Bartender. Administrator removed through Discord role settings after scoped channel preparation and functional checks.

Do not close Stage 1 until every item is done. Do not re-open completed items unless configuration changes, a regression or an unresolved verification result gives a concrete reason.


## Bounded execution and incident recovery

Each apply/restore invocation now stops after 20 attempted entries, 90 seconds
between entries, or a 150-second hard timeout. Cancellation during a write records
`uncertain` before releasing the lock. A ten-second heartbeat reports receipt
counts. `查詢計劃進度` with the original plan ID reads durable receipts even while
another operation holds the mutation lock; it does not claim that a held lock
means forward progress. `核對中斷結果` only reads ambiguous entries and marks them
verified if the observed value equals the intended result, otherwise conflict.
It never replays a write. Keep all old plan IDs for restoration. For remaining
prepared entries create a fresh preview of current settings before the next batch.
The original fingerprint check and all per-write scope/authority checks remain.

## Live evidence — 2026-11-10

Original plan `3b2486ccb0dc`: 853 verified receipts, mutation lock idle. Final live attachment/embed audit at 12:08 Hong Kong checked 65 ordinary roles and 131 eligible channels with zero unexpected grants (including the temporary test room while present). Four VIP exceptions retained.

PR #97 fixed bounded progress/recovery. PR #98 deployed service preparation; 539 tests and Fly deployment passed. Carl and Bartender each completed 85 verified overwrite writes. Post-removal audit checked 158 channels per service: Administrator false, missing capabilities zero. Carl role mask `1374658358470`; Bartender `326704163953`. Dyno management/Admin powers removed; basic message profile retained.

Actual smoke checks after removal: Dyno `?dinfo` embed; Carl `/ping` and message-edit log with before/after content; Bartender existing Hong Kong language role verification, main menu, membership card, temporary voice-room creation, and `/bot_health`. Health reports loaded systems, running loops, ledger OK, and zero pending/uncertain notification work. The empty test voice room no longer appears in the sidebar after its cleanup interval.

Still open: ordinary/Verified/Mod/Helpers actual-account chat, voice, attachment/embed and private-thread acceptance. Permission proof and administrator-account Bot smoke checks do not substitute for those tests. No live member was kicked, banned or timed out for testing.
