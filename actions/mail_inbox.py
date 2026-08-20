from __future__ import annotations

import platform
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from typing import Optional

_OS = platform.system()
_MAIL_QUERY_TIMEOUT = 90
_MAIL_SCAN_LIMIT = 15
_BODY_MAX = 1200

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _log(msg: str, player=None) -> None:
    print(f"[Mail] {msg}")
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def _days_back(parameters: dict) -> int:
    raw = parameters.get("days") or parameters.get("since_days") or 3
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = 3
    return max(1, min(days, 14))


def _strip_html(text: str) -> str:
    text = re.sub(r"(?i)<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_mail_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return date(y, mo, d)
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", raw)
    if m:
        d, mon, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mo = _MONTHS.get(mon)
        if mo:
            return date(y, mo, d)
    return None


def _fast_mail_script(limit: int) -> str:
    return f'''
tell application "Mail"
    set output to ""
    repeat with i from 1 to {limit}
        try
            set m to message i of inbox
            set s to subject of m
            set snd to sender of m
            set dr to date received of m
            set ds to ((year of dr) as text) & "-" & ((month of dr) as integer) & "-" & (day of dr)
            set output to output & s & (ASCII character 9) & snd & (ASCII character 9) & ds & linefeed
        end try
    end repeat
    return output
end tell
'''


def _search_mail_script(limit: int, needle: str) -> str:
    safe = needle.replace('"', "")
    return f'''
set needle to "{safe}"
tell application "Mail"
    repeat with i from 1 to {limit}
        try
            set m to message i of inbox
            set s to subject of m
            ignoring case
                if s contains needle then
                    set snd to sender of m
                    set dr to date received of m
                    set ds to ((year of dr) as text) & "-" & ((month of dr) as integer) & "-" & (day of dr)
                    set bodyText to content of m
                    return s & (ASCII character 9) & snd & (ASCII character 9) & ds & (ASCII character 9) & bodyText
                end if
            end ignoring
        end try
    end repeat
end tell
return ""
'''


def _run_osascript(script: str) -> tuple[str, Optional[str]]:
    for attempt in (1, 2):
        try:
            print(f"[Mail] Querying Mail.app (attempt {attempt})…")
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=_MAIL_QUERY_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            if attempt == 1:
                print("[Mail] ⚠️ Timeout — retrying once…")
                time.sleep(2)
                continue
            return "", (
                "Mail.app timed out — it may still be syncing Gmail. "
                "Wait until Mail finishes downloading, then try again."
            )
        except Exception as exc:
            return "", f"Could not read Mail.app: {exc}"

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "unknown error").strip()
            if "Not authorized" in err or "1743" in err:
                return "", (
                    "Mail permission denied. Allow Terminal to control Mail under "
                    "System Settings → Privacy & Security → Automation."
                )
            return "", f"Mail.app error: {err[:200]}"

        return proc.stdout or "", None

    return "", "Mail.app timed out."


def _parse_rows(stdout: str, *, cutoff: date) -> list[dict]:
    messages: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        received = _parse_mail_date(parts[2])
        if received and received < cutoff:
            continue
        entry = {
            "subject": parts[0].strip(),
            "sender": parts[1].strip(),
            "received": parts[2].strip(),
        }
        if len(parts) > 3:
            entry["body"] = _strip_html(parts[3])[:_BODY_MAX]
        messages.append(entry)
    return messages


def _macos_mail_messages(days: int, subject_contains: str = "") -> tuple[list[dict], Optional[str]]:
    if _OS != "Darwin":
        return [], "macOS Mail is only available on Mac."

    cutoff = date.today() - timedelta(days=days - 1)
    limit = _MAIL_SCAN_LIMIT if not subject_contains else 30

    if subject_contains:
        stdout, err = _run_osascript(_search_mail_script(limit, subject_contains.lower()))
    else:
        stdout, err = _run_osascript(_fast_mail_script(limit))

    if err:
        return [], err

    messages = _parse_rows(stdout, cutoff=cutoff)
    return messages, None


def _format_messages(messages: list[dict], days: int, *, read_ok: bool, subject_contains: str = "") -> str:
    if not read_ok:
        return f"I could not read your inbox for the last {days} days, sir."

    if not messages:
        if subject_contains:
            return f"No email found matching '{subject_contains}' in the last {days} days, sir."
        return f"No emails in your inbox from the last {days} days, sir."

    if subject_contains and messages[0].get("body"):
        msg = messages[0]
        return (
            f"Email: {msg.get('subject', 'No subject')}\n"
            f"From: {msg.get('sender', 'unknown')}\n"
            f"Received: {msg.get('received', '')}\n"
            f"Body: {msg['body']}"
        )

    lines = [f"Inbox — last {days} days ({len(messages)} messages):"]
    for msg in messages:
        lines.append(f"- {msg.get('subject', 'No subject')} — from {msg.get('sender', 'unknown')}")
    return "\n".join(lines)


def mail_inbox(parameters: dict | None = None, player=None, response=None) -> str:
    params = parameters or {}
    days = _days_back(params)
    subject_contains = (params.get("subject_contains") or params.get("query") or "").strip()
    open_browser = bool(params.get("open_browser", False))

    messages, err = _macos_mail_messages(days, subject_contains)
    read_ok = err is None

    if open_browser:
        import webbrowser
        try:
            webbrowser.open("https://mail.google.com/mail/u/0/#inbox")
        except Exception as exc:
            if err:
                err += f" | Could not open Gmail: {exc}"
            else:
                err = f"Could not open Gmail: {exc}"

    msg = _format_messages(messages, days, read_ok=read_ok, subject_contains=subject_contains)

    if not read_ok and err:
        msg += f" Details: {err}"

    _log(msg.split("\n")[0], player)
    return msg
