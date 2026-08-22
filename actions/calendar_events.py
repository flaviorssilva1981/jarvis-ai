from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

_OS = platform.system()

_SKIP_CALENDAR_NAMES = frozenset({
    "holidays in brazil",
    "feriados",
    "siri suggestions",
    "scheduled reminders",
    "birthdays",
    "holidays",
})

_CALENDAR_QUERY_TIMEOUT = 90
_DEFAULT_CALENDARS = ("Calendar",)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_CONFIG_PATH = _base_dir() / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _log(msg: str, player=None) -> None:
    print(f"[Calendar] {msg}")
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def _resolve_target_date(parameters: dict) -> date:
    when = (parameters.get("when") or parameters.get("date") or "today").strip().lower()
    today = date.today()

    if when in ("today", "bugün", "hoy"):
        return today
    if when in ("tomorrow", "yarın", "mañana"):
        return today + timedelta(days=1)

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(when, fmt).date()
        except ValueError:
            continue

    return today


def _google_calendar_day_url(target: date) -> str:
    return f"https://calendar.google.com/calendar/r/day/{target.year}/{target.month}/{target.day}"


def _format_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")


def _format_events(events: list[dict], target: date, *, read_ok: bool) -> str:
    label = target.strftime("%A, %B %d, %Y")
    if not read_ok:
        return f"I could not read your calendar for {label}, sir."

    if not events:
        return f"You have no events scheduled for {label}, sir."

    lines = [f"Agenda for {label}:"]
    for evt in events:
        title = evt.get("title") or "Untitled event"
        start = evt.get("start")
        end = evt.get("end")
        cal = evt.get("calendar")
        all_day = evt.get("all_day", False)

        if all_day:
            time_part = "All day"
        elif isinstance(start, datetime):
            time_part = _format_time(start)
            if isinstance(end, datetime) and end.date() == start.date() and end > start:
                time_part += f" – {_format_time(end)}"
        else:
            time_part = str(start or "")

        suffix = f" ({cal})" if cal else ""
        lines.append(f"- {time_part}: {title}{suffix}")

    return "\n".join(lines)


def _ensure_calendar_running() -> None:
    """Calendar.app must be running for AppleScript; launch if needed."""
    try:
        subprocess.run(
            ["open", "-a", "Calendar"],
            capture_output=True,
            timeout=10,
        )
        time.sleep(2.5)
    except Exception as exc:
        print(f"[Calendar] ⚠️ Could not launch Calendar.app: {exc}")


def _list_macos_calendars() -> list[str]:
    _ensure_calendar_running()
    script = 'tell application "Calendar" to get name of every calendar'
    for attempt in (1, 2):
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            print(f"[Calendar] ⚠️ List calendars timeout (attempt {attempt})")
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return [n.strip() for n in proc.stdout.split(", ") if n.strip()]
        err = (proc.stderr or proc.stdout or "").strip()
        if err:
            print(f"[Calendar] ⚠️ List calendars failed: {err[:120]}")
    return []


def _calendar_query_order() -> list[str]:
    cfg = _load_config()
    configured = cfg.get("calendar_names") or cfg.get("calendar_name") or []
    if isinstance(configured, str):
        configured = [configured]

    all_cals = _list_macos_calendars()
    if not all_cals:
        all_cals = list(_DEFAULT_CALENDARS)

    ordered: list[str] = []
    seen: set[str] = set()

    for name in [*configured, *all_cals]:
        if not name or name in seen:
            continue
        seen.add(name)
        if name.lower() in _SKIP_CALENDAR_NAMES:
            continue
        ordered.append(name)

    def _priority(name: str) -> tuple[int, str]:
        lower = name.lower()
        if "@" in name:
            return (0, lower)
        if lower == "calendar":
            return (1, lower)
        return (2, lower)

    ordered.sort(key=_priority)
    return ordered


