# Categorized news delivery

Production code is staged with `docs/rss_production.json` set to `enabled: false`.
MonitoRSS must remain active until its three replacement connections can be paused.

## Member experience

The existing PS, Xbox and PC channels stay read-only. Each scheduled news card
includes persistent My News, Preferences and News Channels buttons. Results are
ephemeral and use the existing member/channel access guard. No new DMs, role
mentions, announcements or automatic crossposting are introduced.

At 19:00 Asia/Hong_Kong each category sends at most eight eligible articles.
The existing 12:30 verified-expiry reminder window remains; without a reviewed
offer there is no reminder. Empty categories do not send an empty card.
This is a daily digest, not the former per-article MonitoRSS cadence.

| Source | Destination | Selection |
| --- | --- | --- |
| PlayStation Blog | ps-news | Existing exclusions and ranking |
| Xbox Wire | xbox-news | Existing exclusions and ranking |
| 4Gamers | 電腦-news | Explicit PC, Steam or Epic Games text clues |

PC classification is conservative and can miss articles without those clues.
Steam/Epic adapters remain separate and are not newly enabled for public output.
Existing per-member settings remain in their original persistent database.

## Cutover and verification

1. Deploy the staged configuration and use `/rss_delivery_status` to verify all
   three destinations and successful source polls. Use `/rss_digest_preview`
   for private category previews, including the same card buttons.
2. Verify a visible card with an ordinary member; an admin result is not a
   substitute. Verify My News, Preferences and News Channels independently.
3. Pause only the corresponding MonitoRSS connections. Keep their configuration
   and keep any unrelated services. Record the UI status before switching.
4. Set production `enabled` to true and deploy. Each route takes its first
   successful feed snapshot as a baseline and does not replay that history.
   Only subsequently discovered articles can be sent. The small handover window
   may omit an article; it is deliberately not backfilled as a duplicate burst.
5. Inspect scheduled output and route batch reports. Sending/uncertain batches
   require manual inspection and never automatically resend.

## Rollback

Set production enabled false and confirm the running deployment before resuming
MonitoRSS. Preserve route databases and preference data. Do not enable both
publishers together. Discord member/iPhone interaction and the first real
scheduled delivery still require live verification.
