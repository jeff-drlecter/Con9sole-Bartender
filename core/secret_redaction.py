"""Avoid copying recognizable credentials into message-edit/delete audit previews."""
import re

PATTERNS = (
    re.compile(r'(?i)\boauth:[a-z0-9_-]{12,}'),
    re.compile(r'(?i)\bBearer\s+[a-z0-9._~-]{12,}'),
    re.compile(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w.-]+'),
    re.compile(r'(?i)([\"\']?(?:[a-z0-9_]*(?:token|secret|password|oauth))[\"\']?\s*[:=]\s*[\"\'])([^\"\'\r\n]{8,})([\"\'])'),
)


def redact_credentials(text):
    value = str(text)
    for pattern in PATTERNS[:3]:
        value = pattern.sub('[憑證已遮蔽]', value)
    return PATTERNS[3].sub(lambda m: m[1] + '[憑證已遮蔽]' + m[3], value)
