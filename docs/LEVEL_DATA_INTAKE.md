# Receiving Amari data

The intake tool prepares a **private staging report only**. It cannot import XP, modify the running bot, assign roles, change weekly standings or activate replacement. Its `source: amari-staging` output is deliberately rejected by the frozen-snapshot importer.

## Information to obtain from official support

| Information | Purpose |
| --- | --- |
| Discord server ID | Scope validation against the independently supplied server ID |
| Discord user ID and raw total XP for every exported member | Preserve exact account ownership and within-level progress |
| Raw weekly XP for each member, including explicit zero values | Missing records must not silently become zero |
| Weekly period/reset description | Preserve the source counter without assuming it is a calendar week |
| Export timestamp in UTC, original row count and source reference | Provenance and independent completeness checks |
| Source level, if available | Check against the currently verified XP curve |

Keep original CSV/JSON files unchanged. The tool records SHA-256 hashes. It does not accept display names as identity evidence. Unknown/departed rows can only be excluded by an independently verified ID list; it never guesses the ID behind an Unknown label.

An API key is a credential, not an export file. Configure it through the approved secret mechanism if official API access is granted; never put it in metadata, mappings, source control or a report.

## Private input package

Use the ignored `migration_private/` directory for actual exports, rosters and reports. No real data belongs in repository examples. The following values are synthetic.

`totals.csv`:

```csv
user_id,total_xp,level,weekly_xp
10,55,2,90
11,0,0,0
```

`mapping.json`:

```json
{"columns":{"user_id":"user_id","total_xp":"total_xp","level":"level","weekly_xp":"weekly_xp"}}
```

If official JSON uses different columns, configure them explicitly. For example, for `{"data":[{"id":"10","exp":55,"weekly":90}]}`:

```json
{"rows_key":"data","columns":{"user_id":"id","total_xp":"exp","weekly_xp":"weekly"}}
```

Large Discord IDs should be supplied as decimal strings in JSON, with no spreadsheet rounding. Names, scientific notation, commas inside numeric values, leading zero IDs, float/bool values and duplicate IDs are rejected.

`roster.json`: `["10","11"]`

This is an independently verified **intended XP member set**, not an assumed list of everyone in the server. `--source-count` is the independently reported original export row count **before exclusions**. A departed exclusion list must be explicit IDs present in the export and disjoint from the intended member set. Unexplained missing or extra IDs stop staging.

`metadata.json`:

```json
{
  "guild_id":"1",
  "exported_at":"2026-11-07T05:00:00Z",
  "weekly_period":"Replace with the actual period/reset description supplied by Amari",
  "source_reference":"Replace with the official export receipt/reference"
}
```

## Prepare without importing

```sh
python scripts/prepare_level_data.py \
  --guild 1 \
  --totals migration_private/totals.csv --format csv \
  --mapping migration_private/mapping.json \
  --roster migration_private/roster.json \
  --source-count 2 \
  --metadata migration_private/metadata.json \
  --output migration_private/intake-001
```

If weekly XP arrives separately, omit `weekly_xp` from the totals mapping and provide all three arguments: `--weekly`, `--weekly-format`, `--weekly-mapping`. The weekly mapping needs `user_id` and `weekly_xp`; joins use IDs exclusively. Weekly XP may exceed total XP. A missing weekly value stays `null` and is flagged; it is never invented as zero.

For separate files, metadata also needs `weekly_exported_at` (UTC) and `weekly_source_reference`; `weekly_period` describes the weekly file's counter/reset. Missing provenance or differing capture times are flagged for independent frozen-source verification. The report retains both explicit column mappings/rows keys alongside the input hashes so conversion can be reproduced.

The output directory must be new. It is created with mode700 and `intake.json` with mode600; previous reports and input files are not overwritten. Console output contains aggregate counts only. Input files are limited to20 MiB and100,000 rows.

## After intake

1. Verify source authenticity, original counts, intended member IDs and exclusions against independent evidence.
2. Resolve missing weekly balances, period/reset details, and any source curve mismatch.
3. Reconcile historical game candidates with historical text cooldown evidence and existing preview events. Candidate counts are not compensation approvals; current Booster status is not historical evidence.
4. Establish a common frozen cutover, take a verified backup and construct a fresh canonical snapshot with actual freeze/capture timestamps.
5. Use the existing offline snapshot dry-run, then review each member's source baseline, bridge events, separately reviewed historical compensation and proposed final total. Preserve historical compensation outside the current weekly standings/cooldowns.
6. Complete restore and role recovery acceptance before enabling replacement.

`migration_ready` remains false even when all CSV/JSON fields validate. An intake report does not prove source completeness, a coherent freeze, approved historical compensation or successful recovery. The hard activation gate remains in force.
