# Notification review and member navigation — 2026-11-08

Admin entry: More → Admin Tools → System Status → Review Notifications.
The panel is private, scoped to the guild and original operator, and permissions are
checked again when a modal is submitted and immediately before writing a resolution.
Weekly actions additionally require Manage Server or Administrator permission.

## Resolution

- Browse unresolved recruitment batches and weekly publications, ten entries per page.
- Mark sent: provide a real Discord message link plus a reason. The Bot fetches the
  message and checks guild, access, author, and the exact weekly period or original
  recruitment card link and recipient batch. Ephemeral previews cannot serve as proof.
- Retry: explicitly confirm with a reason. A recruitment session must still be active,
  match the original game and destination, and have participants. The sender rechecks
  current recipient access; only the selected original batch is retried.
- Cancel: recruitment batches can be cancelled with a reason, including after the
  session ends. Cancellation is distinct from a sent receipt and does not alter other
  notification subscriptions. Weekly cancellation is not offered.
- Every resolution stores operator, reason, time and outcome. CAS state/revision checks
  reject old panels; a new revision also rejects late acknowledgements from old sends.
- Normal and manual recruitment delivery share a per-session lock; weekly handling
  shares the level publication lock. These are single-process controls alongside the
  durable SQLite compare-and-swap checks, not a distributed delivery guarantee.

Retrying an uncertain send can duplicate a notification if it actually arrived before
the connection failed. The UI requires explicit channel review; it never automatically
retries uncertain outcomes. Sent and cancelled records cannot be rearmed from the list.
Legacy claims without sufficient original message context cannot be automatically
verified as sent; administrators can cancel an obsolete recruitment notification.

## Navigation

| Surface | Added or aligned navigation |
| --- | --- |
| Member card | Collection, task, level total/week, return to bar; small button rows |
| Level boards | Card, collection, task, alternate board, bar, previous/next page |
| Daily task | Card, collection, refresh, bar; completed task stays disabled |
| Collection | Card, bar statistics/tasks and return; title selector retains its own row |
| Drink/cheer result | Collection, gift, card, return; persistent IDs retained, two buttons per row |
| Bar statistics/boards | Explicit bar-ranking label, card/collection/return controls |
| Theme collection | Card and return alongside existing theme/title controls |
| Squad voice / cancelled team | Consistent return-to-bar wording; existing domain actions retained |

Level-board paging preserves the selected week and never awards XP. Browsing remains
distinct from the existing explicit daily task completion reward. No announcement is
created or published by this change. Final automated and live acceptance results are
reported separately from implementation.
