// Exercise the exact source pasted into Apps Script, with offline Google service fakes.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../apps-script/gta-translation/Code.gs'), 'utf8');
const token = 'a'.repeat(64);
const digest = value => crypto.createHash('sha256').update(value).digest();
const values = new Map([['GTA_TOKEN_SHA256', digest(token).toString('hex')]]);
const chunks = [];
let locked = false;
const services = {
  PropertiesService: { getScriptProperties: () => ({
    getProperty: key => values.get(key),
    setProperty: (key, value) => { assert.ok(locked); values.set(key, value); }
  }) },
  LockService: { getScriptLock: () => ({
    waitLock: () => { assert.ok(!locked); locked = true; },
    releaseLock: () => { locked = false; }
  }) },
  Utilities: {
    DigestAlgorithm: {SHA_256: 'SHA-256'},
    computeDigest: (_, value) => Array.from(new Int8Array(digest(value))),
    formatDate: (_, zone) => { assert.equal(zone, 'Asia/Hong_Kong'); return '2026-11'; }
  },
  ContentService: {MimeType: {JSON: 'json'}, createTextOutput: str => ({setMimeType: () => JSON.parse(str)})},
  LanguageApp: { translate: (text, source, target) => {
    assert.equal(locked, false); assert.equal(source, ''); assert.equal(target, 'zh-TW');
    chunks.push(text); return '譯文';
  } }
};
vm.runInNewContext(code, services);
const post = (text, credential = token) => services.doPost({postData: {contents: JSON.stringify({text, token: credential})}});
assert.equal(post('race', '0'.repeat(64)).error, 'forbidden');
assert.equal(post('').error, 'invalid');
assert.equal(chunks.length, 0);
const input = 'A new race. '.repeat(125) + '🏁';
assert.equal(post(input).translation, '譯文\n譯文');
assert.equal(chunks.join(''), input);
assert.equal(values.get('GTA_USAGE_2026-11'), String(Array.from(input).length));
values.set('GTA_USAGE_2026-11', '449999');
assert.equal(post('🏁').translation, '譯文');
assert.equal(post('a').error, 'month_full');
assert.equal(values.get('GTA_USAGE_2026-11'), '450000');
assert.equal(locked, false);
assert.equal(chunks.length, 3);
