# Stage 3 — Hong Kong / Taiwan wording

Baseline: main 121a4a0061bc0029d8cc647b182f76a9f618bb65, checked 10 November 2026.
Stage 2's alert-only baseline is closed in merged PR #103. Its documented limitations and manual restoration policy remain. Stage 1 is not repeated.

## Delivery and coverage

| Surface | Changes |
| --- | --- |
| Main / section / help | Existing role preference preserved. Fallback menu now localized. Both help variants list the same features, short enough for mobile. |
| Member card | Requester's preference selects navigation, title and fixed field labels; target member and field values are preserved. |
| Recruitment / footprints | Shared cards and notices use neutral Traditional Chinese. Game/room/player names remain untouched. |
| Subscriptions | Private confirmations use the clicker's current preference; shared buttons use 下次通知我 / 每次通知我. No consent or delivery changes. |
| Voice rooms | Created/control templates support viewer preference, interpolate room names after choosing copy. Fixed administrative/error paths use neutral wording. |
| Management | Top-level labels and descriptions use matching Chinese labels while retaining existing routing keys. Deep diagnostics remain outside this pass. |
| Errors | Shared private response helper translates exact known copy; command cooldown and UI failure paths support current preference. Public sends do not inherit one viewer's language. |

Existing zero-permission language role names, default HK, dual-role fallback and onboarding mappings are unchanged. No data migration or new dependency. No permissions, anti-scam configuration, XP policy, subscription storage or timing logic changes.

## Compatibility

No custom IDs, option values, routing keys or persistent-view registration are renamed. Old public cards keep their wording until normal refresh. Existing old roster field names 下次叫埋 / 每次都叫 remain recognized for removal alongside new names, so refreshing old cards cannot expose stale public subscription lists. No bulk historical edits or broadcasts.

Localization uses exact known strings; templates are selected before inserting dynamic names. Embed field values are not translated. Existing emoji-prefix support is retained; no general substring conversion is introduced.

## Verification

551 unit tests pass (six new Stage 3 tests), with compile and whitespace checks. Coverage includes both preferences, unchanged custom IDs/option values, requester-only rendering, public-send isolation, unknown dynamic names, old field cleanup, menu/help parity and message length. Existing squad lifecycle, delivery, permissions and XP suites remain passing. GitHub CI, deployment and live results are recorded separately after execution; unit tests do not establish live Discord appearance.

## Not covered / acceptance still open

- Full regional variants for drink flavour text, cheers quotes, collection/theme lore, detailed level/role/admin audit diagnostics and unrelated activity/update-publisher editors. These are older feature content, not silently claimed translated.
- Discord-native client labels and server channel names, user-authored announcements, names and historical messages.
- Actual mobile-device rendering, every destructive management action, every legacy historical message, and broad live tests of all games.
- Stage 3 remains OPEN until deployment and live preference/legacy-menu acceptance are recorded. Later coverage must start from this inventory rather than repeating Stage 1/2.
