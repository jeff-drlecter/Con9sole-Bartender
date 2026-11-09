"""Generate a read-only AutoMod draft, never call create/edit/delete."""
from datetime import datetime, timezone
import re

ALERT_CHANNEL=1425054477597016084
LINK_PATTERN=r'(?i)(?:https?://|www\.|discord\.gg/|discord(?:app)?\.com/invite/)[^\s<>]+'


def draft(roles,channels,rules,verified):
    role_ids={r.id for r in roles};channel_ids={c.id for c in channels}
    current=[r.to_dict() for r in rules]
    blockers=[];notes=[];proposals=[]
    if verified not in role_ids:blockers.append('Verified 角色不存在，禁止建立豁免規則。')
    if ALERT_CHANNEL not in channel_ids:blockers.append('管理員提示頻道不存在，需先指定。')
    if sum(r['trigger_type']==1 for r in current)>=6:blockers.append('Custom Keyword 規則已滿6條；不可直接新增連結規則。')
    if any(r['name']=='Anti-scam | Unverified links' for r in current):blockers.append('已有同名連結規則；需比較既有設定，唔可重複新增。')
    proposals.append(dict(purpose='未 Verified 連結限制',suggested_rollout='先只提示管理員，測試後再切換封鎖＋提示',
        payload=dict(name='Anti-scam | Unverified links',event_type=1,trigger_type=1,
            trigger_metadata=dict(regex_patterns=[LINK_PATTERN]),enabled=False,
            exempt_roles=[str(verified)],exempt_channels=[],actions=[dict(type=2,metadata=dict(channel_id=str(ALERT_CHANNEL)))]),
        after_validation_actions=[dict(type=1,metadata=dict(custom_message='未 Verified 暫時唔可以貼外部連結，請聯絡管理員協助。')),dict(type=2,metadata=dict(channel_id=str(ALERT_CHANNEL))) ]))
    spam=[r for r in current if r['trigger_type']==3]
    if spam:
        notes.append('已有原生 spam 規則，保留原規則；需核對其啟用狀態、actions 及豁免，唔新增重複規則。')
    else:
        proposals.append(dict(purpose='全員疑似洗版監察',suggested_rollout='先只提示；唔因疑似洗版自動停權或撤銷 Verified',
            payload=dict(name='Anti-scam | Suspected spam',event_type=1,trigger_type=3,enabled=False,
                exempt_roles=[],exempt_channels=[],actions=[dict(type=2,metadata=dict(channel_id=str(ALERT_CHANNEL)))])))
    mention=[r for r in current if r['trigger_type']==5]
    notes.append('保留現有 mention 規則；唔改現有門檻或 actions。' if mention else '未發現原生 mention 規則，需另外評估。')
    notes.extend([
        '此草案不會建立、修改或啟用 AutoMod；所有新增候選 enabled=false。',
        'Verified 只豁免未驗證連結規則，唔豁免全員疑似洗版監察。Administrator／Manage Server 有 Discord 原生 AutoMod 豁免。',
        '連結正則涵蓋 http(s)、www、Discord 邀請；裸域名、混淆／Unicode／零寬字元及 QR 圖片未涵蓋。',
        '一般 YouTube／遊戲官網連結亦會命中未驗證規則；未設定官網白名單，避免子字串白名單放行整則訊息。',
        '原生 spam 偵測唔等於釣魚網址判定；未接入惡意網址資料源。',
        'Bot／webhook／私訊及外部應用有另外限制，唔能夠據此保證全面保護。',
        '不包含自動 Verified、撤銷角色、timeout 或封鎖帳號；需獨立設計及人工覆核。',
        '示例以 Python 正則本地核對，唔係 Discord Rust 正則／真實訊息執行驗收。',
        '提示會包含疑似內容，目的地必須保持私人 staff 頻道；不發送測試通知。'])
    examples=[('https://example.com/game',True),('WWW.example.com',True),('discord.gg/example',True),
              ('[攻略](https://example.com)',True),('今晚一齊打機？',False),('example.com',False),('攻略.png',False)]
    return dict(schema_version=1,update='Anti-scam Update',generated_at=datetime.now(timezone.utc).isoformat(),
        mode='preview_only',blockers=blockers,current_rules=current,proposals=proposals,notes=notes,
        examples=[dict(message=m,expected_match=expected,local_match=bool(re.search(LINK_PATTERN,m))) for m,expected in examples])


def summary(plan):
    purposes='、'.join(p['purpose'] for p in plan['proposals'])
    return ('**Anti-scam 規則草案｜未啟用**\n'
        f"現有 {len(plan['current_rules'])} 條｜新增候選 {len(plan['proposals'])} 條｜阻擋事項 {len(plan['blockers'])} 項\n"
        f'{purposes}\n先只提示管理員；連結封鎖待測試後再啟用。現有規則保持原樣。\n'
        '唔會自動撤銷 Verified／timeout；裸域名、混淆連結、圖片及私訊未涵蓋。完整差異及例子見附件。')
