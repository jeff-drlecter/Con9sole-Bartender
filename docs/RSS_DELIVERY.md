# RSS digest preparation (PR #118)

Private simulation deployment is configured; MonitoRSS remains the production publisher.
This replaces the draft's per-article delivery loop with one combined digest.

## Reader experience

- **19:00 Hong Kong:** one message, up to eight items across selected sources.
  Each item has a platform/source label, short title, up to 150 characters of
  source excerpt and an original link. This is extractive, not an AI-written
  summary or an independently verified explanation of player impact.
- **12:30 Hong Kong:** at most one extra message with up to four verified offers
  ending after 12:30 and at/before 19:00. No confirmed qualifying offer, no message.
- No content means no post. No role/everyone mentions, automatic crossposting,
  translation API calls or new servers. Jobs collect every 20 minutes but publish
  only within the scheduled 15-minute windows. Downtime outside those windows
  does not cause a catch-up burst. Deadlines outside this reminder window need
  separate future policy; this is not a guarantee of alerting on every short offer.
- Same canonical URL or exact normalized title is merged across sources, including
  tracking URL aliases. This does **not** claim semantic deduplication of differently
  worded reporting. Per-story game/platform classification and private member
  browsing are future extensions, not implemented features.

## Configuration and preview

`simulation: true` (the default) uses a separate `rss_simulation.sqlite3` database,
labels every scheduled post as simulation and requires a private channel named
`rss-模擬區`. Production delivery requires an explicit future configuration change.

`RSS_DELIVERY_SOURCES` selects the existing collectors: `ps,xbox,4gamers`.
Empty means no collection or publishing. Steam and Epic adapters are not yet built.

`RSS_DIGEST_CONFIG` points to a local UTF-8 JSON file (max 64 KiB). Start from
`docs/rss_digest.example.json`. With sources selected and `enabled: false`, the
collector runs but public delivery stays off. Set an actual destination channel
ID only after choosing where the **single combined digest** should live; it no
longer fans out to all three existing platform channels. `channel_id: 0` deliberately
cannot be enabled. Configuration changes require a Bot restart.

| Setting | Effect |
| --- | --- |
| `include_any` | If nonempty, require any one phrase in title or summary |
| `exclude_any` | Any match excludes; exclusion wins over all other rules |
| `boost_any` | Matches increase ranking, but never force an excluded item in |
| `max_items` | One to eight items, no minimum filler count |

Keywords are literal substrings, Unicode-normalized and case-insensitive. They
are **not regular expressions**. Empty `include_any` accepts all non-excluded news.
These controls replace the old 4Gamers-only case-sensitive regex for the digest;
the independent shadow trial retains its original filters for comparison.

Administrators can use `/rss_digest_preview` for a private, non-consuming preview
or `/rss_delivery_status` to inspect article/batch states. Preview does not publish,
reserve a schedule slot or alter deduplication state.

## Verified offer metadata

Generic RSS headlines do not prove free-to-keep status, region or a deadline.
The reminder engine therefore accepts only explicit verified metadata in `offers`,
keyed by the article's canonical HTTPS URL. For example (illustrative, not a real offer):

```json
"offers": {
  "https://example.com/official-offer": {
    "kind": "keep",
    "ends_at": "2026-11-20T18:00:00+08:00",
    "verified": true,
    "region": "香港"
  }
}
```

Kinds are `keep` (permanent claim), `trial` (limited play), `member` (subscription
benefit) and `f2p` (normally free). Normally-free games never trigger expiry reminders.
A matching article must have entered the queue after its initial baseline. A
previously digested offer may get one reminder; an expired offer is omitted.
Metadata must be checked against the official offer, including region and membership
requirements. `verified: true` is an operator assertion, not automatic verification.
Automated Epic/Steam offer discovery and verification remain **not implemented**.

## Sources and research follow-up

| Area | Present input | Next verification |
| --- | --- | --- |
| PS | Traditional Chinese PlayStation Blog RSS | HK/Asia PS Plus eligibility, store links, output relevance |
| Xbox | Xbox Wire RSS | Separate Game Pass additions/removals from Free Play Days and permanent giveaways |
| PC/general | 4Gamers latest-news RSS | Broad gaming coverage; refine PC/game keywords and exclusions |
| Steam | No collector yet | Per-game announcements vs platform news; official offer deadline/region |
| Epic | No collector yet | Official free-games promotions, deadline/region; exclude normally free games/demos |
| Other | Candidate only | GOG giveaways, major patches, crossplay, service maintenance and subscription departures |

Primary references:
- https://blog.zh-hant.playstation.com/feed/
- https://news.xbox.com/en-us/feed/
- https://www.4gamers.com.tw/rss/latest-news
- https://store.epicgames.com/en-US/free-games
- https://partner.steamgames.com/doc/marketing/discounts/freeweekends

