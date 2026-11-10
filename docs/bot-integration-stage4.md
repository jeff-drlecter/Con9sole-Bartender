# Stage 4 — Bot functions, entries and responsibilities

Started 10 November 2026 (Hong Kong). Base main `01c531a` (#107).
Status: closed for entry consolidation and documented service ownership on 10 November 2026 (Hong Kong). Implementation #108 and acceptance fix #109 are merged and deployed.
Stages 1 and 3 are closed for their documented scope. Stage 2's alert-only baseline
is closed with the limits in anti-scam-stage2.md; this stage does not change it.

## Ownership and evidence

| Service | Responsibility / observed state | Evidence and boundary |
| --- | --- | --- |
| Con9sole-Bartender | Member card/XP/titles, bar activities, recruitment/footprints, opt-in squad notices, temporary voice rooms, staff panels and supplemental alert-only monitoring | Current source; level takeover status in LEVEL_AUDIT.md; Stage 1 and 3 acceptance. No new XP, consent or moderation policy here. |
| Carl-bot | Member/message/voice and moderation logs; existing game reaction-role panel and enabled moderation commands | Stage 1 dashboard evidence in service-permissions.md. Retain these functions; not migrated to Bartender. Dashboard configuration not freshly re-read in Stage 4. |
| Dyno | Retained basic command service; last dashboard had zero autoresponses/custom commands and other modules disabled | Stage 1 evidence. Idle does not establish safe removal; no kick/removal performed. |
| Amari | Historical XP retained; scoring/rewards/announcements disabled at the accepted takeover | LEVEL_AUDIT.md current deployed-status table. No historical data deletion or reactivation. |
| Discord native AutoMod | Original rules preserved alongside alert-only supplemental monitoring | anti-scam-stage2.md. Not replaced by Carl/Dyno/Bartender moderation actions. |
| Adventure Frontier, Twitch Alerts, YAGPDB | Present in current slash-command suggestions | Live Discord command picker observed on 10 November. Configuration and functional ownership not audited; not disabled or claimed redundant. |

## Gaps and changes

- Quick bar gains existing temporary-room **control** and **my squad notices** entry
  points. Each row has at most two buttons; more features remains the last row.
  These open existing user-scoped flows, not additional room creation or consent.
- Social section restores the existing confession modal entry already advertised
  in Help and previously available on legacy menus. Opening is not publishing.
- Help identifies **Con9sole-Bartender** in the `/menu` picker: the live picker
  also contains Adventure Frontier and Twitch Alerts `/menu` commands. Those
  independent applications' commands are retained.
- Help documents the notice shortcut in both wording preferences. Staff panel
  description gains its existing permission-audit entry, using the same capability
  filter as other described tools.
- Old menu IDs, callback methods, private replies, role preferences, permission
  checks, scores, cooldown policy and subscription lifecycle remain unchanged.
  Legacy social and new quick shortcuts deliberately lead to the same existing
  panel; no second implementation or notification sender is introduced.

## Acceptance

Required: full offline suite and Python 3.11 CI; deployment status; fresh quick bar
and both read-only shortcuts in Discord; social modal opened then cancelled;
old posted menu callback; language/row and permissions regressions. Do not send an
anonymous confession, change subscription consent or create a room to test a
navigation-only change.

Stage 4 is not a claim that every external Bot dashboard has been audited, nor
that native mobile layout has been tested. External Bot removal and migration of
Carl logs/reaction-role panels require a separate concrete dependency review.
Stage 5 remains maintenance/health/permission-change monitoring.


## Acceptance results — 10 November 2026, 20:28–20:34 Hong Kong

- #108 passed 556 local tests and Python 3.11 CI. Fly deployment run
  42815772615 completed successfully, including machine-status verification.
- Live sandbox: new /menu displays both shortcuts; notification settings opens
  the existing private empty state and returns to the quick bar. No subscription
  was changed.
- Social → confession opens the original form; cancelled without submitting.
- Info → Help identifies Con9sole-Bartender and documents the new shortcut.
  Management shows the existing permission-audit entry and capability-filtered
  description. No permission or configuration write was performed.
- Voice controls outside voice initially sent the correct notice followed by a
  generic error. #109 fixes the helper passing view=None by using the existing
  safe sender. 557 tests and Python 3.11 CI pass; Fly run 42816543631 completed
  successfully with machine-status verification.
- Post-fix voice-control retest sends only the expected no-current-room notice.
  A pre-restart, still-valid Help-menu control button and notification shortcut
  both respond after deployment. No room creation was needed for this entry test.
- HK live wording and offline HK/TW labels, stable IDs, legacy registration,
  capability filters and row limits pass. This is not new live TW-account or
  native-mobile acceptance; Stage 3 evidence remains separately documented.
- A several-hour-old ephemeral menu timed out. Fresh /menu works; private menus
  are not promised indefinite lifetime. Historical public posted-menu callbacks
  were not freshly clicked in this stage; persistence/legacy coverage is offline
  plus Stage 3's documented live evidence.

No external Bot dashboard was freshly audited or Bot removed. This closure covers
the implemented entry consolidation and documented responsibilities; it does not
certify every external Bot's enabled configuration. Stage 5 remains separate.
