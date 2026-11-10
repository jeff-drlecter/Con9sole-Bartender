# Stage 4 — Bot functions, entries and responsibilities

Started 10 November 2026 (Hong Kong). Base main `01c531a` (#107).
Status: implementation prepared; CI/deployment/live acceptance pending.
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
