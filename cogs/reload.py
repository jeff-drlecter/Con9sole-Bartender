from __future__ import annotations

from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

COGS_DIR = Path(__file__).resolve().parent

HELPER_ROLE_IDS = set(getattr(config, "HELPER_ROLE_IDS", []))
HELPER_ROLE_NAMES = set(getattr(config, "HELPER_ROLE_NAMES", ["Helper", "helper", "helpers"]))


def can_use_reload(member: discord.Member | discord.User) -> bool:
    """Allow server managers/admins/helpers to use reload."""
    if not isinstance(member, discord.Member):
        return False

    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True

    for role in member.roles:
        if role.id in HELPER_ROLE_IDS:
            return True
        if role.name in HELPER_ROLE_NAMES:
            return True

    return False


def _list_cogs_package() -> list[str]:
    """Return reloadable cog module names under cogs/.

    Example output: ["menu", "drink", "cheers", "reload"]
    """
    names: list[str] = []

    for path in sorted(COGS_DIR.glob("*.py")):
        name = path.stem
        if name.startswith("_") or name == "__init__":
            continue
        names.append(name)

    return names


def _normalize_cog_name(cog: str | None) -> str | None:
    if cog is None:
        return None

    value = cog.strip()
    if not value:
        return None

    if value.lower() in {"all", "*", "全部", "所有"}:
        return None

    if value.startswith("cogs."):
        value = value.removeprefix("cogs.")

    if value.endswith(".py"):
        value = value[:-3]

    return value


class Reload(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _reload_one(self, ext: str) -> tuple[bool, str]:
        """Reload one extension.

        Returns:
            (True, "") when success
            (False, "error text") when failed

        This method is intentionally public-ish because menu.py Admin Tool calls it.
        """
        try:
            if ext not in self.bot.extensions:
                await self.bot.load_extension(ext)
            else:
                await self.bot.reload_extension(ext)
            return True, ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    async def _reload_many(self, cog: str | None = None) -> tuple[list[str], list[str]]:
        target = _normalize_cog_name(cog)

        if target is None:
            names = _list_cogs_package()
        else:
            names = [target]

        ok_list: list[str] = []
        fail_list: list[str] = []

        for name in names:
            ext = f"cogs.{name}"
            ok, fail = await self._reload_one(ext)
            if ok:
                ok_list.append(name)
            else:
                fail_list.append(f"{name} -> {fail}")

        return ok_list, fail_list

    def _format_result(self, ok_list: list[str], fail_list: list[str]) -> str:
        parts: list[str] = []

        if ok_list:
            parts.append("✅ 已重載： " + ", ".join(ok_list))

        if fail_list:
            parts.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

        return "\n".join(parts) if parts else "⚠️ 無可重載的 cogs。"

    @app_commands.command(name="reload", description="重載所有 / 指定的 cogs（Admin/Helper）")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(cog="可選：指定 cog 名稱，例如 menu / drink / cheers；留空＝全部")
    async def reload_cmd(self, inter: discord.Interaction, cog: Optional[str] = None):
        if not can_use_reload(inter.user):
            await inter.response.send_message(
                "❌ 你需要 `Manage Server` 權限或 helpers role 先可以使用 `/reload`。",
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True, thinking=True)

        ok_list, fail_list = await self._reload_many(cog)
        await inter.followup.send(self._format_result(ok_list, fail_list), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reload(bot))
