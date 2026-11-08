# Whole-bot integration review — 2026-11-08 (Hong Kong)

Scope: menus, bar/collections, cheers, daily tasks, levels, recruitment/footprints,
subscriptions, temporary voice rooms, role tools, publisher and activity reminders.
This is a source review with isolated tests, not a claim of exhaustive live acceptance.

## Consistent user model

- Quick bar is the main entry; My Member Card is the personal progress entry.
- Collections and daily tasks link from the member card; rankings distinguish level XP from drink statistics.
- Successful drink and cheer actions use one integration service and the existing shared text/activity cooldown.
- Viewing cards, collections or rankings never awards ordinary activity XP.
- Explicit owner-requested exception: completing the selected daily task grants an extra fixed 5 XP, once per member per Hong Kong day, including weekly XP, without touching engagement cooldown or Booster multiplication.
- A collection-view task can therefore earn its daily task bonus; repeated collection views cannot earn ordinary XP or repeat the task bonus.
- Task completion lives in the stats database; reward receipt and score update commit atomically in the level database. Reopening today's task retries an unclaimed reward. Already committed receipts prevent double rewards after restart or reply failure.
- Existing UTC task history is preserved. Current task selection/completion now uses Hong Kong midnight; no historical task bonus backfill or historical date rewrite is performed.

## Reviewed integration and disposition

| Area | Finding | Local change / remaining work |
| --- | --- | --- |
| Bar / cheers | Only drinks were connected to XP | Shared successful-action integration; cheers now joins the same path; no duplicate fallback after uncertain award |
| Daily tasks | UTC day differed from Hong Kong XP calendar; no reward | Hong Kong day, +5 daily receipt, weekly points, role job; retry via current task page |
| Member card | Tasks required a separate menu trip | Task button alongside collection and rank navigation |
| Subscription actions | Fixed game/user event ID suppressed all later XP | Receipt now includes interaction ID; successful new subscriptions remain subject to shared cooldown |
| Role tools | Helper could use Bot hierarchy to grant dangerous roles | Central actor authorization, dangerous-permission and target hierarchy checks across slash/menu/bulk; mapped level roles must use level management |
| UI / help | Old Amari prompt and missing level help / stats labels | Member-level wording and current help/labels aligned |
| Recruitment notifications | Reservation consumes one-shot subscriptions before Discord send | Still open: distinguish pending/sent/failed without blindly replaying an uncertain send |
| Returning members | Required Lv5 baseline missing; stale lifecycle events can overwrite/recreate XP | Still open: membership-generation fencing and one return baseline; separate release and race tests required |
| Exclusions | Queued event can outlive eligibility change | Still open: recheck text/activity eligibility inside ledger lock |
| Level audit / import | Retained inventory and hybrid overwrite safety gaps | Still open: reset generations and incompatible-import guard |
| Weekly publisher | Cancellation can leave a claimed but unsent result | Still open: recoverable pending/sent state |
| Voice / role repair | Slow role REST work shares voice timer work | Review bounded repair budget before claiming fault isolation |
| Operational health | Several individual state stores and background loops | Still needed: one read-only health dashboard for scoring, storage, voice, notices and pending retries; no silent success when a subsystem fails |

Independent reviewer reproduced the role escalation using fake Discord members only.
No evidence of live exploitation or historical score corruption was established.
No public announcement, production score edit or subscription replay is part of this review.

Validation for this local integration round: 356 tests pass, including 10 role authorization
regressions, subscription receipt separation, shared action single-path handling and daily
bonus cooldown/receipt/midnight tests. Live acceptance and deployment are separate states.
