# Helper activity sandbox

Enabled only by `HELPER_SANDBOX=1`. On startup it creates `helper-模擬區` under the
existing RSS sandbox category, with explicit @everyone View Channel denial and
Helper (`1279071042249162856`) / exact `🧪 Tester` role view, history, send and
interaction permissions. No game-category permissions are changed. Missing roles,
conflicting room names, or uncertain creates fail closed for inspection.

The shared board contains clearly fictional MH help, GTA/Helldivers conversation,
and FC voice examples. It refreshes the same message every two minutes without
pings. Members can create one active test request each (global maximum 20), claim,
handoff or finish it. Atomic database transitions prevent two helpers claiming
one request. Only the owner or an administrator can finish/handoff. Completed
requests cannot be reopened by stale controls. Preferences, demo workflow and
history persist in `/data/helper_sandbox.sqlite3`. The history button shows the
last 20 transitions, including to later-joining testers. Duty toggling is only a
saved demo preference; it sends no real alerts.

The private live-activity button is real, but scoped to each viewer's current
permissions. Game categories are those with the configured `開一個小隊 call` hub,
excluding archive/hidden category names. Text activity uses human message events
in ordinary text channels only, retaining timestamps, channel/user IDs for a
30-minute rolling window, capped at 10,000 events in memory. It does not store
message text, backfill history, inspect private threads, or infer help from words.
View Channel AND Read Message History are checked for each text channel before
counts are included. Users are deduplicated across visible channels in a category.
Voice cards require View Channel AND Connect, exclude bots and hubs, and show
current occupants as a count. Start times are only stated as observed times;
preexisting calls have unknown start times. Nothing listens to voice audio.

No public live activity forwarding, real help request intake, duty notifications,
new-member detection or automatic escalation is enabled in this prototype. The
board and controls are restricted to Helper, Tester and administrators, in the
configured sandbox guild/channel. Private replies are not public channel history.

Acceptance: inspect the shared demo, create a test request, have two testers try
to claim it, verify one owner, hand it off and resolve it. Reopen the history after
restart. Compare live summaries as users with different game permissions; hidden
channels and inaccessible voice rooms must not appear. Lack of observed text
activity is explicitly not presented as proof that a category is inactive.

Deployment verifies the real channel's role overwrites, historical visibility,
five persistent controls and the fictional label via read-only Discord API calls.
