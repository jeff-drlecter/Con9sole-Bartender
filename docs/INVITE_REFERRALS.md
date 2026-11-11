# Invite sources and member referrals

Member entry points: after 我的組隊通知 in the newly rendered Quick Bar; first row of the More menu and community rankings; `/invite` is also available. Existing invite buttons route to the new personal link flow. Previously posted messages retain their old button layout until refreshed.

Personal links are generated lazily against the existing public `INVITE_CHANNEL_ID` (rules). One stored permanent unique code per member is reused. A revoked/missing code may be replaced only for that member; the feature never revokes, recreates, moves, or edits any existing platform link or source channel.

Management tools:

- Admin menu → 平台邀請連結: private source selector discovered from the live invite list and existing source channel names, excluding tracked personal codes. Live status and usage are fetched before returning a link. No automatic replacement for missing platform links.
- `/invite_sources [member] [days]`: admin-only, private tracked join history or aggregate sources (omit days for all tracked history; use 7/30 for those windows). Platform names reflect the existing source channel names; publication locations remain unverified.
- `/invite_panel channel:<channel> platforms:<true|false>`: admin-only placement of a persistent platform selector entry or member invite/results/leaderboard card. Platform entry still checks administrator/manage-server permissions on every interaction, even if posted in a public channel.

## Attribution and limits

Snapshot guild invite usage counts at startup/resume. Correlate joined members in a two-second window. Attribute only if a single invite usage delta explains the whole batch. Multiple changed codes, missing codes, permission failures, disconnections, or mismatched counts remain unknown. Do not infer a member's intention. Reconnect establishes a fresh baseline and does not retroactively credit offline joins. An invite shared elsewhere retains its original source label.

Persist member IDs, join/leave timestamps, invite code, inviter ID, and reward receipts in the existing XP SQLite file under the persistent data directory. No message text or device/IP information is collected. Startup seeds known current members and historical membership/XP records to avoid rewarding known returners; members with no surviving historical evidence cannot be proven to be first-time server members. Leave tracking reflects events observed while the bot runs, not verified current retention after downtime.

## Rewards and rankings

A confirmed personal referral awards the inviter 25 EXP after the new member holds the existing verified role and has passed Discord pending screening. Inviter must still be a current, eligible human member. Unknown sources, bots, self-referrals, known existing/returning members, departed join generations, and repeated verification updates do not receive rewards. No historical invite totals are converted into EXP.

The receipt, XP event, total XP, weekly XP, and pending level-role job commit in one SQLite transaction. Permanent reward receipts survive leave/reset and process restart; one invited account can produce at most one reward for the server. Mode off/preview never consumes the reward. Pending qualifying rewards retry every minute while both membership generations remain current. Reward role updates use the existing leveling reconciliation flow.

Leaderboards show rewarded invite counts and awarded EXP, with Hong Kong calendar month/all-time choices. They record historical rewarded contributions and are not a current retention leaderboard. There is no automatic EXP clawback on a new member leaving. Basic deduplication cannot prove that different Discord accounts are different people.

## Deployment checks

Needs existing Guild Members intent and Manage Server (list invites), plus View Channel/Create Invite on the configured public entry. No new role permissions are granted by this change. Verify a personal link can be retrieved twice, old platform link selection returns the exact existing URL, verification credits once, a leave/rejoin does not credit again, and buttons remain functional after restart. Add persistent cards to the existing guide/Admin archive using `/invite_panel` after deployment.

Invite codes are never embedded in the new source/configuration: platform choices are read live from Discord; personal codes and attribution remain only in the runtime SQLite database.
