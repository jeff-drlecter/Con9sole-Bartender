# Unified management status

Open `/bot_health` or More → Management tools → System status.
The private panel is bound to its owner and rechecks current staff permissions.
Refresh updates the same message and renews the panel timeout.

The dashboard reports loaded modules, scoring mode, voice/squad/title loops,
role queues, title mapping safety, database checks, notification queues,
uncertain recruitment cards and pending end-of-session notification edits.
Database queries remain available even when the leveling cog failed to load.
Running loops are not proof that individual jobs succeeded; the timestamp is
when the snapshot was read, not the last successful job execution.

Admins also have direct links to level/title management and scoped notification
review. The recent notification audit shows the latest ten subscription/weekly
review actions, actor IDs and timestamps; it does not ping actors or recipients.
Missing/unreadable databases are distinguished from an empty audit history.
Helpers and moderators can view status but cannot use admin review controls.

Unknown send outcomes must be checked in the original channel before a scoped
review or `/squad_recover`. No dashboard action automatically changes XP,
reassigns roles, restarts loops, clears queues or broadcasts notifications.
Known end-of-session notification edits continue to use the existing background
retry/backoff and saved message IDs.