def _macos_calendar_events(target: date) -> tuple[list[dict], Optional[str]]:
    if _OS != "Darwin":
        return [], "macOS Calendar is only available on Mac."

    cal_names = _calendar_query_order()
    if not cal_names:
        return [], "No calendars found in Calendar.app."

    all_events: list[dict] = []
    last_err: Optional[str] = None

    for cal_name in cal_names[:3]:
        print(f"[Calendar] Querying '{cal_name}'...")
        events, err = _macos_calendar_events_for_name(target, cal_name)
        if events:
            all_events.extend(events)
        if err:
            last_err = err
            if "timed out" in err.lower() or "connection is invalid" in err.lower():
                if all_events:
                    break
                continue

    if all_events:
        all_events.sort(key=lambda e: (e.get("all_day", False), e.get("start") or datetime.min))
        return all_events, None

    return [], last_err


def _macos_calendar_events_for_name(target: date, cal_name: str) -> tuple[list[dict], Optional[str]]:
    _ensure_calendar_running()
    y, m, d = target.year, target.month, target.day
    safe_name = cal_name.replace('"', "")
    script = f'''
set targetDate to current date
set year of targetDate to {y}
set month of targetDate to {m}
set day of targetDate to {d}
set time of targetDate to 0
set dayEnd to targetDate + (1 * days)
set output to ""
tell application "Calendar"
    set cal to calendar "{safe_name}"
    set evts to every event of cal whose start date ≥ targetDate and start date < dayEnd
    repeat with evt in evts
        set s to start date of evt
        set e to end date of evt
        set output to output & (summary of evt) & (ASCII character 9) & (time string of s) & (ASCII character 9) & (time string of e) & (ASCII character 9) & (allday event of evt) & (ASCII character 9) & "{safe_name}" & linefeed
    end repeat
end tell
return output
'''
    for attempt in (1, 2):
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=_CALENDAR_QUERY_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            if attempt == 1:
                print(f"[Calendar] ⚠️ Timeout on '{cal_name}' — retrying…")
                continue
            return [], f"Calendar access timed out while reading '{cal_name}'."
        except Exception as exc:
            return [], f"Could not read Calendar.app calendar '{cal_name}': {exc}"

        if proc.returncode == 0:
            return _parse_macos_output(proc.stdout or "", target), None

        err = (proc.stderr or proc.stdout or "unknown error").strip()
        if "Not authorized" in err or "1743" in err:
            return [], (
                "Calendar permission denied. Open System Settings → Privacy & Security → "
                "Calendars and allow access for Terminal (or the app running JARVIS)."
            )
        if "-1728" in err or "Can't get calendar" in err:
            return [], None
        if "connection is invalid" in err.lower() or "isn't running" in err.lower() or "(-600)" in err:
            if attempt == 1:
                print(f"[Calendar] ⚠️ Calendar not ready on '{cal_name}' — retrying…")
                _ensure_calendar_running()
                time.sleep(1)
                continue
        return [], f"Calendar.app error: {err[:200]}"

    return [], f"Calendar.app error: could not read '{cal_name}'."


def _parse_macos_output(stdout: str, target: date | None = None) -> list[dict]:
    events: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        title, start_raw, end_raw, all_day_raw = parts[:4]
        cal_name = parts[4] if len(parts) > 4 else ""

        all_day = all_day_raw.strip().lower() == "true"
        start_dt = _parse_apple_time(start_raw, target)
        end_dt = _parse_apple_time(end_raw, target)

        events.append({
            "title": title.strip(),
            "start": start_dt,
            "end": end_dt,
            "all_day": all_day,
            "calendar": cal_name.strip(),
        })

    events.sort(key=lambda e: (e.get("all_day", False), e.get("start") or datetime.min))
    return events


def _parse_apple_time(raw: str, target: date | None) -> Optional[datetime]:
    raw = raw.strip()
    if not raw or not target:
        return _parse_apple_iso(raw)
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        s = int(m.group(3) or 0)
        return datetime(target.year, target.month, target.day, h, mi, s)
    return _parse_apple_iso(raw)


def _parse_apple_iso(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if not raw:
        return None
    m = re.match(
        r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})$",
        raw,
    )
    if m:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")[:19])
    except ValueError:
        return None


