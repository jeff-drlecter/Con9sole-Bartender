"""Conservative, explainable help candidates; stores references, never message bodies."""
import re
import unicodedata
from core.helper_sandbox import HelperStore


def detect_help(content):
    text=unicodedata.normalize('NFKC',content).casefold()
    text=re.sub(r'```.*?```','',text,flags=re.S)
    text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))
    text=re.sub(r'https?://\S+','',text).strip()
    if not text: return None
    resolved=r'已經?解決|已解決|搞掂(?!未)|解決咗|唔使幫|不用幫|唔洗幫|問題解決|fixed it|solved it|never mind|nvm'
    if re.search(resolved,text): return None
    if re.search(r'有咩(?:可以)?幫(?:手|到)|有什麼(?:可以)?幫|我(?:可以|嚟|來)幫|let me help|happy to help|can i help',text): return None
    if re.search(r'求助|求救|救命|幫幫手|幫下手|幫吓手|幫我|幫忙|請教|求教|need (?:some )?help|can (?:anyone|someone|you) help',text): return '明確求助用語'
    if re.search(r'點樣|點先可以|點解|點搞|點整|有[冇無沒]人(?:識|知|知道)|想問|請問|如何|怎[麼樣]|how (?:do|can|to)|anyone know',text): return '詢問方法／原因'
    if re.search(r'搞唔掂|唔識|唔知點|入唔到|連唔到|開唔到|玩唔到|登入唔到|連線失敗|閃退|卡住|無法(?:登入|連線|啟動)|can.t (?:connect|launch|login|log in)|keeps? crashing',text): return '遇到操作／連線困難'
    return None


class DetectionStore(HelperStore):
    def __init__(self,path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS detected_help (
                    message_id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,
                    created REAL,reason TEXT,state TEXT,owner INTEGER,updated REAL,replied INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS help_state_date ON detected_help(state,created);
            ''')

    def observe(self,message_id,channel_id,author_id,created,reason,now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM detected_help WHERE created<?',(now-7*86400,))
            old=db.execute('SELECT state FROM detected_help WHERE message_id=?',(message_id,)).fetchone()
            if reason is None:
                if old: db.execute("UPDATE detected_help SET state='withdrawn',updated=? WHERE message_id=?",(now,message_id))
                return
            if created<now-7*86400: return
            if old:
                # Edits never reopen handled/dismissed candidates.
                db.execute('UPDATE detected_help SET reason=?,updated=? WHERE message_id=?',(reason,now,message_id))
                if old['state']=='withdrawn':
                    db.execute("UPDATE detected_help SET state='open',owner=NULL WHERE message_id=?",(message_id,))
            else:
                db.execute("INSERT INTO detected_help VALUES (?,?,?,?,?,'open',NULL,?,0)",(message_id,channel_id,author_id,created,reason,now))
            db.execute('DELETE FROM detected_help WHERE message_id IN (SELECT message_id FROM detected_help ORDER BY created DESC LIMIT -1 OFFSET 1000)')

    def reply(self,message_id,author_id):
        with self.connect() as db:
            db.execute('UPDATE detected_help SET replied=1 WHERE message_id=? AND author_id!=?',(message_id,author_id))

    def withdraw(self,message_id,now):
        self.observe(message_id,0,0,now,None,now)

    def prune(self,now):
        with self.connect() as db: db.execute('DELETE FROM detected_help WHERE created<?',(now-7*86400,))

    def candidates(self,now,closed=False):
        with self.connect() as db:
            states="('done','dismissed')" if closed else "('open','claimed','handoff')"
            return [dict(r) for r in db.execute('SELECT * FROM detected_help WHERE state IN '+states+' AND created>=? ORDER BY replied,created DESC LIMIT 1000',(now-7*86400,))]

    def detection(self,message_id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM detected_help WHERE message_id=?',(message_id,)).fetchone()
        return dict(row) if row else None

    def act(self,message_id,user,action,now,admin=False):
        if action not in {'claim','done','handoff','dismiss'}: raise ValueError('無效操作。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM detected_help WHERE message_id=?',(message_id,)).fetchone()
            if not row or row['created']<now-7*86400 or row['state'] in {'done','dismissed','withdrawn'}: raise ValueError('呢則求助已處理、撤回或過期。')
            if action=='claim':
                if row['owner'] is not None: raise ValueError('已有人接手。')
                state,owner,label='claimed',user,'已接手，請到原頻道回覆'
            elif action=='dismiss':
                if row['owner'] not in (None,user) and not admin: raise ValueError('已有負責人，請由佢確認。')
                state,owner,label='dismissed',user,'已標記為誤判'
            else:
                if row['owner']!=user and not admin: raise ValueError('只限負責人或管理員處理。')
                state,owner,label=('done',user,'已完成') if action=='done' else ('handoff',None,'已轉交其他 Helper')
            db.execute('UPDATE detected_help SET state=?,owner=?,updated=? WHERE message_id=?',(state,owner,now,message_id))
            return label
