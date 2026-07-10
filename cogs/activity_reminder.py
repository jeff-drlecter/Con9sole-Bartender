# cogs/activity_reminder.py
# Activity Reminder Cog
# - Remind at T-5 mins and at start time (minute precision)
# - Activities can have multiple schedules (same activity, different time slots)
# - Helper can add/remove activities/schedules and set ping role/channel
# - Persistent storage in JSON (no DB)

import asyncio
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

import discord
from discord.ext import commands, tasks
from discord import app_commands

import config
from core.json_storage import atomic_write_json, load_json_object

log = logging.getLogger("con9sole-bartender.activity-reminder")

# --------- Settings ---------
TARGET_GUILD = discord.Object(id=config.GUILD_ID)

# IMPORTANT: set your helper role id here (same as cogs/role.py)
HELPER_ROLE_ID = 1279071042249162856

# Remind minutes before
REMIND_BEFORE_MINUTES = 5

# Your server timezone (UTC+8)
# If you prefer "Asia/Hong_Kong", also works; both are UTC+8
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Hong_Kong")
except Exception:
    TZ = None  # fallback to naive local time


# --------- Permission helpers ---------
def user_is_helper(member: discord.Member) -> bool:
    return any(r.id == HELPER_ROLE_ID for r in member.roles)


def user_is_admin_or_helper(inter: discord.Interaction) -> bool:
    if inter.guild is None or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    return m.guild_permissions.administrator or user_is_helper(m)


# --------- Data model ---------
@dataclass
class Schedule:
    # weekdays: 0=Mon ... 6=Sun
    weekdays: List[int]
    time_hhmm: str  # "HH:MM"

@dataclass
class Activity:
    id: str
    name: str
    channel_id: int
    ping_role_id: int
    schedules: List[Schedule]


# --------- Parsing helpers ---------
_WEEKDAY_MAP = {
    "mon": 0, "monday": 0, "一": 0, "週一": 0, "星期一": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "二": 1, "週二": 1, "星期二": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "三": 2, "週三": 2, "星期三": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "四": 3, "週四": 3, "星期四": 3,
    "fri": 4, "friday": 4, "五": 4, "週五": 4, "星期五": 4,
    "sat": 5, "saturday": 5, "六": 5, "週六": 5, "星期六": 5,
    "sun": 6, "sunday": 6, "日": 6, "週日": 6, "星期日": 6,
}

def _parse_time_hhmm(s: str) -> str:
    s = (s or "").strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", s)
    if not m:
        raise ValueError("時間格式要係 HH:MM（24小時制），例如 23:00")
    hh = int(m.group(1))
    mm = int(m.group(2))
    return f"{hh:02d}:{mm:02d}"

def _parse_weekdays(s: str) -> List[int]:
    """
    Accept:
      - "1,5,6" (Mon=1 ... Sun=7)
      - "mon,fri,sat"
      - "週五,週六"
      - "1-5" (range)
      - "mon-fri" (range)
    """
    raw = (s or "").strip().lower()
    if not raw:
        raise ValueError("請提供星期，例如 1,5,6 或 mon,fri,sat 或 週五,週六")

    # Normalize separators
    raw = raw.replace("，", ",").replace("、", ",").replace(" ", "")
    parts = raw.split(",")

    out: List[int] = []

    def add_day_token(tok: str):
        tok = tok.strip().lower()
        if not tok:
            return
        # numeric 1..7
        if tok.isdigit():
            n = int(tok)
            if n < 1 or n > 7:
                raise ValueError("星期數字只接受 1-7（1=週一 ... 7=週日）")
            out.append(n - 1)
            return
        if tok in _WEEKDAY_MAP:
            out.append(_WEEKDAY_MAP[tok])
            return
        raise ValueError(f"無法識別星期：{tok}")

    for p in parts:
        if not p:
            continue
        # range handling: "1-5" or "mon-fri" or "週五-週六"
        if "-" in p:
            a, b = p.split("-", 1)
            a = a.strip().lower()
            b = b.strip().lower()

            def tok_to_idx(t: str) -> int:
                if t.isdigit():
                    n = int(t)
                    if n < 1 or n > 7:
                        raise ValueError("星期數字只接受 1-7（1=週一 ... 7=週日）")
                    return n - 1
                if t in _WEEKDAY_MAP:
                    return _WEEKDAY_MAP[t]
                raise ValueError(f"無法識別星期：{t}")

            ia = tok_to_idx(a)
            ib = tok_to_idx(b)

            if ia <= ib:
                out.extend(list(range(ia, ib + 1)))
            else:
                # wrap-around range, e.g. fri-mon
                out.extend(list(range(ia, 7)))
                out.extend(list(range(0, ib + 1)))
        else:
            add_day_token(p)

    # unique + sort
    out = sorted(set(out))
    return out


