from __future__ import annotations

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config
from core.permissions import is_server_admin
from features.onboarding_wording import neutralize_prompts
from features.language_preferences import LanguageView, ROLE_NAMES, PROMPT_TITLE, preference_roles, serialize_prompts, make_room_for_language


class LanguagePreferences(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def menu_entry(self, interaction):
        from features.language_preferences import language
        current = "台灣" if language(interaction.user) == "tw" else "香港"
        await interaction.response.send_message(
            f"目前語境：{current}。\n香港語境／台灣語境：私人選單、會員卡、訂閱確認及通用錯誤提示按偏好顯示；公開招募卡及通知採用共通繁體中文，部分舊功能回覆仍待整理。與所在地無關。\n切換後請使用新選單；舊訊息不會自動改寫。",
            view=LanguageView(interaction.user.id), ephemeral=True)

    @app_commands.command(name="language", description="切換香港／台灣 Bot 用語")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def language_command(self, interaction: discord.Interaction):
        await self.menu_entry(interaction)

    @app_commands.command(name="language_onboarding_setup", description="管理員：加入香港／台灣語境 onboarding 選項")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    async def setup_command(self, interaction: discord.Interaction):
        if interaction.guild_id != config.GUILD_ID or not is_server_admin(await interaction.guild.fetch_member(interaction.user.id)):
            await interaction.response.send_message("只限伺服器管理員。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            try:
                guild = interaction.guild
                roles = await guild.fetch_roles()
                # Never reuse a privileged or ambiguous role with the same name.
                for name in ROLE_NAMES.values():
                    matches = [r for r in roles if r.name == name]
                    if len(matches) > 1 or any(r.managed or r.permissions.value for r in matches):
                        raise ValueError("同名語境角色有衝突；未更改 onboarding。")
                if not is_server_admin(await guild.fetch_member(interaction.user.id)):
                    raise ValueError("管理權限已變更。")
                for name in ROLE_NAMES.values():
                    if not any(r.name == name for r in roles):
                        if not is_server_admin(await guild.fetch_member(interaction.user.id)):
                            raise ValueError("管理權限已變更。")
                        roles.append(await guild.create_role(name=name, permissions=discord.Permissions.none(), mentionable=False, hoist=False, reason="Wording preference only"))
                chosen = preference_roles(roles, await guild.fetch_channels())
                current = await guild.onboarding()
                prompts = neutralize_prompts(serialize_prompts(current))
                matches = [p for p in prompts if p["title"] == PROMPT_TITLE]
                if len(matches) > 1:
                    raise ValueError("重複語境題目；未更改 onboarding。")
                expected = [{"title": "香港語境", "description": "廣東話／香港常用詞", "role_ids": [str(chosen["hk"].id)], "channel_ids": []},
                            {"title": "台灣語境", "description": "台灣繁體中文常用詞", "role_ids": [str(chosen["tw"].id)], "channel_ids": []}]
                if matches:
                    p = matches[0]
                    if p["single_select"] is not True or not p["in_onboarding"] or [o.get("role_ids") for o in p["options"]] != [o["role_ids"] for o in expected]:
                        raise ValueError("現有語境題目設定不同；未覆寫。")
                else:
                    prompts = make_room_for_language(prompts)
                    prompts.append(dict(id="0", type=0, title=PROMPT_TITLE, single_select=True, required=False, in_onboarding=True, options=expected))
                prompts = neutralize_prompts(prompts)
                if prompts != serialize_prompts(current):
                    if not is_server_admin(await guild.fetch_member(interaction.user.id)):
                        raise ValueError("管理權限已變更。")
                    if serialize_prompts(await guild.onboarding()) != serialize_prompts(current):
                        raise ValueError("Onboarding 已被其他人更改，請重新執行。")
                    import json
                    from datetime import datetime, timezone
                    from core.storage_paths import DATA_DIR
                    backup = DATA_DIR / ("language-onboarding-before-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
                    backup.write_text(json.dumps({"guild_id": str(guild.id), "prompts": serialize_prompts(current)}, ensure_ascii=False, indent=2))
                    # Use raw transport solely to retain existing prompt/option snowflake IDs.
                    await guild._state.http.edit_guild_onboarding(guild.id, prompts=prompts, reason="Neutral Traditional Chinese onboarding copy; preserve answer IDs and mappings")
                after = serialize_prompts(await guild.onboarding())
                original = neutralize_prompts(serialize_prompts(current))
                if not matches:
                    original = make_room_for_language(original)
                if any(p not in after for p in original):
                    raise ValueError("讀回發現原有題目不同，請管理員檢查；未自動重試。")
                added = [p for p in after if p["title"] == PROMPT_TITLE]
                if len(added) != 1 or [o.get("role_ids") for o in added[0]["options"]] != [o["role_ids"] for o in expected]:
                    raise ValueError("未能確認新題目；請檢查，未自動重試。")
                await interaction.followup.send("✅ Onboarding 中性繁體中文及語境選項已讀回確認；原有問題及選項 ID 已保留；新聞區顯示選項移到入服後「頻道與身份組」（原先四條入服前問題已滿）。兩個偏好角色均為零權限。日常可用 /menu → 更多玩法 → 資訊與設定 → 語境設定，或 /language 切換。", ephemeral=True)
            except (ValueError, discord.HTTPException) as exc:
                await interaction.followup.send(f"設定未完成：{exc}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(LanguagePreferences(bot))
