# Con9sole Bartender Operations

## Production

- GitHub repository: `jeff-drlecter/Con9sole-Bartender`
- Default branch: `main`
- Fly.io application: `con9sole-bartender`
- Fly.io region: `sin`
- Persistent volume mount: `/data`

Never place Discord, Twitch, GitHub, or Fly.io tokens in repository files or logs.

## Normal release flow

1. Create a branch and draft pull request.
2. Confirm Python compilation and unit tests pass.
3. Merge only after all GitHub checks succeed.
4. The `Fly Deploy` workflow deploys `main` automatically.
5. Confirm the workflow's `Verify Fly.io machine status` step succeeds.
6. Run `/ping` and one read-only command such as `/menu` in Discord.

## Routine checks

```bash
gh pr checks <PR_NUMBER> --repo jeff-drlecter/Con9sole-Bartender
gh run list --repo jeff-drlecter/Con9sole-Bartender --limit 10
flyctl status --app con9sole-bartender
flyctl releases --app con9sole-bartender
flyctl logs --app con9sole-bartender --no-tail
```

A healthy deployment has a completed GitHub workflow, a completed Fly release, and a `started` machine in `sin`. Machine state alone does not prove the Discord connection is healthy, so confirm `/ping` after functional changes.

The **Discord deployment gap** in the Fly Deploy job summary measures from Fly signalling the old process to shut down until the replacement's first Discord ready event with the persistent welcome verification button registered. It uses Fly log timestamps for the target Machine during this rollout and checks the ready event's image commit. This is a readiness estimate; a real button click is a separate check. Build time is excluded. Missing, ambiguous or out-of-order markers and failed deployments are reported as unavailable. The observer only reads the short Fly log buffer; it does not contact members or store log contents.

## Rollback decision

Rollback when a new release repeatedly crashes, cannot log in to Discord, loses a core command, or produces data-write errors. Do not roll back merely for a cosmetic issue that can be fixed forward safely.

Before rollback:

1. Record the failing GitHub commit, Fly release, and image.
2. Capture recent logs without copying secrets or message content.
3. Confirm whether the release changed a persisted schema.
4. Do not roll back a schema change until backward compatibility is confirmed.

To restore a known-good image:

```bash
flyctl deploy --image <LAST_KNOWN_GOOD_IMAGE> --app con9sole-bartender
flyctl status --app con9sole-bartender
flyctl logs --app con9sole-bartender --no-tail
```

Then run `/ping`, `/menu`, and the feature affected by the incident.

## Persistent data

- `/data/drink_state.json`: cooldown and recent-drink state.
- `/data/activity_reminders.json`: activity schedules and sent cache.
- `/data/community_stats.sqlite3`: drink events, menu usage, and daily bar data.
- `/data/game_announcements.json`: newly created games awaiting a manual Update Publisher post.
- `*.corrupt.<timestamp>`: preserved malformed JSON awaiting manual inspection.

Never delete or replace a `/data` file without first making a backup. SQLite is the correct store for event history and statistics at the current single-machine scale; a network database is unnecessary unless multiple writers or substantially higher traffic are introduced.

## Update Publisher

Set `ANNOUNCEMENT_CHANNEL_ID` in `config.py` to the target text or announcement channel before release. A zero or invalid value leaves publishing disabled. New games are only added to the pending list; they are never posted automatically.

Update Publisher posts the update and any optional thread reply as ordinary messages in this server. Both use Discord's silent delivery with mentions disabled. Members can read them in the channel without a push or desktop notification. The bot does not crosspost to servers following the channel.

After deployment, open `/menu` → Admin Tool → Update Publisher as an Admin or Helper. Create a feature or game draft, confirm the private preview, then test Publish and Cancel with a non-production draft if appropriate.

## Dependency updates

Dependabot opens weekly pull requests for Python and GitHub Actions dependencies. These pull requests must pass the normal checks and must not be auto-merged. Review release notes for Discord, Twitch, database, and deployment behavior changes before merging.
