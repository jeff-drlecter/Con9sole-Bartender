# Helper 社群動態 Dashboard

Channel: `1570639281225994301` (`📊｜社群動態`) under 管理團隊.

The shared board updates in place every two minutes with aggregate human text activity observed in the last 30 minutes since Bot startup, plus current occupied voice rooms. It uses the existing eligible community game/public-chat sources, omits private/staff/test areas, and shows category names and counts only. It does not provide raw source messages, usernames or audio. Existing compact pulse logs move to this channel; no new ping or DM is introduced. No separate launch announcement is sent.

`我的總覽` opens the existing private Overview with current source view/history checks (voice additionally requires connect). Help handling retains ownership and permission checks. Helpers and the existing Tester audience have view/history access, matching the source demo channel's overwrites; @everyone remains denied. The channel move preserves its explicit overwrites rather than synchronizing management-category permissions.

The former renamed demo broke initialization because runtime still checked its old name and topic. Runtime now binds to the exact guild and pinned dashboard channel ID and validates access; it never creates or renames a channel. Dashboard settings use independent `dashboard_channel`/`dashboard_panel` keys. Old demo channel/panel IDs and history remain, without reusing an old message ID in the new destination. Pending help and saved preferences are preserved. An uncertain initial panel send is not automatically retried.

Local validation covers renamed channel/topic startup, wrong guild/saved channel, public exposure and missing Helper history denial, old panel preservation, aggregate source exclusion and absence of member names. Production verification reads the pinned channel, Helper/Tester view/history overwrites and the persisted new panel/controls. A real Helper account is still needed for interactive role acceptance.
