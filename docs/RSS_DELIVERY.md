# RSS delivery cutover

Implemented but OFF by default. Setting `RSS_DELIVERY_SOURCES` to a comma-separated
subset of `ps,xbox,4gamers` starts the delivery cog after restart. An empty value
stops delivery. Unknown names fail closed. Steam is not supported or reactivated.
The existing shadow trial remains independent and expires on its original schedule.

## Behavior

- Uses the existing channel IDs, RSS parser, one-day date gate and 4Gamers filters.
- First successful fetch per source seeds a separate persistent baseline. It sends
  no articles already in that response. Failed fetches never seed a baseline.
- Subsequent eligible stories enter `/data/rss_delivery.sqlite3`. Primary keys
  deduplicate across restarts. Process sources sequentially every 20 minutes;
  send at most one story per source every 30 seconds.
- A rolling 24-hour cap permits 50 queue send attempts per source, including retries.
  A definitive HTTP 429 is retried with bounded exponential delay, at most five
  attempts. Discord.py also handles its normal transport rate limiting.
- A timeout, connection failure, HTTP 5xx or crash during sending has ambiguous
  delivery status. `uncertain` or `sending` is held for manual review and is NOT
  resent automatically. This chooses avoiding duplicate posts over guaranteed
  delivery. The private `/rss_delivery_status` reports these states.
- Older-than-one-day queued stories expire. Failures in one source do not stop the
  others. Missing permissions/channels leave stories queued.
- Posts one source-attributed embed with title, original link and a summary excerpt.
  No role/everyone pings, translation API calls, new machines or announcement
  crossposting. Match this preview against the desired MonitoRSS format first.

## Required before live cutover

1. Complete and inspect the shadow run; 4Gamers needs fresh observations after the
   repaired URL first succeeds. Compare actual article URLs, filters and source
   coverage; the replacement endpoint is broader than the broken category URL.
2. Check Fly's actual memory and billing against the existing US$5/month target.
   Process RSS alone is not a bill estimate.
3. Record/export the source's current MonitoRSS destination, format, filter, cap and
   enabled state. Verify Bartender can view/send/embed in the same destination.
4. Choose one source, disable ONLY its MonitoRSS connection, then enable ONLY that
   source in `RSS_DELIVERY_SOURCES` and restart. First-fetch baseline deliberately
   discards existing entries: reconcile any news arriving during this transition
   manually. Do not run both publishers simultaneously for the same source.
5. Verify a new post's content, attribution, destination and absence of duplicates;
   check the private status and restarts before switching the next source.

## Rollback

Remove the source from `RSS_DELIVERY_SOURCES`, restart and verify it is disabled,
then re-enable its original MonitoRSS connection. Retain both trial and delivery
SQLite databases. Never delete deduplication state to retry a failed migration.
Before resuming Bartender later, reconcile queued stories against what MonitoRSS
published during the rollback. Re-enabling without reconciliation could replay
those queued stories; it is not an automatic failover mechanism.

## Current evidence (11 November 2026)

PR #117 repairs the old 4Gamers HTML endpoint. Before that deployment, PS/Xbox each
had 60 polls, zero errors and three eligible articles; 4Gamers had 60 failures.
Trial expiry is 14 November 00:01 HKT. After deployment, the next live poll succeeded and established 50 baseline
articles for 4Gamers (61 polls, 60 historical errors). Formal delivery has not
been activated.
