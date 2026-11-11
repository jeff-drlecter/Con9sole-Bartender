# Helper activity and automatic help detection sandbox

Enabled by `HELPER_SANDBOX=1` in the existing private `helper-模擬區`.
Helpers and 🧪 Tester retain view/history access; ordinary members cannot enter.
No game-category access is changed. The former request-creation demonstration is
replaced with automatic detection: members simply speak in their game channels.
No real pings, source-channel replies or direct messages are sent by the bot.

## Automatic intake

Game categories are discovered from their configured `開一個小隊 call` hub;
archive/hidden categories are excluded. Eligible sources are ordinary text channels
whose names contain 吹水/討論/求助/組隊, plus public threads in those channels or
game forums. Private threads and bot messages are excluded. Forum starter titles
are considered only for the starter message, so every reply does not become a
new candidate just because a thread has a help-related title.

An explainable Cantonese/Chinese/English rule set marks explicit requests for help,
questions about methods/causes, and operation/connection failures. A bare question
mark or ordinary invitation to play is insufficient. Code blocks, quoted lines,
URLs, offers to help and explicit resolution phrases are excluded. These are
**suspected requests**, not an assertion that someone needs intervention. Sarcasm,
ambiguous wording and context can produce false positives/negatives; Helpers can
mark `不是求助`. No external AI service or text transmission is used.

Startup performs a bounded initial scan: up to 60 eligible cached text channels /
active public threads, latest 30 messages per channel within the last six hours.
It is not complete historical coverage and does not enumerate archived threads.
Thereafter new messages and edits are evaluated. Source deletes/bulk deletes or
edits removing the help signal withdraw the candidate. A later qualifying edit
can reopen a withdrawn candidate, but never a handled/dismissed one. Direct replies
from other humans, and replies to a forum starter, mark `有人回覆`; they do not
mark the issue resolved. No guarantee of no replies is inferred from missing data.

## Helper controls and privacy

`待接應（自動偵測）` opens a private list with original-message excerpts/links,
reason, reply-observation and owner/status. Original source View Channel AND Read
Message History permissions are checked before fetching/displaying any content,
and again before an action. Fetches are bounded to 20 attempts / eight visible
entries per opening. Source deletion, lost permissions or unavailable API means
no content/action is exposed. Every actionable message is fetched again to check
its current contents. The shared board only explains the workflow; it never
copies real private-channel excerpts or candidate counts to all Testers.

Atomic state transitions support `我跟進`, `已處理`, `轉交`, `不是求助`. Only the
owner or administrator may resolve/handoff an owned item. Stale controls cannot
reopen completed work. `處理記錄` shows handled/dismissed entries subject to the
same source permissions. SQLite stores message/channel/author IDs, timestamps,
rule reasons and workflow metadata, never message bodies. Candidates are limited
to 1,000 records and seven days, with periodic cleanup. Prior demo tables are
preserved but no longer used for automatic intake.

`即時活動` privately shows actual human text counts in a bounded 30-minute memory
window (10,000 events), plus current voice occupancy, filtered by current source
permissions. Voice requires View Channel AND Connect; bots and hubs are omitted.
No voice audio is accessed. Existing calls have unknown start times unless their
first human join was observed. Duty toggling is a saved demo preference only;
notifications are not enabled.

## Verification

Tests cover Cantonese/English examples, exclusions, public forum title handling,
private-thread exclusion, source permission filtering, edit/delete withdrawal,
reply observation, dedup, claim races, owner controls, retention and no text-body
storage. Deployment checks the actual private room access/history permissions,
five controls, automatic-detection panel, detector version and initial scan status.

## Unified mobile Overview

`開啟 Overview` combines four sections into one private, per-viewer embed:
needs-help first, recent chat, occupied voice rooms, and attention opportunities.
Each section shows at most three short rows. `刷新` edits the same ephemeral card;
`跟進求助` and `處理記錄` use the existing source-permission checks and workflow.
Empty lists and request controls provide `返回 Overview`. The public entry message
is deliberately short; real activity/source text is never copied into it.

Attention opportunities retain references only in a 200-item in-memory window:
observed messages by members who joined within seven days, and explicit LFG/chat
invitations without an observed direct human reply. New-member messages are
shown once per author within the observation window, never described as their
first-ever message. Opportunities expire after 30 minutes; direct human replies
remove LFG entries and source deletions remove referenced opportunities. Source
view/history permissions are checked before links are shown. This coverage is
bounded observation and does not establish that nobody responded elsewhere.

The `睇示例` button opens a clearly fictional four-section card, never inserts
fake requests/activity into the live queue, and allows returning to the real
Overview. This supports mobile layout testing even when the server is quiet.