def _now() -> datetime:
    if TZ:
        return datetime.now(TZ)
    return datetime.now()


def _today() -> date:
    return _now().date()


def _dt_for_date_and_hhmm(d: date, hhmm: str) -> datetime:
    hh, mm = map(int, hhmm.split(":"))
    if TZ:
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
    return datetime(d.year, d.month, d.day, hh, mm)


def _minute_floor(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


# --------- Cog ---------
class ActivityReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Store reminders on the Fly.io volume by default so deploys/restarts do not erase them.
        # Local development can override this with ACTIVITY_REMINDER_PATH.
        self.data_file = os.getenv(
            "ACTIVITY_REMINDER_PATH",
            "/data/activity_reminders.json",
        )
        self.data_dir = os.path.dirname(self.data_file) or "."

        self.activities: Dict[str, Activity] = {}
        # sent_cache key: f"{activity_id}|{schedule_idx}|{yyyy-mm-dd}|{kind}"
        # kind: "pre" or "start"
        self.sent_cache: Dict[str, str] = {}

        self._load()
        self._tick.start()

    def cog_unload(self):
        self._tick.cancel()

    # ---------- Storage ----------
    def _ensure_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)

    def _load(self):
        self._ensure_dir()
        if not os.path.exists(self.data_file):
            self._save()
            return

        raw = load_json_object(
            self.data_file,
            lambda: {"activities": [], "sent_cache": {}},
        )

        self.activities = {}
        for a in raw.get("activities", []):
            try:
                schedules = [Schedule(**s) for s in a.get("schedules", [])]
                act = Activity(
                    id=a["id"],
                    name=a["name"],
                    channel_id=int(a["channel_id"]),
                    ping_role_id=int(a["ping_role_id"]),
                    schedules=schedules,
                )
                self.activities[act.id] = act
            except Exception:
                continue

        self.sent_cache = raw.get("sent_cache", {}) or {}

        # prune cache older than 3 days to keep file small
        self._prune_cache(days=3)
        self._save()

    def _save(self):
        self._ensure_dir()
        raw = {
            "activities": [
                {
                    "id": a.id,
                    "name": a.name,
                    "channel_id": a.channel_id,
                    "ping_role_id": a.ping_role_id,
                    "schedules": [asdict(s) for s in a.schedules],
                }
                for a in self.activities.values()
            ],
            "sent_cache": self.sent_cache,
        }
        atomic_write_json(self.data_file, raw)

    def _prune_cache(self, days: int = 3):
        # keep only recent days
        cutoff = _today() - timedelta(days=days)
        keep: Dict[str, str] = {}
        for k, v in self.sent_cache.items():
            # key: activity|idx|yyyy-mm-dd|kind
            parts = k.split("|")
            if len(parts) != 4:
                continue
            try:
                d = date.fromisoformat(parts[2])
            except Exception:
                continue
            if d >= cutoff:
                keep[k] = v
        self.sent_cache = keep

    # ---------- ID ----------
    def _new_activity_id(self) -> str:
        # short deterministic-ish id
        ts = int(_now().timestamp())
        base = f"a{ts}"
        if base not in self.activities:
            return base
        i = 2
        while f"{base}_{i}" in self.activities:
            i += 1
        return f"{base}_{i}"

    # ---------- Reminder loop ----------
    @tasks.loop(seconds=60)
    async def _tick(self):
        # wait until bot ready
        if not self.bot.is_ready():
            return

        now = _minute_floor(_now())
        # trigger time points
        t_start = now
        t_pre = now + timedelta(minutes=REMIND_BEFORE_MINUTES)

        # prune daily
        if now.minute == 0 and now.hour == 0:
            self._prune_cache(days=3)
            self._save()

        for act in list(self.activities.values()):
            guild = self.bot.get_guild(int(config.GUILD_ID))
            if guild is None:
                continue

            channel = guild.get_channel(act.channel_id)
            if not isinstance(channel, discord.abc.Messageable):
                continue

            role = guild.get_role(act.ping_role_id)
            if role is None:
                continue

            for idx, sch in enumerate(act.schedules):
                # check if today matches for "start" or "pre"
                # For "start", compare to now date/time
                if self._matches_datetime(sch, t_start):
                    await self._send_if_needed(guild, channel, role, act, idx, t_start, kind="start")

                # For "pre", compare to (now + 5) date/time, but message is sent at now
                if self._matches_datetime(sch, t_pre):
                    await self._send_if_needed(guild, channel, role, act, idx, t_pre, kind="pre")

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()
        # align loop closer to minute boundary
        await asyncio.sleep(1)

    def _matches_datetime(self, sch: Schedule, dt: datetime) -> bool:
        # weekday: dt.weekday() 0..6
        if dt.weekday() not in sch.weekdays:
            return False
        return dt.strftime("%H:%M") == sch.time_hhmm

    async def _send_if_needed(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        role: discord.Role,
        act: Activity,
        schedule_idx: int,
        event_dt: datetime,
        kind: str,  # "pre" or "start"
    ):
        k = f"{act.id}|{schedule_idx}|{event_dt.date().isoformat()}|{kind}"
        if k in self.sent_cache:
            return

        # Build message
        when = event_dt.strftime("%H:%M")
        weekday_txt = ["一", "二", "三", "四", "五", "六", "日"][event_dt.weekday()]

        if kind == "pre":
            content = (
                f"{role.mention}\n"
                f"提醒：**{act.name}** 將於 **{when}（週{weekday_txt}）** 開始，仲有 **{REMIND_BEFORE_MINUTES} 分鐘**。"
            )
        else:
            content = (
                f"{role.mention}\n"
                f"開始：**{act.name}** 已經喺 **{when}（週{weekday_txt}）** 開始。"
            )

        try:
            await channel.send(content)
            self.sent_cache[k] = _now().isoformat()
            self._save()
        except Exception:
            # do not spam save; just ignore send failure
            return

    # ---------- Autocomplete ----------
    async def activity_autocomplete(self, inter: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        q = (current or "").lower()
        items = []
        for a in self.activities.values():
            if q and q not in a.name.lower():
                continue
            items.append(app_commands.Choice(name=a.name, value=a.id))
        return items[:25]

    # ---------- Commands ----------
    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_add", description="新增活動（可包含首個時段）")
    @app_commands.describe(
        name="活動名稱",
        channel="提醒發送頻道",
        ping_role="要 tag 嘅角色",
        weekdays="星期：1-7（1=週一..7=週日），或 mon,fri，或 週五,週六，亦可 1-5",
        time_hhmm="時間（24小時制 HH:MM，例如 23:00）",
    )
    async def activity_add(
        self,
        inter: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        ping_role: discord.Role,
        weekdays: str,
        time_hhmm: str,
    ):
        try:
            wd = _parse_weekdays(weekdays)
            hhmm = _parse_time_hhmm(time_hhmm)
        except ValueError as e:
            await inter.response.send_message(f"❌ {e}", ephemeral=True)
            return

        act_id = self._new_activity_id()
        act = Activity(
            id=act_id,
            name=name.strip(),
            channel_id=channel.id,
            ping_role_id=ping_role.id,
            schedules=[Schedule(weekdays=wd, time_hhmm=hhmm)],
        )
        self.activities[act.id] = act
        self._save()

        await inter.response.send_message(
            f"✅ 已新增活動：**{act.name}**\n"
            f"頻道：{channel.mention}\n"
            f"Tag：{ping_role.mention}\n"
            f"時段：{self._format_schedule(act.schedules[0])}\n"
            f"（將會喺開始前 {REMIND_BEFORE_MINUTES} 分鐘同準時提醒）",
            ephemeral=True,
        )

    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_add_time", description="為現有活動新增一個時段")
    @app_commands.describe(
        activity_id="活動（可用自動完成）",
        weekdays="星期：1-7 / mon,fri / 週五,週六 / 1-5",
        time_hhmm="時間（HH:MM）",
    )
    @app_commands.autocomplete(activity_id=activity_autocomplete)
    async def activity_add_time(
        self,
        inter: discord.Interaction,
        activity_id: str,
        weekdays: str,
        time_hhmm: str,
    ):
        act = self.activities.get(activity_id)
        if act is None:
            await inter.response.send_message("❌ 找唔到活動。", ephemeral=True)
            return

        try:
            wd = _parse_weekdays(weekdays)
            hhmm = _parse_time_hhmm(time_hhmm)
        except ValueError as e:
            await inter.response.send_message(f"❌ {e}", ephemeral=True)
            return

        new_s = Schedule(weekdays=wd, time_hhmm=hhmm)
        act.schedules.append(new_s)
        self._save()

        await inter.response.send_message(
            f"✅ 已為 **{act.name}** 新增時段：{self._format_schedule(new_s)}",
            ephemeral=True,
        )

    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_set", description="修改活動的頻道或 tag 角色")
    @app_commands.describe(
        activity_id="活動（可用自動完成）",
        channel="新頻道（可留空）",
        ping_role="新 tag 角色（可留空）",
        name="新名稱（可留空）",
    )
    @app_commands.autocomplete(activity_id=activity_autocomplete)
    async def activity_set(
        self,
        inter: discord.Interaction,
        activity_id: str,
        channel: Optional[discord.TextChannel] = None,
        ping_role: Optional[discord.Role] = None,
        name: Optional[str] = None,
    ):
        act = self.activities.get(activity_id)
        if act is None:
            await inter.response.send_message("❌ 找唔到活動。", ephemeral=True)
            return

        if channel is None and ping_role is None and (name is None or not name.strip()):
            await inter.response.send_message("ℹ️ 無任何更改。", ephemeral=True)
            return

        if channel is not None:
            act.channel_id = channel.id
        if ping_role is not None:
            act.ping_role_id = ping_role.id
        if name is not None and name.strip():
            act.name = name.strip()

        self._save()

        await inter.response.send_message(
            f"✅ 已更新活動：**{act.name}**\n"
            f"頻道：<#{act.channel_id}>\n"
            f"Tag：<@&{act.ping_role_id}>",
            ephemeral=True,
        )

    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_remove_time", description="刪除活動某個時段（用 index）")
    @app_commands.describe(
        activity_id="活動（可用自動完成）",
        index="要刪嘅時段序號（由 1 開始）",
    )
    @app_commands.autocomplete(activity_id=activity_autocomplete)
    async def activity_remove_time(
        self,
        inter: discord.Interaction,
        activity_id: str,
        index: int,
    ):
        act = self.activities.get(activity_id)
        if act is None:
            await inter.response.send_message("❌ 找唔到活動。", ephemeral=True)
            return

        if index < 1 or index > len(act.schedules):
            await inter.response.send_message("❌ index 超出範圍。", ephemeral=True)
            return

        removed = act.schedules.pop(index - 1)
        self._save()

        await inter.response.send_message(
            f"✅ 已刪除 **{act.name}** 時段 #{index}：{self._format_schedule(removed)}",
            ephemeral=True,
        )

    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_delete", description="刪除整個活動")
    @app_commands.describe(activity_id="活動（可用自動完成）")
    @app_commands.autocomplete(activity_id=activity_autocomplete)
    async def activity_delete(self, inter: discord.Interaction, activity_id: str):
        act = self.activities.get(activity_id)
        if act is None:
            await inter.response.send_message("❌ 找唔到活動。", ephemeral=True)
            return

        del self.activities[activity_id]
        # cleanup sent_cache related keys
        self.sent_cache = {k: v for k, v in self.sent_cache.items() if not k.startswith(f"{activity_id}|")}
        self._save()

        await inter.response.send_message(f"✅ 已刪除活動：**{act.name}**", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.check(lambda i: user_is_admin_or_helper(i))
    @app_commands.command(name="activity_list", description="列出所有活動及時段")
    async def activity_list(self, inter: discord.Interaction):
        if not self.activities:
            await inter.response.send_message("ℹ️ 暫時未有任何活動。", ephemeral=True)
            return

        lines: List[str] = []
        for a in self.activities.values():
            lines.append(f"**{a.name}**  （ID: `{a.id}`）")
            lines.append(f"- 頻道：<#{a.channel_id}>")
            lines.append(f"- Tag：<@&{a.ping_role_id}>")
            for i, s in enumerate(a.schedules, start=1):
                lines.append(f"- 時段 #{i}：{self._format_schedule(s)}")
            lines.append("")

        text = "\n".join(lines).strip()
        # split if too long
        if len(text) > 3800:
            chunks = []
            buf = ""
            for line in lines:
                if len(buf) + len(line) + 1 > 3800:
                    chunks.append(buf)
                    buf = ""
                buf += line + "\n"
            if buf.strip():
                chunks.append(buf)

            await inter.response.send_message("📌 活動列表（分段顯示）：", ephemeral=True)
            for c in chunks:
                await inter.followup.send(c, ephemeral=True)
            return

        await inter.response.send_message(text, ephemeral=True)

    # ---------- Formatting ----------
    def _format_schedule(self, s: Schedule) -> str:
        # 0..6 -> 一..日
        zh = ["一", "二", "三", "四", "五", "六", "日"]
        days = ",".join([f"週{zh[d]}" for d in s.weekdays])
        return f"{days} {s.time_hhmm}"


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityReminder(bot), guild=TARGET_GUILD)
