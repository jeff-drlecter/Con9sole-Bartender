# Anti-scam Update — Stage 1 acceptance record

Status: implementation prepared; NOT applied and NOT closed.

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
- [ ] Fresh live preview and inspect diff; historical snapshot is not authority to apply.
- [ ] Apply attachment/embed policy and read back each change.
- [ ] Post-apply zero non-exception ordinary grants; no Bot/staff capability loss.
- [ ] Live ordinary/Verified/Mod/Helpers and Bot functional acceptance.
- [ ] Service-specific least-privilege configuration for Carl-bot, Dyno, Bartender. Administrator remains an explicit blocker; it is not removed by this capability gate.

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
