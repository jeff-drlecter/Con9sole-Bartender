"""Render the synthetic Discord SDK responses recorded by the draft replay."""

from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from zoneinfo import ZoneInfo


def render_control(control):
    label = escape(control["label"])
    if control["value"] is not None:
        value = escape(control["value"], quote=True)
        if control["required"]:
            label += "（必填）"
        return f'<label>{label}<input readonly value="{value}"></label>'
    disabled = " disabled" if control["disabled"] else ""
    return f"<button{disabled}>{label}</button>"


def hong_kong_time(match):
    value = datetime.fromtimestamp(int(match[1]), ZoneInfo("Asia/Hong_Kong"))
    return value.strftime("%Y-%m-%d %H:%M（香港）")


def render_report(evidence):
    trace = json.loads((evidence / "trace.json").read_text(encoding="utf-8"))
    steps = trace["steps"]
    verdict = "通過" if trace["passed"] else f'未通過 · {escape(trace["failed_step"] or "互動或測試環境")}'
    cards = []
    for step in steps:
        controls = "".join(render_control(control) for control in step["controls"])
        content = escape(step["content"])
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"&lt;t:(\d{1,11}):F&gt;", hong_kong_time, content)
        cards.append(f'<section><h2>{escape(step["step"])}</h2>'
                     f'<p>{content}</p><div>{controls}</div></section>')
    page = evidence / "replay.html"
    page.write_text("""<!doctype html>
<html lang="zh-HK"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>約局草稿離線驗收</title>
<style>
* { box-sizing: border-box }
body { margin: 0; padding: 28px; font: 16px/1.55 system-ui,sans-serif; background: #f3f5f8; color: #182637 }
h1, h2, p { margin: 0 }
h1 { font-size: 26px }
header p { margin: 3px 0 18px; color: #435367 }
main { display: grid; gap: 14px; grid-template-columns: repeat(2,minmax(0,1fr)) }
section { background: white; border: 1px solid #c8d2dd; border-radius: 8px; padding: 18px }
section h2 { font-size: 18px; color: #224e70 }
section p { white-space: pre-wrap; overflow-wrap: anywhere; margin: 12px 0 }
section div { display: flex; gap: 6px; flex-wrap: wrap }
button, input { font: inherit; border: 1px solid #b4c2ce; border-radius: 5px; padding: 3px 9px }
button { font-size: 14px; background: #edf4fb; color: #204765 }
button:disabled { color: #787f87; background: #f2f2f2; border-style: dashed }
label { display: block; width: 100%; color: #354759 }
input { display: block; background: white; width: 100%; margin-top: 3px }
@media (max-width: 700px) { main { grid-template-columns: 1fr } }
</style>""" + f"<header><h1>約局草稿離線驗收 · {verdict}</h1>"
                    + "<p>合成會員操作後，Discord SDK 回傳嘅文字、欄位及按鈕狀態。</p></header><main>"
                    + "".join(cards) + "</main></html>", encoding="utf-8")

    mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    chrome = (shutil.which("google-chrome") or shutil.which("chromium")
              or shutil.which("chromium-browser") or (mac_chrome if Path(mac_chrome).is_file() else None))
    if not chrome:
        raise SystemExit(f"Install Chrome or Chromium to capture the replay. Saved SDK report: {page}")

    # An empty browser profile renders only the local report, without loading Discord or a user session.
    screenshot = evidence / "replay.png"
    rows = (len(steps) + 1) // 2
    height = max(680, 240 + 320 * rows)
    browser_env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "SYSTEMROOT") if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="draft-replay-browser-") as profile:
        command = [chrome, "--headless", "--no-first-run", "--disable-extensions",
                   "--disable-background-networking", "--disable-component-update",
                   "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={profile}",
                   f"--window-size=1240,{height}", f"--screenshot={screenshot}", page.as_uri()]
        result = subprocess.run(command, env=browser_env, capture_output=True, text=True, timeout=60)
    if result.returncode or not screenshot.is_file() or not screenshot.stat().st_size:
        raise SystemExit(f"Chrome could not capture {page}: {result.stderr[-1000:]}")
    print(f"Saved {len(steps)} SDK states and their visual report: {screenshot}")
