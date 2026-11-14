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

The bot posts the panel once in that room after deployment, with a durable reservation
to prevent duplicates on restart. Administrators can recover a failed posting with
`/rss_personal_panel`. Its persistent
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

## Calendar highlights and recent popular games (sandbox)

The persistent panel now includes 是日精選 / 今個月精選 / 最近熱門.
Button results are private and respect member preferences. Shared short snapshots
remain in channel history for future testers. One initial snapshot is posted once
feeds and the chart refresh have finished; subsequent snapshots are posted in the
19:00–19:14 HKT window, at most once per calendar date. These replace the old long
19:00 card in simulation only. The 12:30 verified-offer reminder is unchanged.
Reservations prevent automatic duplicate posts after an ambiguous send failure.

Today uses Hong Kong midnight through now; month uses the first day of the current
Hong Kong month through now. Month selection can include older collected items
without admitting them into the normal daily delivery queue. The UI explicitly
says coverage is only the collected portion of the month. Exact URL/title aliases
are merged, administrator exclusions still apply, and verified expired offers are
removed. Selection favors verified offers, membership updates, updates/co-op and
configured interest keywords; it is an editorial rule, not popularity measurement.
No positive score means no highlight filler. Public cards show at most three rows
per section; private views show at most five. Known dates and deadlines are shown.

Recent popular games use Valve's official Most Played chart service:
https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/
with title/type verification through Steam's appdetails endpoint. Top entries of
type `game` retain their original chart ranks; identified modeling/design/photo
editing/utility genres are omitted even when Steam labels them as games. This is
explicitly Steam/PC coverage, not a PS/Xbox or all-industry ranking. It is not a
free-games list. The rollup date and retrieval time are displayed along with
https://store.steampowered.com/charts/mostplayed . Valve explains the chart views at
https://store.steampowered.com/news/posts/?enddate=1666727642&feed=steam_blog .

Chart refresh is every six hours, responses are bounded to 2 MiB, only the first
ten ranked app records are looked up, and the first five verified games are kept.
The last successful cache survives restart; retrieval older than 24h or source
rollups older than seven days are not presented as current. Source failure never
falls back to newest RSS articles as a fabricated popularity ranking. These
public Steam endpoints are schema-validated but not guaranteed stable.

## Member browsing rollout — 14 November 2026

`RSS_PERSONAL_PUBLIC=1` exposes a private, on-demand member browser via `/news`
and `/menu` → 更多玩法 → 資訊與設定 → 遊戲情報. This flag is independent
of scheduled delivery. The current Fly configuration keeps `simulation:true`
and the private test destination: MonitoRSS remains the production publisher.
No new shared public card, DM, notification or role assignment is created.

The member must be in this guild and in a text channel both they and the Bot
can view. Threads and DMs are rejected. Every panel action checks access again;
preference panels and keyword submissions additionally check their owner.
Public entry replies, results and settings are ephemeral. Existing persistent
sandbox button IDs and `/data/rss_sandbox_preferences.sqlite3` are retained,
including per-user preferences and the Steam chart cache. Browsing does not
claim scheduled batches. Reopening reads current settings.

Shared labels use neutral Traditional Chinese; authored private prompts use
existing HK/TW language roles, defaulting to neutral when unset or conflicting.
Source headlines, excerpts and user keywords are not translated. Steam/Epic
verified offer collection is still absent and described explicitly in the UI.

Rollback the member browser by setting `RSS_PERSONAL_PUBLIC=0` and restarting;
the private sandbox still operates and stored preferences are retained. This
flag never enables production publishing. Deployment checks confirm command
registration and SQLite integrity without sending messages. Automated member
permission models are not a real ordinary-member or iPhone interaction test.
Before production news cutover, finish the original source comparison,
scheduled delivery acceptance and MonitoRSS backup/disable sequence above.

Deploy impact: the existing single-process Bot restarts. Discord voice rooms
remain server-side, but Bot interaction responses and background jobs can pause;
active short-lived preference views must be reopened. Persistent RSS button IDs
and existing SQLite databases are retained. No guarantee of zero interruption.

## Steam/Epic source collectors — 14 November 2026

`STORE_NEWS_CONFIG=docs/store_news.json` enables two regional Epic collectors and
Steam official community-announcement feeds for configured AppIDs. The initial
watched list is CS2 (730), Dota 2 (570), Apex Legends (1172470) and GTA V Legacy
(271590); this is a bounded multi-game selection, not all Steam news. Each game
name/type/AppID is checked against the Steam store before its feed is accepted.

Collection runs every 30 minutes in the existing process, at most 10 watched games
and 20 reviewed Steam offers. Responses are capped at 2 MiB, redirects rejected,
and HTTP 429 honors Retry-After (at least the next 30-minute cycle). There are no
new services, dependencies, credentials or member account links. Persisted snapshots
live in `/data/store_news.sqlite3`, separate from the scheduled delivery queue.
New adapters never feed automatic digests, expiry notifications or shared snapshots.

Initially `STORE_NEWS_PUBLIC=0`: only private button previews in the existing test
room incorporate these results. Other rooms continue the earlier RSS behavior.
After real-source acceptance, `1` permits them in existing private `/news` results;
it does not enable a new notification or public publisher. No automatic promotion.

Epic reads the store's `freeGamesPromotions` endpoint separately with HK/HKD and
TW/TWD. It is store-owned but undocumented; schema changes can break collection.
Only active BASE_GAME / base-edition entries with a currently active zero-price
promotion, positive original price, no voucher requirement and a valid product URL
are classified as permanent claims. Upcoming offers, expired offers, demos, bundles,
DLC and ordinary free-to-play games are excluded. Country-specific source results
are not proof that every individual account is eligible; store/account restrictions
still apply. A successful empty result removes past offers for that region.

A separate member-owned regions selector defaults to both markets and never follows
their language preference. Old preference rows gain this field without losing filters.
Regional duplicates merge after filtering, only within the same store/promotion;
where end times differ, the earliest verified end is shown. Offers older than two
hours since successful collection are hidden; news snapshots older than 24h are
hidden. The original timestamps are retained; active offers can appear outside the
24-hour news window. The UI identifies checked time and current availability.

Steam news alone never proves permanent access. `steam_offers` remains empty until
an operator reviews a matching official Steam announcement and enters an explicit
kind, region and timezone-aware start/end. Schema: appid, kind (keep/trial),
starts_at, ends_at, regions (hk/tw), evidence_url, reviewed:true. Only matching
`https://store.steampowered.com/news/app/APPID/view/GID` evidence is accepted.
Permanent claims additionally require current regional positive original price,
zero final price and 100% discount, on a paid base game. Trial access is an operator
assertion from the announcement, not an inference from normal store price. Nothing
in this implementation promises complete automatic Steam giveaway discovery.

Acceptance: source parser adversarial cases, real HK/TW comparisons, region filtering,
legacy preference migration, expired/stale removal, restart persistence, cross-store
identity separation and read-only queue isolation. `verify_store_sources.py` checks
real persisted source results on Fly without sending any message. Mobile interaction
and ordinary-member live UI checks remain separate. Roll back by unsetting
STORE_NEWS_CONFIG and restarting, retaining the SQLite data; MonitoRSS is unaffected.