def _fetch_ical_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "JARVIS-Calendar/1.0"})
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _unwrap_ical_line(line: str) -> str:
    return line.strip()


def _parse_ical_datetime(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d")
    if "T" in raw:
        clean = raw.replace("Z", "")
        if len(clean) >= 15:
            return datetime.strptime(clean[:15], "%Y%m%dT%H%M%S")
    return None


def _ical_events_for_date(ics_text: str, target: date) -> list[dict]:
    events: list[dict] = []
    blocks = ics_text.split("BEGIN:VEVENT")
    for block in blocks[1:]:
        if "END:VEVENT" not in block:
            continue

        fields: dict[str, str] = {}
        current_key = ""
        for line in block.splitlines():
            line = _unwrap_ical_line(line)
            if not line or line.startswith("END:VEVENT"):
                continue
            if line.startswith(" "):
                if current_key:
                    fields[current_key] += line[1:]
                continue
            if ":" not in line:
                continue
            key_part, value = line.split(":", 1)
            current_key = key_part.split(";")[0].upper()
            fields[current_key] = value

        summary = fields.get("SUMMARY", "Untitled event")
        dtstart_raw = fields.get("DTSTART", "")
        dtend_raw = fields.get("DTEND", "")
        all_day = "T" not in dtstart_raw and re.fullmatch(r"\d{8}", dtstart_raw.strip())

        start_dt = _parse_ical_datetime(dtstart_raw)
        end_dt = _parse_ical_datetime(dtend_raw)
        if not start_dt:
            continue

        event_date = start_dt.date() if isinstance(start_dt, datetime) else start_dt
        if hasattr(event_date, "year") and event_date != target:
            continue

        events.append({
            "title": summary,
            "start": start_dt,
            "end": end_dt,
            "all_day": all_day,
            "calendar": "Google Calendar",
        })

    events.sort(key=lambda e: (e.get("all_day", False), e.get("start") or datetime.min))
    return events


def _ical_calendar_events(target: date) -> tuple[list[dict], Optional[str]]:
    url = (_load_config().get("google_calendar_ical_url") or "").strip()
    if not url:
        return [], None
    try:
        ics = _fetch_ical_text(url)
    except URLError as exc:
        return [], f"Could not fetch Google Calendar iCal feed: {exc.reason}"
    except Exception as exc:
        return [], f"Could not fetch Google Calendar iCal feed: {exc}"

    return _ical_events_for_date(ics, target), None


def calendar_events(parameters: dict | None = None, player=None, response=None) -> str:
    params = parameters or {}
    target = _resolve_target_date(params)
    open_browser = bool(params.get("open_browser", False))

    events: list[dict] = []
    errors: list[str] = []
    read_ok = False

    mac_events, mac_err = _macos_calendar_events(target)
    if mac_err is None:
        read_ok = True
        events = mac_events
    elif mac_events:
        read_ok = True
        events = mac_events
    elif mac_err:
        errors.append(mac_err)

    if not read_ok:
        ical_events, ical_err = _ical_calendar_events(target)
        if ical_err is None and _load_config().get("google_calendar_ical_url"):
            read_ok = True
            events = ical_events
        elif ical_err:
            errors.append(ical_err)

    if open_browser:
        try:
            webbrowser.open(_google_calendar_day_url(target))
        except Exception as exc:
            errors.append(f"Could not open Google Calendar in browser: {exc}")

    msg = _format_events(events, target, read_ok=read_ok)

    if not read_ok:
        setup = (
            " To fix this: (1) Sync Google Calendar to the macOS Calendar app and grant "
            "Calendar permission to Terminal under System Settings → Privacy & Security; "
            "or (2) Add your private Google Calendar iCal URL to config/api_keys.json as "
            "'google_calendar_ical_url' (Google Calendar → Settings → Integrate calendar "
            "→ Secret address in iCal format). Do not guess events from the screen."
        )
        msg = msg + setup
        if errors:
            msg += " Details: " + " | ".join(errors[:2])

    _log(msg.split("\n")[0], player)
    return msg
