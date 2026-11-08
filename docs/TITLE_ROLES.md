# Collection title roles

Members open My Member Card → Manage Title, or the existing collection milestone
selector. Only unlocked milestone/theme titles are selectable. A private preview and
confirmation precede selection. Hide Title removes the displayed title without
deleting earned awards. A member can have one display role, separate from level/game roles.

Title selection and its role job commit in the same stats-database transaction.
Workers read the latest selected title and mappings, validate current membership and
unlock proof, then remove only explicitly managed obsolete title roles and add the
desired safe role. Failed/partial changes remain queued; revision-based acknowledgement
cannot delete a newer job. Sync is serialized across cog reloads. External changes to
managed member roles trigger reconciliation; missing or unsafe roles fail closed.

Mappings are administrator/Manage Server controlled via Admin Tools → Title Management.
Roles require zero permissions/default colour, no hoist/mentionability, no integration
management and a position below the Bot. Level-managed roles are rejected. Initial
binding to an existing role requires an empty role unless it is already managed here.
Generic Role Tools cannot mutate title roles, including after a reload.

The administrator may preview creating the nine standard count titles or create/bind
individual theme/milestone roles. Role creation has a durable intent: an uncertain
creation cannot automatically create a duplicate; inspect Discord and bind the actual
role or clear the intent after verifying that no role was created. Creating/binding
roles does not enqueue legacy members automatically.

Initial all-member sync requires a complete member cache, safe roles, proven unlocks,
an explicit private CSV preview and confirmation. The preview digest includes current
selections, mapping version and affected role sets; changes require a fresh preview.
The confirmed batch and role snapshots are audited and queued atomically. User-initiated
future title changes sync automatically. No role grants or XP adjustments occur merely
from opening a title or administration page.

Member cards and title management distinguish actual role agreement from pending or
unbound titles. System Status shows the title sync loop, pending users and unsafe role
bindings. Selection without a mapping remains a card-only title. Discord role calls
and SQLite cannot be globally atomic; durable jobs reconcile partial outcomes. An
administrator must fix hierarchy/permission issues; roles are not recreated silently.
