# Stage 2: alert-only anti-scam and spam monitoring

Status: CLOSED for the current alert-only rollout, 10 November 2026. Stage 1 remains closed. Do not repeat completed acceptance unless settings change. Future automatic verification or enforcement is not activated or approved by this closure.

## Current rollout

- Preserve the three unrelated native AutoMod rules.
- Native `Anti-scam | Unverified links`: enabled, alert only to admins channel 1425054477597016084; Verified role 1279040517451022419 is exempt.
- Native `Anti-scam | Suspected spam`: enabled, alert only to the same destination; no explicit Verified exemption.
- PR #100 removed bulk channel-list dependencies from status/draft commands after live logs showed discord.py failing on an unknown type-20 channel. These two commands now reply successfully; existing rule identity and ownership checks remain.
- PR #101 supplements native spam detection: five matching normalized text messages from one human member within 15 seconds produce a staff alert. Per-member cooldown is 120 seconds. Cross-channel events are counted only when visible to the Bot. No role exemption, including Verified or staff. Bots, webhooks and the alert destination are excluded.
- Every supplement alert fetches current destination/roles and checks privacy before sending. It includes member ID, count and a message link, not copied message text. Mentions and embeds are suppressed. Bounded hashes and IDs live only in memory and reset on restart.
- No added rule deletes, blocks, times out or revokes Verified. Ordinary chat, voice and Bot access remain independent of Verified.

## Live acceptance, 10 November 2026 (Hong Kong time)

| Check | Observed result |
| --- | --- |
| Native URL rule on unverified sandbox messages | Existing 12:51 and 13:02 alerts visible; messages remained posted |
| Native spam limitation | Five benign identical sandbox messages at 13:47 produced no observed native spam alert |
| Supplement, ordinary member | At 13:53, five matching messages produced one staff alert; source messages remained |
| Admin destination privacy | Ordinary test account opening the direct admins URL was redirected to the server rules channel; destination preflight also passed |
| Verified identity | `jeff_con9sole` had Verified and ordinary/Tester roles, with no Mod, Helpers or EA FC-M |
| Verified URL exemption | At 14:07, a fresh Discord.com URL posted with an embed; no corresponding new native URL alert was observed in admins |
| Verified spam inclusion | At 14:07, five matching messages produced one supplement alert in admins; source messages remained and Verified was not revoked |
| Cooldown | Unit-tested. A later live batch produced no extra observed alert, but exact timing of that second batch was not recorded sufficiently to certify a full additional five-in-15-second trigger |
| Pre-join role grants | All 27 answers across four pre-join questions were opened read-only and checked. None assigned Verified. They assign platform, game/version, off-topic/no-off-topic or language-preference roles |
| Member self-service view | Current test account's Channels & Roles page displayed no customisation options; this is not proof that all admin-configured questions are absent |

Previous session checks: Carl-bot had no autoroles, sticky-role reassignment disabled, and its sole reaction-role record contained game roles only. Dyno's role automation modules were disabled. Bartender source has no automatic Verified grant workflow; existing arbitrary role grant/revoke tools are administrator operations.

## Manual review and re-verification policy

An alert is evidence for review, not a finding of fraud. A single ordinary link, a game link or repeated benign text must not automatically remove Verified. Initial operation is notification only.

Review in stages: inspect message context; classify benign/uncertain/credible abuse; record evidence and the administrator's decision privately before any separately authorised enforcement. A Verified revocation for anti-scam reasons must be recorded as requiring manual review, including account ID, reason, actor and resolution. Only an administrator may restore it after reviewing that record. Rejoining, answering onboarding or clicking a public role button must not restore it. No automatic verification service may be introduced without consulting this restriction and implementing a persistent per-member hold checked by every automatic grant path.

No production member was revoked or punished to test this policy. The currently absent automatic grant flow is not a tested persistent hold implementation; future automation requires that additional safeguard.

## False positives, native exemptions and limits

- Ordinary unverified game/YouTube/official URLs also match the explicit-URL rule. This is expected monitoring noise, not proof of malicious intent. No broad substring allowlist is added.
- Benign repeats also trigger the supplement; cooldown and manual review limit the consequence to one private alert. Different users are not combined. Distinct messages do not count as matching text.
- Discord documents native Administrator/Manage Server exemptions; the supplement does not use these exemptions. Native spam is a machine-learning classifier and is not a deterministic repeated-message detector.
- Bare domains, obfuscated/zero-width links, QR/image scams, DMs and malicious-domain reputation are not covered by this explicit-URL rule. The supplement does not inspect image content or edit events, and cannot inspect messages the Bot cannot receive.
- Restart/reload loses supplement windows and cooldown. A failed or uncertain alert send is not blindly retried. Native alerts continue independently.
- No claim of complete scam detection or guaranteed alert delivery is made.

Primary reference reviewed 10 November 2026: https://support.discord.com/hc/en-us/articles/4421269296535-AutoMod-FAQ (native exemptions, spam classifier limitations and alert destinations).

## Final onboarding and restoration acceptance

Browser access resumed and all seven post-join answers were opened individually, read-only; each dialog was cancelled without saving. Combined with the 27 pre-join answers, all 34 configured answer grants were checked and none included Verified.

| Post-join answer | Assigned roles |
| --- | --- |
| 顯示新聞區 | news-sub |
| 暫時隱藏 | no-news-sub |
| 直播及觀看直播 | 主播, 觀眾 |
| 只進行直播 | 主播 |
| 只觀看直播 | 觀眾 |
| 暫不參與 | 非直播 |
| 參與測試 | 🧪 Tester |

Current checked grant paths are onboarding (34 answers), Carl-bot autoroles/sticky roles/reaction roles, Dyno role automation modules, and Bartender's role-grant source paths. None provides an automatic Verified re-grant. Bartender's generic role_grant remains an administrator-directed operation, not self-service verification. Manual Discord role assignment by authorised staff remains possible and must follow the review policy above; this is an intentional administrative action, not an automatic restoration.

Current restoration workflow: record an anti-scam revocation and review-required status privately with member ID, evidence, actor and date; keep the member unverified while unresolved; an administrator reviews the evidence and records approval before manually granting Verified; then record the resolution. A single ordinary URL or a monitor alert alone is not grounds for automated revocation. No member was actually revoked as an enforcement drill.

The current no-automatic-verification configuration satisfies the no-automatic-restoration rule for this rollout. A persistent technical hold is NOT implemented or claimed; it is a prerequisite before any future automatic verification feature. Re-audit integrations or role-grant paths if they change.

Stage 2's current alert-only baseline is closed. Known limitations above remain explicit; this closure is not a guarantee of complete scam detection. Stage 3–5 remain separate work.
