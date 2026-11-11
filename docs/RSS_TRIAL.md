# RSS shadow trial

Three days from the first load; state survives restarts in `DATA_DIR/rss_trial.sqlite3`.
The Bot checks 4Gamers, Xbox Wire and PlayStation Blog every 20 minutes sequentially.
Steam remains disabled. MonitoRSS stays in production. No public delivery, translation,
mentions, new machine, volume or paid service is introduced.

First successful response per source establishes a baseline. Subsequent new IDs/links
are recorded with the audited ANY regex filter and one-day date gate. Regex matching
is case-sensitive in this trial; compare actual MonitoRSS outcomes before cutover.
Rate limits and 50/day caps are not simulated: would_deliver means eligibility before
those limits. No delivery queue is activated in shadow mode. XML responses are capped
at 2 MiB decompressed and 500 entries; DTD/entities are rejected. Errors retry next poll.
HTTP validators reduce repeat transfers; article identity is persisted in SQLite.

Administrators can use `/rss_trial_status` for an ephemeral report. Fly application logs
also include per-poll counts, failures, fetched bytes and whole-process current/peak RSS.
These are not incremental memory, wire egress, full VM memory, or actual invoice costs.
For the US$5 target, also inspect Fly VM memory and organization Cost Explorer.

Stop early with `RSS_TRIAL_STOP=1` and restart the Bot. Expiry never enables delivery.
Before any cutover: compare eligible article links against MonitoRSS for 3 days, resolve
parser/filter differences, check restart deduplication and RAM, and implement/test queue,
daily cap, Discord format and retries. Then switch one source at a time. Keep original
MonitoRSS settings as rollback. No automatic switch occurs.

## 11 November migration check

Live status at 19:46 HKT: each source had 60 checks; PS and Xbox had zero
errors and three eligible new articles each. 4Gamers failed all 60 checks.
Whole-process peak RSS was 76.3 MiB; this does not establish monthly cost.

The old 4Gamers `/rss/news/c/2` URL returned HTTP 200 HTML, not XML. Its
HTML advertises `https://www.4gamers.com.tw/rss/latest-news` as the RSS
alternate. A live check of that endpoint parsed 50 articles with the existing
parser. It is a broader latest-news feed; the existing audited filters remain
unchanged, so compare its eligible output before production use.

The source fix preserves the database and original expiry. Failed polls never
created a baseline, so the first valid 4Gamers response establishes one without
backfilling. The status command now includes the last recorded historical error
per source, even after recovery. This fix does not enable delivery or reset the
three-day trial. Queue, caps, retries and output comparison remain cutover gates.
