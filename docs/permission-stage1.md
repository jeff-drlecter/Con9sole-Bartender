# Anti-scam Update — Stage 1 acceptance record

Status: Stage 1 baseline acceptance completed on 2026-11-10 after ordinary-member voice and uninvited private-thread checks. Evidence and coverage limits are recorded below.

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
- [x] Live ordinary/Verified/Mod/Helpers and Bot baseline functional acceptance (scope and limits below).
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

### Human-account checks — 12:45–13:03 Hong Kong

Using `jeff_con9sole`, Helpers message send and membership-card interaction passed. User removed Helpers; Verified message send, membership-card slash command and a real Discord.com link embed passed in FC chat. User then removed Verified and EA FC-M. EA FC-M was confirmed to retain Manage Messages, Timeout and scoped attach/embed grants; its presence explained the first unverified embed result, rather than a Tester-role leak.

At 13:02, the profile no longer listed Helpers, Verified or EA FC-M; Tester and ordinary game/level roles remained. In the test sandbox, a fresh message sent successfully, the Discord.com URL remained plain with no embed, the composer actions menu offered Create Thread/Use Apps/Schedule Message with no upload entry, and `/levels rank` returned the membership card at 13:03. This verifies normal text/Bot use and the visible attachment restriction for that account in the sandbox, not an attempted file-upload rejection.

Remaining live acceptance: voice and private-thread scenarios, Mod without owner/Admin bypass, and actual file-upload behavior where required. Historical embeds remain visible after role removal; only newly sent messages were used to judge the restriction.

### Mod, private-thread and voice smoke checks — 13:14–13:16 Hong Kong

User assigned Mod to `jeff_con9sole`; the profile showed Mod and the account remained distinct from server owner `jeff_drlecter`. In the sandbox, a new Discord.com link produced an embed and Upload a File was present. Created `Stage 1 私人討論串驗收` with the private checkbox selected; Discord displayed the private-thread invitation notice and accepted its first message. Joined the empty sandbox voice hub while muted; Bartender created `小隊call • 1`, moved the account, and Discord showed Voice Connected. Explicitly disconnected afterward; connection controls disappeared.

These complete the requested Mod/private-thread/voice smoke scenarios. Coverage limits remain: no actual file-transfer attempt, no uninvited-account private-thread visibility test, no speech/audio-quality test, and no ordinary-account voice test. No ban/kick/timeout or other-member deletion was exercised. Treat these as scoped smoke acceptance, not an exhaustive role-by-channel matrix or proof of all moderation actions. Full Stage 1 closure remains conditional on the required coverage decision; the live changes and successful smoke checks themselves are complete.

### Final baseline acceptance — 13:22–13:26 Hong Kong

User removed Mod. Fresh profile inspection of `jeff_con9sole` showed ordinary game/level roles and Tester, with no Mod, Helpers, Verified or EA FC-M. Joined the empty sandbox voice hub while muted; Bartender created/moved the account to `小隊call • 1` and Discord showed Voice Connected. Disconnected and restored the original unmuted toggle afterward; this did not test microphone audio quality.

Switched to owner `jeff_drlecter` and created private thread `Stage 1 未獲邀可見性驗收` (`1569583382529314919`) with the private checkbox selected and a non-mention text marker; did not invite `jeff_con9sole`. Switched back to the ordinary account and navigated directly to the observed thread URL. Discord redirected to the guild root and did not expose the thread message. On return to the parent channel, the original thread owned by `jeff_con9sole` remained listed, while the new uninvited thread was absent. This distinguishes membership from loss of Mod powers.

The previously pending ordinary-voice and private-thread visibility scenarios now pass. Stage 1 baseline acceptance is complete: applied permission receipts, zero nonexception role grants, Bot least-privilege and functional checks, human text/Bot checks, ordinary voice connectivity and private-thread membership boundary. Earlier pending notes are chronological evidence and are superseded here. Remaining coverage limitations are actual file-transfer attempts (upload controls were checked), audio quality, and destructive moderation operations; these are not claimed as tested. No further live permission changes were made during final acceptance. Preserve test markers for audit; temporary voice rooms use existing empty-room cleanup.
