// Standalone Apps Script web app. Only a hash of the Bot token is stored here.
function jsonReply(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(event) {
  const props = PropertiesService.getScriptProperties();
  try {
    if (!event.postData || event.postData.contents.length > 80000) {
      return jsonReply({error: 'invalid'});
    }
    const request = JSON.parse(event.postData.contents);
    if (typeof request.token !== 'string' || !/^[a-f0-9]{64}$/.test(request.token)) {
      return jsonReply({error: 'forbidden'});
    }
    const hash = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, request.token);
    const actual = hash.map(b => (b & 255).toString(16).padStart(2, '0')).join('');
    if (actual !== props.getProperty('GTA_TOKEN_SHA256')) {
      return jsonReply({error: 'forbidden'});
    }
    if (typeof request.text !== 'string' || !request.text.trim() || request.text.length > 20000) {
      return jsonReply({error: 'invalid'});
    }
    const characters = Array.from(request.text);
    const lock = LockService.getScriptLock();
    lock.waitLock(5000);
    try {
      const month = Utilities.formatDate(new Date(), 'Asia/Hong_Kong', 'yyyy-MM');
      const key = 'GTA_USAGE_' + month;
      const used = Number(props.getProperty(key) || '0');
      if (!Number.isSafeInteger(used) || used < 0) throw new Error('Invalid counter');
      if (used + characters.length > 450000) return jsonReply({error: 'month_full'});
      props.setProperty(key, String(used + characters.length));
    } finally {
      lock.releaseLock();
    }
    // Keep long posts within individual LanguageApp calls; count the full text once.
    const pieces = [];
    for (let start = 0; start < characters.length;) {
      let end = Math.min(start + 1200, characters.length);
      if (end < characters.length) {
        let boundary = end;
        while (boundary > start && !/\s/.test(characters[boundary - 1])) boundary--;
        if (boundary > start) end = boundary;
      }
      const part = characters.slice(start, end).join('');
      if (part.trim()) pieces.push(LanguageApp.translate(part, '', 'zh-TW', {contentType: 'text'}));
      start = end;
    }
    return jsonReply({translation: pieces.join('\n')});
  } catch (error) {
    const detail = String(error);
    const daily = /quota|too many times|daily limit/i.test(detail) && !/short time/i.test(detail);
    return jsonReply({error: daily ? 'daily_limit' : 'unavailable'});
  }
}