Steam Free Weekends are time-limited play, not permanent ownership. Epic's free
page includes multiple kinds of free content, so matching the word "free" is
insufficient. Do not treat an undocumented promotion endpoint as a stable API or
promise a monthly cost based only on process memory.

## Durability and delivery failures

The first successful fetch establishes a per-source baseline without backfill.
New eligible articles are persisted in `rss_delivery.sqlite3`. Bad HTTP/XML never
establishes a baseline. Digest selection considers news from the past 24 hours;
old leftovers do not automatically flood subsequent digests. Filtering happens at
selection time, so a configuration adjustment can affect pending stories.

A SQLite transaction reserves a date/kind slot and its deduplication identities
before sending. Restarts cannot send it again. Definitive HTTP 429 refusals retry
up to three times, with exponential delay, within the same 15-minute slot window.
Timeouts, HTTP 5xx and crash-interrupted sends stay `uncertain`/`sending` for manual
inspection. This deliberately avoids blind duplicate retries; delivery is not
guaranteed after ambiguous failure. The old individual-article queue methods remain
internal compatibility code and are not called by the publisher.

## Before replacing MonitoRSS

1. Finish the repaired shadow run and compare article URLs, categories and source
   quality. Confirm every desired source has a tested collector; Epic/Steam
   giveaways are not covered merely by including general PC news.
2. Select the combined digest destination, keywords and offer verification source.
   Run with public publishing disabled and inspect private previews. Confirm the
   intended platform/language coverage and current Fly costs against the US$5 target.
3. Back up each MonitoRSS connection's settings. Disable only sources about to be
   replaced, then enable the matching Bartender sources and digest destination.
   Never leave both publishers enabled for the same source. Reconcile articles
   during the transition: baseline seeding deliberately does not backfill.
4. Verify one actual scheduled digest and any qualifying reminder before completing
   the cutover. Check formatting, links, filters, caps, restarts and lack of duplicates.

Rollback: set `enabled:false`, restart and verify no public delivery, then restore
original MonitoRSS connections. Retain both SQLite databases. Before resuming a
future cutover, reconcile pending articles against MonitoRSS output; do not delete
state to force retries. This is a prepared draft, not automatic failover.

## Private simulation workspace

Channel: https://discord.com/channels/626378673523785731/1570054214850183289
Only administrators and the existing Bartender bot were admitted. The channel is
inside the existing test category, retaining its own private permission overrides.
`fly.toml` selects `docs/rss_simulation.json`, which enables scheduled output only
in this private destination. No MonitoRSS connection is disabled.

`/rss_simulate` is administrator-only and must be invoked in the configured private
channel. It posts a read-only real-news snapshot (including the initial baseline),
then fictional digest/reminder examples and a six-check report. Fixtures use a
disposable database, do not seed real offer metadata, and do not consume the
scheduled queue. Repeated manual runs are limited to once per minute. Scheduled
simulation remains 19:00 digest / qualifying 12:30 reminder; there is no automatic
production promotion after tests pass.

Acceptance before replacement: inspect actual rendering; verify source fetching,
keyword outcomes, deduplication, deadline classification, scheduled runs and restart
behavior. Steam/Epic automated offer collectors and a real destination decision
remain open. Passing synthetic checks alone is not full migration acceptance.

## Tester personal sandbox

The private `rss-模擬區` now permits the 🧪 Tester role to view history,
comment, react and use non-administrative commands. Everyone remains denied
View Channel. Existing management commands remain administrator-only.

An administrator posts `/rss_personal_panel` in that room once. Its persistent
buttons survive restart. Members with access can open private preferences and
personal previews; interactions reject other guilds/channels and production mode.
Preferences are stored by user ID in `/data/rss_sandbox_preferences.sqlite3`.
This does not assign roles, change channel subscriptions, send DMs or notifications,
or consume the scheduled digest queue. The settings view expires after ten minutes;
reopen it from the persistent panel. Each selected field saves immediately.

Options: PS/Xbox/PC, any store/Steam/Epic, news/permanent claim/member/trial,
and up to ten literal include-any/exclude-any keywords per field. Exclusion wins.
All-store selection overrides individual store selections. Personal filtering
happens before the eight-item cap and preserves administrator filtering and exact
deduplication. Mixed 4Gamers content is not automatically considered PC: explicit
platform text is required. This deliberately conservative classifier can omit
relevant articles. A claim is only classified as an offer when verified metadata
exists; Steam/Epic acquisition is still pending. Empty results are stated honestly.

The settings panel provides a clearly labeled fictional fixture mode for testing
Steam/Epic and keep/member/trial combinations independently of available feeds.
Acceptance: two testers save different preferences, reopen after restart, confirm
private independent results, check PC+Epic+keep yields only the fictional Epic
claim, verify exclusion takes precedence, and confirm live preview leaves delivery
state unchanged. No automatic production promotion.
