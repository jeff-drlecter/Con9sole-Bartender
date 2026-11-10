import asyncio
import io
import json
import discord
from discord import app_commands
from discord.ext import commands
import config
from features import service_access as service,anti_scam_fix as journal

class ServiceAccess(commands.Cog):
    def __init__(self,bot):self.bot=bot

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='service_access',description='指定Bot：降權前準備頻道存取／驗收；唔修改Administrator')
    @app_commands.choices(bot=[app_commands.Choice(name='Carl-bot',value='carl'),app_commands.Choice(name='Bartender',value='bartender')],action=[app_commands.Choice(name='預覽',value='preview'),app_commands.Choice(name='套用',value='apply'),app_commands.Choice(name='驗收',value='verify'),app_commands.Choice(name='復原',value='restore'),app_commands.Choice(name='進度',value='status')])
    async def access(self,inter:discord.Interaction,bot:str,action:str='preview',plan_id:str=''):
        await inter.response.defer(ephemeral=True,thinking=True)
        audit=self.bot.get_cog('PermissionAudit')
        if not audit or not await audit.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if action=='status':
            try:
                result=await asyncio.to_thread(journal.load,plan_id,inter.guild_id,inter.user.id)
                if result.get('scope')!='service_access' or result.get('service')!=bot:raise ValueError('計劃不符。')
                await inter.followup.send(journal.summary(result),ephemeral=True)
            except ValueError as exc:await inter.followup.send(str(exc),ephemeral=True)
            return
        if audit.lock.locked():
            await inter.followup.send('另一項權限操作進行中。',ephemeral=True);return
        async with audit.lock:
            try:
                async with asyncio.timeout(210):
                    if action=='preview':
                        result=await service.plan(inter.guild,bot,inter.user.id)
                        await asyncio.to_thread(journal.save,result)
                        text=journal.summary(result)+f"\n待準備共{result['remaining']}項；只準備本批。角色建議值 {result['role_after']}，尚未降權。"
                    elif action in ('apply','restore'):
                        result=await asyncio.to_thread(journal.load,plan_id,inter.guild_id,inter.user.id)
                        if result.get('service')!=bot:raise ValueError('計劃與服務不符。')
                        async def heartbeat():
                            while True:
                                await asyncio.sleep(10)
                                try:await inter.edit_original_response(content=journal.summary(result)+'\n只準備服務所需頻道權限，未修改Administrator。')
                                except discord.HTTPException:pass
                        task=asyncio.create_task(heartbeat())
                        try:await service.execute(inter.guild,result,lambda:audit.authorized(inter),restore=action=='restore')
                        finally:
                            task.cancel()
                            try:await task
                            except asyncio.CancelledError:pass
                        text=journal.summary(result)+'\n本批停止；未修改Administrator。重新預覽剩餘項，未知結果先核對。'
                    elif action=='verify':
                        result=await service.validate_live(inter.guild,bot)
                        text=f"{bot}｜Administrator {result['administrator']}｜頻道 {result['channels_checked']}｜缺少 {len(result['missing'])}個\n只屬權限驗收；仍需功能實測。"
                    else:raise ValueError('未知操作。')
                    if not await audit.authorized(inter):return
                    if action in ('apply','restore'):await inter.edit_original_response(content=text)
                    payload=json.dumps(result,ensure_ascii=False,indent=2).encode()
                    await inter.followup.send(text,file=discord.File(io.BytesIO(payload),filename='service-access.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException,TimeoutError) as exc:
                await inter.followup.send(str(exc) if isinstance(exc,ValueError) else '操作已停止；保留紀錄，請用進度查詢及權限核對，唔好盲目重試。',ephemeral=True)

async def setup(bot):await bot.add_cog(ServiceAccess(bot))
