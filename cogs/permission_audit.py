"""Admin-only read-only permission audit export."""
import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands
import config
from core.permissions import is_server_admin
from features.permission_audit import collect, archive


class PermissionAudit(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.lock=asyncio.Lock()
        self.last_run=0

    async def authorized(self,inter):
        if inter.guild_id!=config.GUILD_ID or inter.guild is None:return False
        # Refresh actor authority rather than trusting a panel's cached member.
        try:actor=await inter.guild.fetch_member(inter.user.id)
        except discord.HTTPException:return False
        return is_server_admin(actor)

    async def menu_entry(self,inter):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked() or time.monotonic()-self.last_run<60:
            await inter.followup.send('報告生成中或剛完成，請稍候一分鐘再試。',ephemeral=True);return
        async with self.lock:
            snapshot=await collect(inter.guild,config.VERIFIED_ROLE_ID)
            output=await asyncio.to_thread(archive,snapshot)
            if not await self.authorized(inter):
                await inter.followup.send('權限已改變，報告未送出。',ephemeral=True);return
            if output.getbuffer().nbytes>inter.guild.filesize_limit:
                await inter.followup.send('報告超出附件限制，未有送出；請聯絡維護者。',ephemeral=True);return
            self.last_run=time.monotonic()
            counts={level:sum(r['severity']==level for r in snapshot['findings']) for level in ('warning','policy','review')}
            await inter.followup.send(
                f"**Anti-scam Update｜權限審核**\n角色 {len(snapshot['roles'])}｜分類／頻道 {len(snapshot['channels'])}\n"
                f"需優先核對 {counts['warning']}｜設計差異 {counts['policy']}｜一般覆核 {counts['review']}\n"
                f"Onboarding：{snapshot['onboarding']['status']}｜AutoMod：{snapshot['automod']['status']}\n"
                '附件包含摘要及完整 JSON；未修改任何設定。未涵蓋 threads 或逐人有效權限，詳見 coverage。',
                file=discord.File(output,filename='anti-scam-permission-audit.zip'),
                ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='permission_audit',description='Anti-scam Update：唯讀匯出角色、分類、頻道及權限報告')
    async def audit(self,inter:discord.Interaction):
        try:await self.menu_entry(inter)
        except discord.HTTPException:
            await inter.followup.send('Discord 讀取或附件傳送失敗；未修改任何設定，請稍後再試。',ephemeral=True)

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='anti_scam_fix',description='預覽／套用大量 mention 清理及未驗證語音感應修正')
    @app_commands.choices(action=[app_commands.Choice(name='預覽',value='preview'),app_commands.Choice(name='套用指定預覽',value='apply'),app_commands.Choice(name='復原指定計劃',value='restore')])
    async def fix(self,inter:discord.Interaction,action:str='preview',plan_id:str=''):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項審核／修正進行中，請稍後。',ephemeral=True);return
        from features import anti_scam_fix as fixes
        import io
        import json
        async with self.lock:
            try:
                if action=='preview':
                    roles=await inter.guild.fetch_roles();channels=await inter.guild.fetch_channels()
                    plan=fixes.build(roles,channels,inter.guild_id,inter.user.id,config.VERIFIED_ROLE_ID)
                    await asyncio.to_thread(fixes.save,plan)
                elif action in ('apply','restore'):
                    plan=await asyncio.to_thread(fixes.load,plan_id,inter.guild_id,inter.user.id)
                    if plan.get('scope') is not None:raise ValueError('計劃屬於其他修正範圍，請使用原有專用指令。')
                    await fixes.execute(inter.guild,plan,lambda:self.authorized(inter),restore=action=='restore')
                else:raise ValueError('未知操作。')
                if not await self.authorized(inter):return
                text=fixes.summary(plan)
                if action=='preview':
                    text+='\n只清理已核對普通角色嘅大量 mention 權限，並開啟 @everyone 語音感應；唔會開放原本不可見／不可連線嘅房間。\n完整修改清單見附件。套用：/anti_scam_fix action:套用指定預覽 plan_id:'+plan['id']
                payload=io.BytesIO(json.dumps(plan,ensure_ascii=False,indent=2).encode())
                await inter.followup.send(text,file=discord.File(payload,filename='anti-scam-change-plan.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException) as exc:
                text=str(exc) if isinstance(exc,ValueError) else 'Discord 操作結果需核對；停止後續修改，唔會自動重試。'
                await inter.followup.send(text+'\n如有部分操作，請用相同計劃復原或重新審核。',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='anti_scam_rules',description='唯讀產生連結限制及全員疑似洗版 AutoMod 草案')
    async def rules(self,inter:discord.Interaction):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項審核進行中，請稍後。',ephemeral=True);return
        from features.anti_scam_rules import draft,summary
        import io
        import json
        async with self.lock:
            try:
                roles,channels,rules=await asyncio.gather(inter.guild.fetch_roles(),inter.guild.fetch_channels(),inter.guild.fetch_automod_rules())
                plan=draft(roles,channels,rules,config.VERIFIED_ROLE_ID)
                if not await self.authorized(inter):
                    await inter.followup.send('權限已改變，草案未送出。',ephemeral=True);return
                payload=json.dumps(plan,ensure_ascii=False,indent=2).encode()
                if len(payload)>inter.guild.filesize_limit:
                    await inter.followup.send('草案超出附件限制，未送出。',ephemeral=True);return
                await inter.followup.send(summary(plan),file=discord.File(io.BytesIO(payload),filename='anti-scam-rule-draft.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await inter.followup.send('未能讀取完整 AutoMod 設定，未產生可套用草案；未修改任何設定。',ephemeral=True)

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='anti_scam_monitor',description='啟用／查看／停用兩條指定 AutoMod 只提示監察規則')
    @app_commands.choices(mode=[app_commands.Choice(name='查看狀態',value='status'),app_commands.Choice(name='啟用只提示監察',value='enable'),app_commands.Choice(name='停用本工具監察',value='disable')])
    async def monitor(self,inter:discord.Interaction,mode:str='status'):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項操作進行中，請稍後。',ephemeral=True);return
        if mode not in ('status','enable','disable'):
            await inter.followup.send('未知操作。',ephemeral=True);return
        from features.anti_scam_monitor import run
        async with self.lock:
            try:
                result=await run(inter.guild,config.VERIFIED_ROLE_ID,lambda:self.authorized(inter),mode,actor=inter.user.id)
                if not await self.authorized(inter):return
                await inter.followup.send('**Anti-scam｜只提示監察**\n'+'\n'.join(result)+'\n提示送到管理員指令頻道；唔封鎖訊息、唔停權、唔撤銷 Verified。',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException) as exc:
                detail=str(exc) if isinstance(exc,ValueError) else 'Discord 操作未能確認，請查看狀態；唔自動重複建立。'
                await inter.followup.send(detail+'\n可能已有部分規則建立，請用查看狀態核對。',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='participation_fix',description='預覽／套用已加入公海會員的聊天權限修正')
    @app_commands.choices(action=[app_commands.Choice(name='預覽',value='preview'),app_commands.Choice(name='套用指定預覽',value='apply'),app_commands.Choice(name='復原指定計劃',value='restore')])
    async def participation(self,inter:discord.Interaction,action:str='preview',plan_id:str=''):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項操作進行中，請稍後。',ephemeral=True);return
        from features import anti_scam_fix as fixes
        from features.participation_fix import build,execute
        import io,json
        async with self.lock:
            try:
                if action=='preview':
                    roles,channels=await asyncio.gather(inter.guild.fetch_roles(),inter.guild.fetch_channels())
                    plan=build(roles,channels,inter.guild_id,inter.user.id)
                    await asyncio.to_thread(fixes.save,plan)
                elif action in ('apply','restore'):
                    plan=await asyncio.to_thread(fixes.load,plan_id,inter.guild_id,inter.user.id)
                    if plan.get('scope')!='participation':raise ValueError('計劃唔屬於公海參與修正。')
                    await execute(inter.guild,plan,lambda:self.authorized(inter),restore=action=='restore')
                else:raise ValueError('未知操作。')
                if not await self.authorized(inter):return
                lines=[fixes.summary(plan)]+[o['name'] for o in plan['ops']]+plan['skipped']
                lines+=['只改兩個指定公海頻道的 off-topic 發言／討論串回覆。唔改可見性或附件權限位元；舊角色已有附件／預覽權限可能隨發言開放而可用。連結仍只提示。']
                if action=='preview':lines+=['套用時指定計劃 ID：'+plan['id']]
                payload=io.BytesIO(json.dumps(plan,ensure_ascii=False,indent=2).encode())
                await inter.followup.send('\n'.join(lines),file=discord.File(payload,filename='participation-plan.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException) as exc:
                text=str(exc) if isinstance(exc,ValueError) else 'Discord 操作需核對，唔會自動重試。'
                await inter.followup.send(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='verified_access_preview',description='唯讀檢查未 Verified 附件／預覽角色組合及產生收窄草案')
    async def verified_preview(self,inter:discord.Interaction):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項操作進行中，請稍後。',ephemeral=True);return
        from features.verified_access_preview import preview,summary
        import io,json
        async with self.lock:
            try:
                snapshot=await collect(inter.guild,config.VERIFIED_ROLE_ID)
                result=await asyncio.to_thread(preview,snapshot,config.VERIFIED_ROLE_ID)
                if not await self.authorized(inter):
                    await inter.followup.send('權限已改變，預覽未送出。',ephemeral=True);return
                payload=json.dumps(result,ensure_ascii=False,indent=2).encode()
                if len(payload)>inter.guild.filesize_limit:
                    await inter.followup.send('預覽超出附件限制，未送出。',ephemeral=True);return
                await inter.followup.send(summary(result),file=discord.File(io.BytesIO(payload),filename='verified-access-preview.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await inter.followup.send('未能讀取完整設定；未修改任何權限。',ephemeral=True)


    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name='stage1_permissions',description='第1階段：預覽／分批套用附件預覽權限及驗收')
    @app_commands.choices(action=[app_commands.Choice(name='預覽',value='preview'),app_commands.Choice(name='套用指定預覽',value='apply'),app_commands.Choice(name='復原指定計劃',value='restore'),app_commands.Choice(name='驗收目前設定',value='verify')])
    async def stage1(self,inter:discord.Interaction,action:str='preview',plan_id:str=''):
        await inter.response.defer(ephemeral=True,thinking=True)
        if not await self.authorized(inter):
            await inter.followup.send('只限本伺服器管理員。',ephemeral=True);return
        if self.lock.locked():
            await inter.followup.send('另一項權限操作進行中，請稍後。',ephemeral=True);return
        from features import stage1_permissions as policy, anti_scam_fix as journal
        import io,json
        async with self.lock:
            try:
                snapshot=await collect(inter.guild,config.VERIFIED_ROLE_ID)
                snapshot['service_members']={}
                for role in snapshot['roles']:
                    if role.get('bot_id'):
                        member=await inter.guild.fetch_member(int(role['bot_id']))
                        snapshot['service_members'][role['id']]=[str(r.id) for r in member.roles if r.id!=inter.guild_id]
                trusted={r['id'] for r in snapshot['roles'] if policy.privileged(r)}
                snapshot['staff_members']={}
                async for member in inter.guild.fetch_members(limit=None):
                    ids=[str(r.id) for r in member.roles if r.id!=inter.guild_id]
                    if not member.bot and trusted.intersection(ids):
                        snapshot['staff_members'][str(member.id)]=ids
                if action=='preview':
                    result=await asyncio.to_thread(policy.build,snapshot,inter.user.id,config.VERIFIED_ROLE_ID)
                    await asyncio.to_thread(journal.save,result)
                    text=journal.summary(result)+'\n只改附件及連結預覽；4個VIP例外保留。\n套用：/stage1_permissions action:套用指定預覽 plan_id:'+result['id']
                    text+='\n階段未結案：'+('；'.join(result['blockers']) or '仍需套用後驗收及Bot功能實測。')
                elif action in ('apply','restore'):
                    result=await asyncio.to_thread(journal.load,plan_id,inter.guild_id,inter.user.id)
                    if result.get('scope')!='stage1_caps':raise ValueError('計劃不屬於第1階段。')
                    if action=='apply' and policy.fingerprint(snapshot)!=result['fingerprint']:
                        raise ValueError('角色／頻道設定已變更，請重新預覽；未套用。')
                    await policy.execute(inter.guild,result,lambda:self.authorized(inter),restore=action=='restore')
                    if action=='apply':
                        result['live_verification']=await asyncio.to_thread(policy.verify,await collect(inter.guild,config.VERIFIED_ROLE_ID),config.VERIFIED_ROLE_ID)
                        await asyncio.to_thread(journal.save,result)
                    text=journal.summary(result)+'\n已停止於第一個衝突／未知結果；詳見附件。階段是否完成仍以驗收及Bot最小權限核對為準。'
                elif action=='verify':
                    result=await asyncio.to_thread(policy.verify,snapshot,config.VERIFIED_ROLE_ID)
                    text='目前附件／預覽驗收：非例外殘留 '+str(len(result['unexpected_unverified_caps']))+' 個。\n此結果不代表Bot降權或實際成員功能已驗收完成。'
                else:raise ValueError('未知操作。')
                if not await self.authorized(inter):return
                payload=json.dumps(result,ensure_ascii=False,indent=2).encode()
                if len(payload)>inter.guild.filesize_limit:raise ValueError('報告超出附件限制。')
                await inter.followup.send(text,file=discord.File(io.BytesIO(payload),filename='stage1-permissions.json'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except (ValueError,discord.HTTPException) as exc:
                text=str(exc) if isinstance(exc,ValueError) else 'Discord結果需核對；停止後續修改，不自動重試。'
                await inter.followup.send(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):await bot.add_cog(PermissionAudit(bot))
