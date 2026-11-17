# Temp-VC ordering with unsupported Discord channel types

## Problem and bounded fix

With locked `discord.py==2.7.1`, `Guild.fetch_channels()` constructs every channel
in the guild response before callers can filter by category. A synthetic channel
with `type=20` causes `InvalidData`, even in an unrelated category. The cosmetic
ordering wrapper catches that exception, so room creation can continue but the
numeric reorder never reaches Discord.

`_order_temp_channels` now calls the same Bot HTTP client's
`get_all_guild_channels` endpoint and constructs `discord.VoiceChannel` objects
only for the exact `ChannelType.voice` value (`2`) in the requested category.
Both filters run before SDK construction, so unrelated voice payload fields are
never decoded. The category comparison uses REST string snowflakes, or a null
or absent `parent_id` for uncategorized rooms. This retains authenticated,
rate-limited REST reads and a fresh full response; it never substitutes the
potentially incomplete Gateway cache. Selected voice fields are decoded by the SDK.

The existing sorting algorithm and bulk update remain unchanged: tracked rooms
are sorted numerically immediately before their hub, unrelated voice rooms keep
their relative order, and existing voice position slots are reused. Unknown
types, stage/text/category/forum/media channels and other categories never enter
the update payload. No channel permission overwrites, parents or names are sent;
unknown rows are neither modified nor deleted. The existing permissions needed
for channel positioning remain required. REST or positioning HTTP failures still
log and return through the cosmetic wrapper without failing room setup.

This change touches no routes, sessions, attendance, EXP, production settings or
stored schemas. It does not establish any missing attendance or collector loss.

## Offline verification

Synthetic payload tests exercise the real SDK channel conversion, without a Bot
login or network request. They first reproduce `Guild.fetch_channels` rejecting
type `20`, then verify the fixed sorter emits exactly one expected bulk payload
for the same response. Coverage includes unknown channels in the target and
another category, sparse positions, unchanged source rows, exact voice-type
selection, other-category exclusion, uncategorized channels, incomplete cache,
permission failures, numeric naming and no-op behavior. A regression with
out-of-scope type-2 rows lacking SDK-required fields verifies pre-construction
category filtering for string and null parents, including an uncategorized target.

The room-creation regression also supplies a synthetic raw response containing
an unsupported channel, checks the successful numeric reorder, and retains the
creator ownership, returned-room, cleanup scheduling and no-deletion assertions.

```sh
/private/tmp/con9sole-validation-venv/bin/python -m unittest discover -s tests -p '*tempvc*.py' -v
```

Result: **41 tests passed**, including all temp-VC tests and quick-bar temp-VC
flows. `git diff --check` passed.

Local validation uses the isolated hash-locked environment with Python **3.14.8**
and `discord.py==2.7.1`. This is not evidence of Python 3.11 CI or live Discord UI
acceptance. Integration checks and the required Python 3.11/security CI remain
the coordinating agent's delivery gate. No deployment or production mutation was
performed; rollback of this code change requires no data migration.
