# Staff tool permissions

Discord role permissions and delegated Bot actions are separate. Helpers must not gain server configuration authority through the Bot's own permissions.

| Operation | Admin / Manage Server | Moderator | Helper |
|---|---|---|---|
| Stats, Ping, system health | Yes | Yes | Yes |
| Single safe role changes | Existing role authorization | Only if also Helper | Existing hierarchy and privileged-role protection |
| Temporary voice cleanup | Yes | Yes | No |
| Reload, game setup, announcement publishing | Yes | No | No |
| Activity reminder configuration, squad routing setup | Yes | No | No |
| Notification resolution / retry | Yes | No | No |
| Bulk role changes, level/title administration | Yes | No | No |

Admin means Administrator or Manage Server. Moderator requires both Timeout Members and Manage Messages; a role name alone does not authorize moderation. Existing Manage Channels authority also permits temporary voice cleanup.

The menu hides unauthorized tools on new panels. Dispatch and action handlers recheck permissions so old persistent buttons cannot bypass the policy. Direct slash commands use the same server-admin boundary for configuration. Notification resolution checks the current guild member again before committing.

Helpers retain existing role hierarchy checks and cannot delegate roles with moderation or management powers. Level and title roles remain protected by their dedicated systems. This change does not assign staff roles or modify Discord channel overwrites.

Validation: offline authorization regressions cover denied direct actions, old-button dispatch, Helpers versus moderator powers, current-member revocation, admin access, and safe-role batch rejection. Live delivery and role hierarchy remain separate operational checks.
