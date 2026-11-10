# Stage 3 — Hong Kong / Taiwan wording

Status: CLOSED for the documented Stage 3 surface set after live acceptance on 10 November 2026, 15:59 Hong Kong.

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

553 local unit tests pass, including seven Stage 3 copy cases for room-name preservation, default/dual-role behavior, unchanged persistent IDs/callbacks, preference changes on reused controls, modal defaults and subscription game names/state. Existing functional tests retain permission, consent, timing, uncertain-delivery and accounting assertions; copy assertions updated for neutral shared labels. Production Python 3.11 compatibility is checked by CI.

Deployment and baseline live acceptance completed; see the final evidence below. Review limitations: this is the listed Stage 3 surface set, not a full translation of every legacy admin audit/export, drink narrative, external Bot, slash-command schema, Discord-native channel name or historical message. Shared card refresh cadence is unchanged. No destructive or scoring-changing live drill is required for copy acceptance.

## First live acceptance and blocking compatibility fix

HK account `jeff_drlecter`: menu, member card and health panel replied normally. Health reported loaded systems, running loops, zero queued role work and zero pending/uncertain notices. TW account `jeff_con9sole`: menu showed 吧台／喝一杯／找人一起玩／小隊語音房; member-card return showed 吧台; subscription panel instructions/footer used Taiwan copy without changing preferences. A pre-deployment footprint's existing roster button returned the private roster using the original dispatch IDs. No subscription was toggled.

TW `/vc_new` created room `1569605485445906432` but then failed in cosmetic sorting: `guild.fetch_channels()` raised `discord.InvalidData` for the existing unsupported type-20 channel. Logs show the same bootstrap error before Stage 3. Treat InvalidData like the existing HTTP sorting failure: log it, retain ownership, complete cleanup scheduling and return the created room. Do not bypass room access checks or change its permissions. Regression exercises actual manual creation with failing fetch and verifies ownership plus empty-room cleanup scheduling. This first-pass blocker was resolved in #106 and the final live re-test below passed.

## Final live acceptance — 10 November 2026

- #104 (`587625d`) passed Python 3.11 CI 42769911248 and Fly deploy 42770045744. #106 (`5f1a8f9`) passed CI 42771847126 and Fly deploy 42771933418, including machine status verification. No later runtime code was required for closure.
- HK menu, member card and read-only health panel passed. Systems loaded, relevant loops running, zero queued role work and zero pending/uncertain notification work observed.
- TW account retained its existing preference. Menu/card navigation, own subscription instructions/footer, pre-deployment footprint roster callback, existing-room controls and the rename modal all passed. Modal was cancelled, without renaming or submitting data. No subscription consent changed.
- Reconciled the 15:04 uncertain UI result through production logs: room `1569608579827105932` created at 15:04:07 and deleted empty at 15:06:08 Hong Kong. The browser's Sending command display was not evidence of a backend failure; no blind replay was performed.
- At 15:59, with no remaining owned test room, one fresh `/vc_new` returned **臨時語音房已建立**, unchanged default name **小隊call • 1**, limit **32**, **祝大家聊得開心**, and **重新命名／修改人數上限／返回吧台** controls. This completed the previously pending new-room response acceptance. Empty-room cleanup remains the existing 120-second mechanism.
- User language-role preferences, access policies, AutoMod, XP rules and subscriptions were not changed. No punishment, announcement or destructive member action was used for copy testing.

Closure is for the documented UI surface set and smoke checks. Legacy audit/export text, drink narratives, external Bots, native slash-schema/channel names and historical card bodies are not claimed fully translated. Mobile label lengths/rows were kept compact and protocol tests pass; a separate native iOS/Android visual test was not performed. Cosmetic numeric voice sorting is skipped and logged when discord.py cannot parse the bulk channel list; creation/control/cleanup now continue safely. Reopen only for a new defect or a requested expansion of these limits.
