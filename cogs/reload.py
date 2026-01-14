# cogs/reload.py
from __future__ import annotations

import pkgutil
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

TARGET_GUILD = discord.Object(id=config.GUILD_ID)

# 你要畀 Helper 用到 /reload，就填 Helper role id；唔想就留 None
HELPER_ROLE_ID: Optional[int] = 1279071042249162856


def _user_can_reload(inter: discord.Interaction) -> bool:
    if inter.guild is None or not isinstance(inter.user, discord.Member):
        return False
    m: discord.Member = inter.user
    if m.guild_permissions.administrator:
        return True
    if HELPER_ROLE_ID is not None and any(r.id == HELPER_ROLE_ID for r in m.roles):
        return True
    return False


def _list_cogs_package() -> List[str]:
    # 掃描 cogs/ 內所有 .py（排除私有/__init__）
    names: List[str] = []
    import cogs  # type: ignore

    for mod in pkgutil.iter_modules(cogs.__path__):  # type: ignore
        if mod.ispkg:
            continue
        if mod.name.startswith("_"):
            continue
        names.append(mod.name)
    return sorted(names)


class Reload(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.check(_user_can_reload)
    @app_commands.command(name="reload", description="重載所有 / 指定的 cogs（Admin/Helper）")
    @app_commands.describe(cog="例如 role、duplicate、role_channel_factory；留空=全重載")
    async def reload(self, inter: discord.Interaction, cog: Optional[str] = None):
        await inter.response.defer(ephemeral=True)

        if cog:
            ext = cog if cog.startswith("cogs.") else f"cogs.{cog}"
            ok, fail = await self._reload_one(ext)
            if ok:
                await inter.followup.send(f"✅ 已重載：`{ext}`", ephemeral=True)
            else:
                await inter.followup.send(f"❌ 失敗：`{ext}`\n{fail}", ephemeral=True)
            return

        # reload all
        ok_list: List[str] = []
        fail_list: List[str] = []

        for name in _list_cogs_package():
            ext = f"cogs.{name}"
            ok, fail = await self._reload_one(ext)
            if ok:
                ok_list.append(name)
            else:
                fail_list.append(f"{name} -> {fail}")

        msg = []
        if ok_list:
            msg.append("✅ 已重載： " + ", ".join(ok_list))
        if fail_list:
            msg.append("❌ 失敗：\n- " + "\n- ".join(fail_list))

        await inter.followup.send("\n".join(msg) if msg else "⚠️ 無可重載的 cogs。", ephemeral=True)

    async def _reload_one(self, ext: str):
        try:
            if ext in self.bot.extensions:
                await self.bot.reload_extension(ext)
            else:
                await self.bot.load_extension(ext)
            return True, ""
        except Exception as e:
            return False, f"`{type(e).__name__}`: {e}"


async def setup(bot: commands.Bot):
    await bot.add_cog(Reload(bot), guild=TARGET_GUILD)
