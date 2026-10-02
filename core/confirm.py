"""
core/confirm.py — a confirmation the model cannot forge.

THE PROBLEM WITH THE OLD GATE
    computer_settings guarded shutdown and restart like this:

        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return "Please confirm by calling again with confirmed=yes."

    `confirmed` is a tool parameter, which means the *model* writes it. Nothing
    stops it from sending confirmed=yes on the first call, and nothing checks
    that a human was ever involved. It is a convention, not a gate — and its
    coverage was two actions, so deleting files and switching off the WiFi the
    assistant is talking over went through with no gate at all.

THE DESIGN HERE
    The confirmation token is issued by the *interface*, never by the model:

      1. An action calls `request(...)` with a callable that does the real work.
      2. This module hands the UI a banner with CONFIRM / CANCEL and returns
         IMMEDIATELY with a sentence for the model to say out loud.
      3. If — and only if — the user presses CONFIRM, the UI calls `resolve()`,
         which runs the stored callable off the Qt thread.

    Nothing blocks. The model keeps talking while the banner is up, so this
    costs no latency at all; in fact it is cheaper than the old gate, which
    burned two tool round trips (reject, then re-call) on every shutdown.

WHAT BELONGS HERE AND WHAT DOES NOT
    Only genuinely irreversible things. Anything that can be reversed should be
    done at once and pushed onto core/undo.py instead — undo is faster than a
    question, and an assistant that asks before every action is one nobody uses.
"""

from __future__ import annotations

from contextvars import ContextVar
_trusted_action = ContextVar("trusted_ui_action", default=None)

import threading
import time
import secrets
import re
from dataclasses import dataclass
from typing import Callable, Optional

# A pending confirmation is abandoned after this long. Chosen to outlast a
# normal "hang on, let me look at the screen" pause without leaving a live
# shutdown button sitting on the HUD for the rest of the day.
TIMEOUT_SECONDS = 90.0


@dataclass
class _Pending:
    key:     str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float
    voice_code: str = ''


_pending: Optional[_Pending] = None
_lock = threading.Lock()
_executing = False

# Set once at startup by main.py. Signature: (title, detail) -> None for show,
# and () -> None for hide. Both are marshalled onto the Qt thread by the UI.
_show_cb: Optional[Callable[[str, str], None]] = None
_hide_cb: Optional[Callable[[], None]] = None
_log_cb:  Optional[Callable[[str], None]] = None


def bind(show, hide, log=None) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _hide_cb, _log_cb
    _show_cb, _hide_cb, _log_cb = show, hide, log


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            pass


def request(key: str, title: str, detail: str, run: Callable[[], str], *, voice_eligible=False) -> str:
    """Park an irreversible action behind the on-screen gate.

    Returns the sentence the tool should hand back to the model — phrased as an
    instruction so the assistant asks the user out loud in their own language,
    rather than reading an English string verbatim."""
    global _pending

    if _trusted_action.get() == key:
        return run()

    if _show_cb is None:
        # No interface bound (headless, or a very early call). Refuse rather
        # than silently performing something irreversible.
        return (f"I cannot confirm '{title}' right now because the interface is "
                f"not available, so I have not done it.")

    with _lock:
        if _executing:
            if threading.current_thread().name.startswith("confirm-") and _pending is None:
                _pending = _Pending(key=key, title=title, detail=detail, run=run, at=time.monotonic())
                return "[CONFIRMATION_PENDING] A further source-code review will appear when this action returns."
            return "An approved action is still running. Wait before requesting another confirmation."
        if _pending is not None and time.monotonic() - _pending.at <= TIMEOUT_SECONDS:
            return "[CONFIRMATION_PENDING] Answer the existing confirmation first. Nothing new was queued."
        code = str(secrets.randbelow(9000) + 1000) if voice_eligible else ''
        if code:
            detail += '\n\nVoice option: say Jarvis confirm ' + code + ', or Jarvis cancel ' + code + '.'
        _pending = _Pending(key=key, title=title, detail=detail,
                            run=run, at=time.monotonic(), voice_code=code)

    try:
        _show_cb(title, detail)
    except Exception as e:
        with _lock:
            _pending = None
        return f"Could not ask for confirmation: {e}. Nothing was done."

    _log(f"SYS: Awaiting confirmation — {title}")
    if code:
        return (f'[CONFIRMATION_PENDING] Explain the pending action briefly, then ask the user to say '
                f'Jarvis confirm {code}, reading the code digit by digit. They may say Jarvis cancel {code}. '
                'The local voice listener handles this; do not call tools to approve it or claim completion.')
    return (
        f"[CONFIRMATION_PENDING] I have put a confirmation on screen for: {title}. "
        f"Say ONE short sentence in the user's own language telling them you need "
        f"them to confirm it on the HUD before you do it. Do not claim it is done."
    )


def resolve(accepted: bool, *, expected_key=None, expected_code=None) -> None:
    """Called by the UI when the user presses CONFIRM or CANCEL.

    Runs the stored callable on a worker thread — this is invoked from the Qt
    thread, and shutting the machine down from inside a button handler would
    freeze the interface on its way out."""
    global _pending, _executing

    with _lock:
        if expected_key is not None and (_pending is None or _pending.key != expected_key or _pending.voice_code != expected_code):
            return
        p, _pending = _pending, None

    if _hide_cb:
        try:
            _hide_cb()
        except Exception:
            pass

    if p is None:
        return

    if time.monotonic() - p.at > TIMEOUT_SECONDS:
        _log(f"SYS: Confirmation expired — {p.title}")
        return

    from core.diagnostics import record
    record("confirmation_granted" if accepted else "confirmation_denied", status="accepted" if accepted else "denied")

    if not accepted:
        _log(f"SYS: Cancelled — {p.title}")
        return

    with _lock:
        _executing = True

    def _worker():
        global _executing
        try:
            result = p.run() or "Done."
            _log(f"SYS: Confirmed — {p.title}. {result}")
        except Exception as e:
            _log(f"ERR: {p.title} failed — {e}")

        finally:
            with _lock:
                _executing = False
                queued = _pending
                if queued:
                    queued.at = time.monotonic()
            if queued and _show_cb:
                try:
                    _show_cb(queued.title, queued.detail)
                except Exception:
                    _log("ERR: Could not display follow-up confirmation; no action executed.")

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def resolve_voice(text, *, local_session=False):
    """Only actual local input transcription calls this, never model/tool output."""
    if not local_session:
        return False
    from memory.config_manager import load_api_keys
    if not load_api_keys().get('voice_confirmation_enabled', False):
        return False
    normalized = re.sub(r'[^a-z0-9 ]', ' ', str(text).lower())
    words = {'zero':'0', 'one':'1', 'two':'2', 'three':'3', 'four':'4', 'five':'5',
             'six':'6', 'seven':'7', 'eight':'8', 'nine':'9'}
    normalized = ' '.join(words.get(w, w) for w in normalized.split())
    match = re.fullmatch(r'jarvis (confirm|cancel) ([0-9 ]+)', normalized)
    if not match:
        return False
    code = match[2].replace(' ', '')
    with _lock:
        pending = _pending
        if not pending or not pending.voice_code or pending.voice_code != code or time.monotonic() - pending.at > TIMEOUT_SECONDS:
            return False
        key = pending.key
    resolve(match[1] == 'confirm', expected_key=key, expected_code=code)
    return True


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            return ""
        return _pending.title
