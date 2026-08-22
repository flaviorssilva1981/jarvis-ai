"""
google_drive.py — Search and open Google Drive files in Chrome (no OAuth).

Uses the user's logged-in Chrome session + Drive web search.
Handles native Google Slides AND uploaded .pptx files (JARVIS local exports).
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote_plus

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"

_FILE_TYPE_FILTERS = {
    # Native Google Slides only — misses uploaded .pptx
    "presentation": "type:presentation",
    "slides": "type:presentation",
    # Uploaded PowerPoint from JARVIS or manual upload
    "pptx": "filename:pptx",
    "powerpoint": "filename:pptx",
    "document": "type:document",
    "spreadsheet": "type:spreadsheet",
    "pdf": "type:pdf",
    "any": "",
}


def _get_api_key() -> str:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))["gemini_api_key"]


def _focus_chrome() -> None:
    if platform.system() == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            check=False,
            timeout=5,
        )
    time.sleep(0.4)


def _open_chrome_url(url: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["open", "-a", "Google Chrome", url], check=False, timeout=20)
    elif platform.system() == "Windows":
        subprocess.run(f'start chrome "{url}"', shell=True, check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


def _chrome_active_url() -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        proc = subprocess.run(
            ["osascript", "-e",
             "tell application \"Google Chrome\" to get URL of active tab of front window"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _extract_drive_file_id(url: str) -> str:
    if not url:
        return ""
    for pattern in (
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
    ):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def _drive_file_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def _drive_search_url(query: str, file_type: str = "slides_or_pptx") -> str:
    ft = file_type.lower()
    if ft in ("slides_or_pptx", "presentation", "slides", "deck"):
        # JARVIS exports .pptx — include both native Slides and uploaded PowerPoint
        q = f"(type:presentation OR filename:pptx) {query}".strip()
    elif ft in ("pptx", "powerpoint"):
        q = f"filename:pptx {query}".strip()
    else:
        type_filter = _FILE_TYPE_FILTERS.get(ft, "")
        q = f"{type_filter} {query}".strip() if type_filter else query.strip()
    return f"https://drive.google.com/drive/search?q={quote_plus(q)}"


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_pptx_name(name: str) -> bool:
    lower = (name or "").lower()
    return lower.endswith(".pptx") or lower.endswith(".ppt")


def _list_results_from_screen(query: str) -> list[dict]:
    """Read visible file names from a Drive search results page."""
    try:
        from google import genai
        from google.genai import types as gtypes
        from actions.screen_processor import _capture_screen

        img_bytes, mime = _capture_screen()
        client = genai.Client(api_key=_get_api_key())
        prompt = (
            f"This is a Google Drive search results page for '{query}'. "
            'Reply ONLY with JSON: {"files": [{"name": "...", "format": "pptx|slides|other"}]}\n'
            "List file names visible in the results. "
            'format=pptx if the name ends with .pptx or shows a PowerPoint icon. '
            'format=slides for native Google Slides. '
            'Use {"files": []} if no results or page not loaded.'
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                gtypes.Part.from_bytes(data=img_bytes, mime_type=mime),
                prompt,
            ],
        )
        data = json.loads(_strip_json_fences(resp.text or "{}"))
        files = data.get("files") or []
        out: list[dict] = []
        for item in files:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            fmt = str(item.get("format") or "")
            if not fmt:
                fmt = "pptx" if _is_pptx_name(name) else "slides"
            out.append({"name": name, "format": fmt})
        return out
    except Exception as e:
        print(f"[GoogleDrive] Vision list failed: {e}")
        return []


def _page_shows_open_error() -> bool:
    """Detect Google Slides 'Could not open file' error page."""
    try:
        from google import genai
        from google.genai import types as gtypes
        from actions.screen_processor import _capture_screen

        img_bytes, mime = _capture_screen()
        client = genai.Client(api_key=_get_api_key())
        prompt = (
            "Does this screenshot show a Google Slides or Drive error like "
            "'Could not open file' or a blank failed load? "
            "Reply ONLY: yes or no"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                gtypes.Part.from_bytes(data=img_bytes, mime_type=mime),
                prompt,
            ],
        )
        return "yes" in (resp.text or "").lower()
    except Exception:
        return False


def _pick_best_match(query: str, files: list[dict]) -> dict:
    if not files:
        return {"name": query, "format": "pptx" if _is_pptx_name(query) else "slides"}
    q = query.lower()
    for item in files:
        name = str(item.get("name", ""))
        if name.lower() == q:
            return item
    for item in files:
        name = str(item.get("name", ""))
        if q in name.lower() or name.lower() in q:
            return item
    return files[0]


def _open_pptx_with_google_slides(name: str) -> str:
    """Select uploaded .pptx in Drive and open with Google Slides (converts to native format)."""
    from actions.computer_control import computer_control

    _focus_chrome()
    steps: list[str] = []

    click_targets = [
        f'PowerPoint .pptx file named "{name}" in Google Drive search results row',
        f'file named "{name}" with PowerPoint icon in Google Drive list',
        f'file row named "{name}" in Google Drive search results',
    ]
    clicked = False
    for desc in click_targets:
        result = computer_control({"action": "screen_click", "description": desc})
        steps.append(result)
        if "not found" not in result.lower():
            clicked = True
            break
        time.sleep(0.5)

    if not clicked:
        return " | ".join(steps)

    time.sleep(0.6)

    open_with_targets = [
        "Open with button in Google Drive toolbar above file list",
        "Open with link at the top of Google Drive when a file is selected",
        f"three dots more actions menu for selected file in Google Drive",
    ]
    for desc in open_with_targets:
        result = computer_control({"action": "screen_click", "description": desc})
        steps.append(result)
        if "not found" not in result.lower():
            break
        time.sleep(0.4)

    time.sleep(0.5)
    slides = computer_control({
        "action": "screen_click",
        "description": "Google Slides option in Open with menu in Google Drive",
    })
    steps.append(slides)
    return " | ".join(steps)


def _open_drive_file(name: str, query: str, file_format: str = "slides") -> str:
    """Open a file from Drive search results."""
    from actions.computer_control import computer_control

    if file_format == "pptx" or _is_pptx_name(name):
        return _open_pptx_with_google_slides(name)

    _focus_chrome()
    steps: list[str] = []
    click_targets = [
        f'Google Slides file named "{name}" in Google Drive search results',
        f'file named "{name}" in Google Drive search results list',
        f'first presentation file in Google Drive search results for {query}',
    ]
    clicked = False
    for desc in click_targets:
        result = computer_control({"action": "screen_click", "description": desc})
        steps.append(result)
        if "not found" not in result.lower():
            clicked = True
            break
        time.sleep(0.5)

    if clicked:
        time.sleep(0.4)
        steps.append(computer_control({"action": "press", "key": "enter"}))

    return " | ".join(steps)


def _recover_broken_presentation_url(url: str) -> tuple[str, str]:
    """
    Fix docs.google.com/presentation/.../edit?rtpof=true errors for uploaded .pptx.
    Opens Drive file preview and tries Open with Google Slides.
    """
    file_id = _extract_drive_file_id(url)
    if not file_id:
        return url, "No file ID in URL"

    view_url = _drive_file_view_url(file_id)
    _open_chrome_url(view_url)
    time.sleep(5)
    _focus_chrome()

    from actions.computer_control import computer_control

    steps: list[str] = [f"Opened Drive preview: {view_url}"]
    for desc in (
        "Open with Google Slides button in Google Drive file preview",
        "Open with button at top of Google Drive file preview page",
        "Google Slides in Open with dropdown on Drive file preview",
    ):
        result = computer_control({"action": "screen_click", "description": desc})
        steps.append(result)
        if "not found" not in result.lower():
            break
        time.sleep(0.5)

    time.sleep(6)
    active = _chrome_active_url()
    return active or view_url, " | ".join(steps)


def _is_open_success(url: str) -> bool:
    if not url:
        return False
    if "drive.google.com/file/d/" in url:
        return True
    if "docs.google.com/presentation" in url and "rtpof=true" not in url:
        return True
    return False


def _is_native_slides_url(url: str) -> bool:
    return (
        "docs.google.com/presentation" in (url or "")
        and "rtpof=true" not in (url or "")
    )


def google_drive_files(
    parameters: dict | None = None,
    player=None,
) -> str:
    """
    Actions:
      search   — open Drive search and list matching files (vision)
      open     — search Drive and open the best match (.pptx or native Slides)
      open_url — open a known URL; fixes broken rtpof=true .pptx links
    """
    params = parameters or {}
    action = (params.get("action") or "open").lower().strip()
    query = (
        params.get("query")
        or params.get("name")
        or params.get("title")
        or params.get("search")
        or ""
    ).strip()
    file_type = (params.get("file_type") or params.get("type") or "slides_or_pptx").lower()
    load_wait = float(params.get("load_wait") or 8.0)
    url = (params.get("url") or "").strip()
    local_path = (params.get("local_path") or params.get("path") or "").strip()

    if action in ("open_local", "open_pptx") and local_path:
        path = Path(local_path).expanduser()
        if not path.exists():
            return f"Local file not found: {path}"
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Windows":
            subprocess.run(["start", "", str(path)], shell=True, check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return (
            f"[DRIVE_OPEN: ok]\n"
            f"Opened local presentation: {path}\n"
            "To present locally, use google_slides_present with pptx_path set to this file."
        )

    if action in ("open_url", "goto", "recover") and url:
        # Broken Office-mode URL for uploaded .pptx → recover via Drive preview
        if "rtpof=true" in url or action == "recover":
            active, recovery = _recover_broken_presentation_url(url)
            if _is_native_slides_url(active):
                msg = (
                    f"[DRIVE_OPEN: ok]\n"
                    f"Converted and opened presentation in Google Slides.\n"
                    f"URL: {active}\n"
                    f"Recovery: {recovery}"
                )
            elif "drive.google.com/file" in active and not _page_shows_open_error():
                msg = (
                    f"[DRIVE_OPEN: ok]\n"
                    f"Opened file preview in Google Drive.\n"
                    f"URL: {active}\n"
                    f"Recovery: {recovery}\n"
                    "If not in Slides yet, click Open with → Google Slides in Chrome."
                )
            else:
                file_id = _extract_drive_file_id(url)
                msg = (
                    f"[DRIVE_OPEN: partial]\n"
                    f"Could not convert uploaded .pptx automatically.\n"
                    f"File ID: {file_id or 'unknown'}\n"
                    f"Try manually: Drive → select file → Open with → Google Slides\n"
                    f"Or open local copy from ~/Documents/JARVIS Presentations/\n"
                    f"Recovery: {recovery}"
                )
            if player and hasattr(player, "write_log"):
                player.write_log(f"[drive] recover {url[:50]}")
            return msg

        _open_chrome_url(url)
        time.sleep(4)
        _focus_chrome()
        active = _chrome_active_url() or url

        if _page_shows_open_error() or "rtpof=true" in active:
            active, recovery = _recover_broken_presentation_url(active or url)
            if _is_native_slides_url(active):
                return (
                    f"[DRIVE_OPEN: ok]\n"
                    f"Recovered and opened in Google Slides.\n"
                    f"URL: {active}\n"
                    f"Recovery: {recovery}"
                )
            return (
                f"[DRIVE_OPEN: partial]\n"
                f"File failed to open in Slides editor.\n"
                f"URL: {active}\n"
                f"Recovery: {recovery}\n"
                "Uploaded .pptx files must be opened with Google Slides (converts to native format)."
            )

        if player and hasattr(player, "write_log"):
            player.write_log(f"[drive] opened {active[:60]}")
        return f"[DRIVE_OPEN: ok]\nOpened in Chrome.\nURL: {active}"

    if not query:
        return "Provide a file name or search query (e.g. 'Presentation' or 'Jarvis AI')."

    search_url = _drive_search_url(query, file_type)

    if action == "search":
        _open_chrome_url(search_url)
        time.sleep(load_wait)
        _focus_chrome()
        files = _list_results_from_screen(query)
        if player and hasattr(player, "write_log"):
            player.write_log(f"[drive] search '{query}' → {len(files)} result(s)")

        if not files:
            return (
                f"[DRIVE_SEARCH: empty]\n"
                f"No files found for '{query}' (or Drive still loading).\n"
                f"Search URL: {search_url}\n"
                "Searches both native Google Slides and uploaded .pptx files."
            )

        lines = [
            "[DRIVE_SEARCH: ok]",
            f"Found {len(files)} file(s) matching '{query}':",
            f"Search URL: {search_url}",
        ]
        for i, item in enumerate(files[:10], 1):
            fmt = item.get("format", "file")
            hint = " (uploaded PowerPoint — opens via Open with Google Slides)" if fmt == "pptx" else ""
            lines.append(f"{i}. {item.get('name', '?')}{hint}")
        lines.append("Use action=open with the exact file name to open it.")
        return "\n".join(lines)

    if action in ("open", "find", "find_and_open"):
        _open_chrome_url(search_url)
        time.sleep(load_wait)
        _focus_chrome()

        files = _list_results_from_screen(query)
        target_item = _pick_best_match(query, files)
        target = str(target_item.get("name", query))
        fmt = str(target_item.get("format", "pptx" if _is_pptx_name(target) else "slides"))

        click_result = _open_drive_file(target, query, file_format=fmt)
        time.sleep(6 if fmt == "pptx" else 5)
        _focus_chrome()
        active = _chrome_active_url()

        if _page_shows_open_error() or ("rtpof=true" in active and fmt == "pptx"):
            active, recovery = _recover_broken_presentation_url(active or "")
            click_result += f" | recovery: {recovery}"

        if _is_native_slides_url(active):
            msg = (
                f"[DRIVE_OPEN: ok]\n"
                f"Opened presentation '{target}' in Google Slides.\n"
                f"URL: {active}"
            )
            if player and hasattr(player, "write_log"):
                player.write_log(f"[drive] opened slides {target}")
            if player and hasattr(player, "show_content"):
                player.show_content(f"DRIVE — {target}", active)
            return msg

        if "drive.google.com/file/d/" in (active or "") and not _page_shows_open_error():
            return (
                f"[DRIVE_OPEN: ok]\n"
                f"Opened '{target}' in Google Drive preview.\n"
                f"URL: {active}\n"
                "Click Open with → Google Slides to edit and present."
            )

        # Retry double-click for native slides only
        if fmt != "pptx":
            try:
                from actions.computer_control import computer_control, _screen_find  # noqa: SLF001

                coords = _screen_find(f'file named "{target}" in Google Drive search results')
                if coords:
                    computer_control({"action": "double_click", "x": coords[0], "y": coords[1]})
                    time.sleep(4)
                    active = _chrome_active_url()
                    if _page_shows_open_error():
                        active, _ = _recover_broken_presentation_url(active or "")
            except Exception:
                pass

        if _is_open_success(active or ""):
            return (
                f"[DRIVE_OPEN: ok]\n"
                f"Opened '{target}' in Chrome.\n"
                f"URL: {active}"
            )

        local_hint = ""
        jarvis_dir = Path.home() / "Documents" / "JARVIS Presentations"
        if jarvis_dir.exists():
            matches = list(jarvis_dir.glob(f"*{query.replace(' ', '*')}*.pptx"))
            if not matches:
                matches = sorted(jarvis_dir.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
            if matches:
                local_hint = (
                    "Local copies found:\n"
                    + "\n".join(f"  • {p}" for p in matches[:3])
                    + "\nSay 'open local presentation' or use action=open_local with local_path."
                )

        if player and hasattr(player, "write_log"):
            player.write_log(f"[drive] partial open for '{target}'")

        return (
            f"[DRIVE_OPEN: partial]\n"
            f"Could not fully open '{target}' in Google Slides.\n"
            f"Search URL: {search_url}\n"
            f"File type: {fmt} (.pptx uploads need Open with → Google Slides)\n"
            f"Active URL: {active or '(unknown)'}\n"
            f"Automation: {click_result}\n"
            + (f"{local_hint}\n" if local_hint else "")
            + "DO NOT claim success unless URL is a working Google Slides or Drive preview link."
        )

    return f"Unknown action '{action}'. Use: search | open | open_url | recover | open_local"
