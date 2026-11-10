# Stage 3 — Hong Kong / Taiwan wording

Base: `121a4a0` (Stage 2 alert-only baseline closed by #103). Stage 1 is not re-opened. This change does not modify roles, permissions, AutoMod, scoring, cooldowns, subscriptions, notification recipients or stored schemas.

## Display policy

- Personal interaction replies use the requesting member's existing zero-permission wording role. No location inference, no preference migration. Missing/conflicting roles retain the Hong Kong default.
- Shared recruitment/footprint cards and session notices use neutral Traditional Chinese. They never adopt the last button-clicker's preference.
- Translate exact Bot-authored literals before inserting dynamic values. Member/game/room names, submitted content, select labels/values, IDs, URLs and mentions remain original. No runtime substring or AI translation.
- New private controls translate display labels/placeholders only; callbacks, custom IDs, selected values, disabled states, page limits and ownership checks remain. Existing persistent squad IDs remain dispatchable.
- Existing messages are not bulk rewritten. Newly rendered/regularly refreshed shared cards get neutral copy through the existing lifecycle, without reposting or introducing notifications.

## Coverage

| Surface | Change |
| --- | --- |
| Main/category/help menus | Existing menu dictionary retained; expanded control labels; mention entry now uses the same preference path |
| Membership card / levels | Read failures, private admin responses and new card/navigation controls use the requesting member's wording; numeric fields remain unchanged |
| Recruitment / footprints | Neutral shared headings, roster labels and once/recurring buttons; personal consent/edit replies localized |
| Subscription settings | Requester's preference passed to private panel; placeholder, instructions, footer and return controls translated; game names and option values unchanged |
| Temporary voice rooms | Creation/control/cleanup text, common errors and modal labels localized; actual room names remain unchanged |
| Management / errors | Health descriptions/footer, menu authority errors, levels administrative replies and shared UI exception reply localized |

## Validation

551 local unit tests pass, including six Stage 3 cases for room-name preservation, default/dual-role behavior, unchanged persistent IDs/callbacks, preference changes on reused controls, modal defaults and subscription game names/state. Existing functional tests retain permission, consent, timing, uncertain-delivery and accounting assertions; copy assertions updated for neutral shared labels. Production Python 3.11 compatibility is checked by CI.

Deployment/live acceptance pending at initial PR creation. Review limitations: this is the listed Stage 3 surface set, not a full translation of every legacy admin audit/export, drink narrative, external Bot, slash-command schema, Discord-native channel name or historical message. Shared card refresh cadence is unchanged. No destructive or scoring-changing live drill is required for copy acceptance.

## First live acceptance and blocking compatibility fix

HK account `jeff_drlecter`: menu, member card and health panel replied normally. Health reported loaded systems, running loops, zero queued role work and zero pending/uncertain notices. TW account `jeff_con9sole`: menu showed 吧台／喝一杯／找人一起玩／小隊語音房; member-card return showed 吧台; subscription panel instructions/footer used Taiwan copy without changing preferences. A pre-deployment footprint's existing roster button returned the private roster using the original dispatch IDs. No subscription was toggled.

TW `/vc_new` created room `1569605485445906432` but then failed in cosmetic sorting: `guild.fetch_channels()` raised `discord.InvalidData` for the existing unsupported type-20 channel. Logs show the same bootstrap error before Stage 3. Treat InvalidData like the existing HTTP sorting failure: log it, retain ownership, complete cleanup scheduling and return the created room. Do not bypass room access checks or change its permissions. Regression exercises actual manual creation with failing fetch and verifies ownership plus empty-room cleanup scheduling. Final voice live re-test pending this fix.
