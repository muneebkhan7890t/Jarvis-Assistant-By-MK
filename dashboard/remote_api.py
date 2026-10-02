"""Signed, device-scoped companion routes integrated with the existing PC registry."""
import asyncio
import base64
import io
import secrets
from pathlib import Path
import time

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from memory.config_manager import load_api_keys
from core.remote_store import remote_store


def scoped_path(roots, index, relative=""):
    if type(index) is not int or not 0 <= index < len(roots) or not isinstance(relative, str):
        raise ValueError("Unknown shared folder")
    root = Path(roots[index]).resolve(strict=True)
    part = Path(relative)
    if not root.is_dir() or part.is_absolute() or part.drive or ":" in relative or ".." in part.parts:
        raise PermissionError("Path is outside the shared folder")
    candidate = root / part
    for piece in (candidate, *candidate.parents):
        if piece == root:
            break
        if piece.is_symlink() or (hasattr(piece, "is_junction") and piece.is_junction()):
            raise PermissionError("Links are not shared")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(root):
        raise PermissionError("Path is outside the shared folder")
    denied = {".git", ".ssh", ".aws", "certs", "__pycache__", ".venv", ".venv-liv"}
    parts = [p.lower() for p in path.relative_to(root).parts]
    if any(p in denied or p.startswith(".env") for p in parts) or path.suffix.lower() in {".key", ".pem", ".pfx", ".db", ".sqlite", ".sqlite3"}:
        raise PermissionError("Sensitive application state is not shared")
    if any(word in path.name.lower() for word in ("api_keys", "credential", "token", "client_secret")):
        raise PermissionError("Credential files are not shared")
    return path


def register(app, server):
    tasks = set()
    store = None
    voice_tickets = {}
    voice_active = False
    server.remote_live_device = None
    project_runner = None
    workflow_runner = None
    push_manager = None
    audio_tickets = {}
    audio_listener = None

    def push():
        nonlocal push_manager
        if push_manager is None:
            from core.remote_push import RemotePush
            push_manager = RemotePush(storage(), load_api_keys)
        return push_manager

    async def push_loop():
        while True:
            try:
                if load_api_keys().get('remote_control_enabled'):
                    await asyncio.to_thread(push().tick)
            except Exception:
                # Keep saved receipts available even if push transport/storage fails.
                pass
            await asyncio.sleep(10)

    async def start_push():
        task = asyncio.create_task(push_loop())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server._startup_callbacks.append(start_push)

    def publish_audio(data):
        # Called on the assistant event loop; bounded, never delays PC playback.
        if audio_listener is None:
            return
        device_id, queue = audio_listener
        try:
            allowed(device_id, 'voice')
            allowed(device_id, 'chat')
            if server.remote_live_device != device_id:
                return
            if data is None:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
            else:
                for offset in range(0, len(data), 2400):
                    queue.put_nowait(data[offset:offset + 2400])
        except (PermissionError, asyncio.QueueFull):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait('stop')

    server.remote_publish_audio = publish_audio

    def storage():
        nonlocal store
        if store is None:
            store = remote_store()
            store.recover()
        return store

    def enabled():
        if not load_api_keys().get("remote_control_enabled", False):
            raise PermissionError("Remote access is disabled on the PC")

    def allowed(device_id, capability):
        enabled()
        device = storage().device(device_id)
        if not device or not device["trusted"] or capability not in device["capabilities"]:
            raise PermissionError("This device does not have this permission")
        if not load_api_keys().get("remote_features", {}).get(capability, False):
            raise PermissionError(f"Enable {capability} in the PC Remote Devices page")

    server.remote_validate = allowed

    def projects_runner():
        nonlocal project_runner
        if project_runner is None:
            from core.remote_projects import ProjectRunner
            project_runner = ProjectRunner(storage(), allowed)
        return project_runner

    async def stop_project_workers():
        if workflow_runner:
            workflow_runner.shutdown()
        if project_runner:
            await asyncio.to_thread(project_runner.shutdown)
        pending = list(tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    server._shutdown_callbacks.append(stop_project_workers)

    def workflows_runner():
        nonlocal workflow_runner
        if workflow_runner is None:
            from core.remote_workflows import RemoteWorkflows
            workflow_runner = RemoteWorkflows(storage(), allowed, lambda name, args: server.remote_dispatch(name, args))
        return workflow_runner

    def claim_live(device_id):
        # Gemini Live is a shared conversation, not a per-device isolated session.
        # Pin its remote owner until app restart to prevent cross-device privilege mixing.
        if server.remote_live_device not in (None, device_id):
            raise PermissionError("Another device owns the shared assistant session. Restart the PC assistant to change its remote owner.")
        server.remote_live_device = device_id

    def remote_tool(name, args):
        from core.permission_manager import policy_for, Risk, manager
        capability = "computer" if name in ("system_status", "computer_context") else "commands"
        allowed(server.remote_live_device, capability)
        if policy_for(name, args).risk != Risk.LOW or manager.decision(name, args)[1] != "allow":
            raise PermissionError("Remote assistant tools are limited to explicitly allowed low-risk commands. Use the dedicated Files or Screen page; sensitive actions require the PC.")
        return server.remote_dispatch(name, args)

    server.remote_tool_dispatch = remote_tool

    def automation_engine(device_id):
        allowed(device_id, "automations")
        from core.permission_manager import manager
        if manager.settings().get("monitoring") == "Deny":
            raise PermissionError("Automation control is denied in PC permissions")
        from core.automation import automations
        return automations

    async def execute_automation(command_id, device_id, ident, revision):
        try:
            engine = automation_engine(device_id)
            storage().update(command_id, "running", {"message": "Running saved automation"})
            def dispatch(name, args):
                automation_engine(device_id)
                if name == "notify":
                    if engine.dispatch is None:
                        raise RuntimeError("PC notification handler is unavailable")
                    return engine.dispatch(name, args)
                from core.permission_manager import manager, policy_for, Risk
                if policy_for(name, args).risk != Risk.LOW or manager.decision(name, args)[1] != "allow":
                    raise PermissionError("PC permissions do not allow this automation action")
                return server.remote_dispatch(name, args)
            result = await asyncio.to_thread(engine.run_now, ident, revision, dispatch_override=dispatch, source="phone")
            status = result["status"] if result["status"] in ("returned", "confirmation_requested") else "failed"
            storage().update(command_id, status, {"message": result.get("error") or result.get("result") or result["status"], "verified": False})
        except asyncio.CancelledError:
            storage().update(command_id, "failed", {"message": "Service stopped; automation outcome is unknown. Inspect before resending."})
            raise
        except Exception as exc:
            storage().update(command_id, "failed", {"message": str(exc)[:1000]})

    def invoke(device_id, payload):
        allowed(device_id, "commands")
        from core.intent_router import route
        from core.permission_manager import policy_for, Risk, manager
        text = payload.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError("Enter a command of 1–2000 characters")
        intent = route(text)
        if intent is None or policy_for(intent.name, intent.parameters).risk != Risk.LOW:
            raise ValueError("This command is not supported by the local remote controller. Use the dedicated pages or PC assistant.")
        if manager.decision(intent.name, intent.parameters)[1] != "allow":
            raise PermissionError("The PC permission settings do not allow automatic execution of this command")
        dispatch = getattr(server, "remote_dispatch", None)
        if dispatch is None:
            raise RuntimeError("PC action registry is not ready")
        return dispatch(intent.name, intent.parameters)

    async def execute(command_id, device_id, payload):
        try:
            storage().update(command_id, "running")
            result = await asyncio.to_thread(invoke, device_id, payload)
            result = str(result)[:16000]
            status = "confirmation_requested" if "[CONFIRMATION_PENDING]" in result else "returned"
            if result.startswith(("Permission denied", "Skill ", "Action '", "Tool '")):
                status = "failed"
            # Legacy action strings are receipts, not independent proof of success.
            storage().update(command_id, status, {"message": result, "verified": False})
        except asyncio.CancelledError:
            storage().update(command_id, "failed", {"message": "Service stopped; outcome unknown. Inspect before resending."})
            raise
        except Exception as exc:
            storage().update(command_id, "failed", {"message": str(exc)[:500]})

    @app.get("/remote", response_class=HTMLResponse)
    async def remote_page():
        return HTMLResponse((Path(__file__).parent / "static" / "remote.html").read_text(encoding="utf-8"))

    @app.get("/static/remote-audio.js")
    async def audio_processor():
        return FileResponse(Path(__file__).parent / "static" / "remote-audio.js", media_type="application/javascript")

    @app.get('/remote-sw.js')
    async def service_worker():
        return FileResponse(Path(__file__).parent / 'static' / 'remote-sw.js',
                            media_type='application/javascript', headers={'Cache-Control': 'no-cache'})

    @app.get('/static/remote-companion.js')
    async def companion_script():
        return FileResponse(Path(__file__).parent / 'static' / 'remote-companion.js', media_type='application/javascript')

    @app.get('/remote-manifest.json')
    async def manifest():
        return JSONResponse({'name': 'MARK LIV Remote', 'short_name': 'MARK LIV',
            'id': '/remote', 'start_url': '/remote', 'scope': '/', 'display': 'standalone',
            'background_color': '#0b1220', 'theme_color': '#101827'})

    @app.websocket('/remote-listen')
    async def listen(websocket: WebSocket, ticket: str = ''):
        nonlocal audio_listener
        from core.remote_security import same_origin
        identity = audio_tickets.pop(ticket, None)
        if not identity or identity[1] <= time.time() or audio_listener is not None or not same_origin(websocket.headers.get('origin'), websocket.headers.get('host', '')):
            await websocket.close(code=4003)
            return
        device_id = identity[0]
        try:
            allowed(device_id, 'voice')
            allowed(device_id, 'chat')
            claim_live(device_id)
        except PermissionError:
            await websocket.close(code=4003)
            return
        queue = asyncio.Queue(maxsize=40)
        audio_listener = (device_id, queue)
        await websocket.accept()
        notice = getattr(server, 'remote_notice', lambda text: None)
        notice('Phone speaker connected to the shared assistant audio.')
        disconnected = asyncio.create_task(websocket.receive())
        started = time.monotonic()
        try:
            while time.monotonic() - started < 900 and not disconnected.done():
                allowed(device_id, 'voice')
                allowed(device_id, 'chat')
                if not server._session_ready():
                    break
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=.5)
                except asyncio.TimeoutError:
                    continue
                allowed(device_id, 'voice')
                allowed(device_id, 'chat')
                if frame == 'stop':
                    break
                if frame is None:
                    await asyncio.wait_for(websocket.send_json({'type': 'clear'}), timeout=1)
                else:
                    await asyncio.wait_for(websocket.send_bytes(frame), timeout=1)
        except (PermissionError, WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            audio_listener = None
            disconnected.cancel()
            await asyncio.gather(disconnected, return_exceptions=True)
            notice('Phone speaker disconnected.')
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    @app.websocket("/remote-voice")
    async def voice(websocket: WebSocket, ticket: str = ""):
        nonlocal voice_active
        from core.remote_security import same_origin
        identity = voice_tickets.pop(ticket, None)
        if not identity or identity[1] <= time.time() or voice_active or not same_origin(websocket.headers.get("origin"), websocket.headers.get("host", "")):
            await websocket.close(code=4003)
            return
        device_id = identity[0]
        try:
            allowed(device_id, "voice")
            claim_live(device_id)
        except PermissionError:
            await websocket.close(code=4003)
            return
        voice_active = True
        notice = getattr(server, "remote_notice", lambda text: None)
        started, frames = time.monotonic(), 0
        window = started
        await websocket.accept()
        notice("Phone microphone connected; audio will be sent to the cloud assistant.")
        if server._wake_callback:
            server._wake_callback()
        try:
            while time.monotonic() - started < 900:
                allowed(device_id, "voice")
                if not server._session_ready():
                    break
                try:
                    data = await asyncio.wait_for(websocket.receive_bytes(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                allowed(device_id, "voice")
                now = time.monotonic()
                if now - window >= 1:
                    window, frames = now, 0
                frames += 1
                if not 2 <= len(data) <= 8192 or len(data) % 2 or frames > 50:
                    break
                try:
                    server._phone_audio_queue.put_nowait({"data": data, "mime_type": "audio/pcm;rate=16000"})
                except asyncio.QueueFull:
                    break  # Fail visibly instead of accumulating stale speech.
        except (WebSocketDisconnect, PermissionError, RuntimeError):
            pass
        finally:
            voice_active = False
            while not server._phone_audio_queue.empty():
                try:
                    server._phone_audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            notice("Phone microphone disconnected.")
            try:
                await websocket.close(code=1000)
            except RuntimeError:
                pass

    @app.post("/remote-api/{operation}")
    async def remote(operation: str, req: Request):
        try:
            enabled()
            raw = await req.body()
            if len(raw) > 16384:
                return JSONResponse({"error": "Request too large"}, status_code=413)
            body = await req.json()
            if not isinstance(body, dict):
                raise ValueError("Object required")
            db = storage()
            if operation == "enroll":
                if not load_api_keys().get("allow_device_pairing", False):
                    raise PermissionError("Enable device pairing on the PC first")
                code = body.get("code", "")
                if not isinstance(code, str) or server._pending_keys.get(code.upper(), 0) <= time.time():
                    raise PermissionError("Invalid or expired PC pairing code")
                device = db.enroll(body.get("public_key"), body.get("name"), body.get("platform"))
                server._pending_keys.pop(code.upper(), None)
                return {"id": device["id"], "fingerprint": device["fingerprint"], "message": "Compare the fingerprint and trust this device on the PC."}
            if operation == "challenge":
                return db.challenge(body.get("device_id"))
            device = db.verify(req.headers.get("x-device", ""), req.headers.get("x-nonce", ""),
                               req.headers.get("x-signature", ""), req.method, req.url.path, raw)
            device_id = device["id"]
            if operation == "session":
                return {"name": device["name"], "capabilities": device["capabilities"],
                        "features": load_api_keys().get("remote_features", {}), "server_time": time.time()}
            if operation == "receipts":
                return {"commands": db.receipts(device_id)}
            if operation == "notifications":
                return {"notifications": db.notifications(device_id), "delivery": "saved_inbox", "push_configured": push().status(device_id)['subscribed']}
            if operation == 'push-status':
                return {**push().status(device_id), 'public_key': push().public_key()}
            if operation == 'push-subscribe':
                if not push().status(device_id)['available']:
                    raise ValueError('Install requirements-push.txt on the PC first')
                push().subscribe(device_id, body.get('subscription'))
                return {'subscribed': True}
            if operation == 'push-unsubscribe':
                push().unsubscribe(device_id)
                return {'subscribed': False}
            if operation == 'audio-ticket':
                allowed(device_id, 'voice')
                allowed(device_id, 'chat')
                if not server._session_ready():
                    raise ValueError('The PC cloud assistant is offline')
                if audio_listener is not None:
                    raise ValueError('Phone speaker is already connected')
                for old, (_device, expiry) in list(audio_tickets.items()):
                    if expiry <= time.time() or _device == device_id:
                        audio_tickets.pop(old, None)
                ticket = secrets.token_urlsafe(32)
                audio_tickets[ticket] = (device_id, time.time() + 30)
                return {'ticket': ticket, 'expires_in': 30, 'sample_rate': 24000}
            if operation == "notification-read":
                db.read_notification(device_id, body.get("id"))
                return {"read": True}
            if operation == "voice-ticket":
                allowed(device_id, "voice")
                if not server._session_ready():
                    raise ValueError("The PC cloud assistant is offline")
                if voice_active:
                    raise ValueError("Another phone microphone is already connected")
                for old, (_device, expiry) in list(voice_tickets.items()):
                    if expiry <= time.time() or _device == device_id:
                        voice_tickets.pop(old, None)
                ticket = secrets.token_urlsafe(32)
                voice_tickets[ticket] = (device_id, time.time() + 30)
                return {"ticket": ticket, "expires_in": 30}
            if operation == "transcript":
                allowed(device_id, "chat")
                return {"messages": [r for r in server._history if r.get("type") == "log"][-30:],
                        "online": server._session_ready()}
            if operation == "chat":
                allowed(device_id, "chat")
                text = body.get("text")
                if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
                    raise ValueError("Enter a message of 1–2000 characters")
                if not server._session_ready():
                    raise ValueError("The PC cloud assistant is offline; message was not queued")
                if server._command_queue.full():
                    raise ValueError("PC command queue is full")
                claim_live(device_id)
                command_id, created = db.enqueue(device_id, body.get("request_id"), {"text": text, "type": "chat"})
                if created:
                    server._command_queue.put_nowait({"text": text, "remote_id": command_id, "device_id": device_id})
                    if server._wake_callback:
                        server._wake_callback()
                return {"id": command_id, "new": created}
            if operation == "revoke-self":
                db.revoke(device_id)
                return {"revoked": True}
            if operation == "command":
                allowed(device_id, "commands")
                payload = {"text": body.get("text")}
                if not isinstance(payload["text"], str) or not 1 <= len(payload["text"].strip()) <= 2000:
                    raise ValueError("Enter a command of 1–2000 characters")
                command_id, created = db.enqueue(device_id, body.get("request_id"), payload)
                if created:
                    task = asyncio.create_task(execute(command_id, device_id, payload))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                return {"id": command_id, "new": created}
            if operation == "computer":
                allowed(device_id, "computer")
                import psutil
                from core.battery import snapshot
                cpu = await asyncio.to_thread(psutil.cpu_percent, interval=.15)
                return {"cpu_percent": cpu, "memory_percent": psutil.virtual_memory().percent,
                        "battery": snapshot(), "at": time.time(), "assistant_online": server._session_ready()}
            if operation == "screen":
                allowed(device_id, "screen")
                from core.permission_manager import manager
                if manager.settings().get("screen") not in ("Allow", "Allow While Active"):
                    raise PermissionError("PC screen permission does not allow capture")
                from core.diagnostics import record
                record("remote", "screen_capture", source="phone", status="requested")
                notice = getattr(server, "remote_notice", None)
                if notice:
                    notice("A trusted phone requested a screen capture.")
                def capture():
                    import pyautogui
                    image = pyautogui.screenshot()
                    image.thumbnail((1600, 1000))
                    buf = io.BytesIO()
                    image.convert("RGB").save(buf, format="JPEG", quality=70)
                    return base64.b64encode(buf.getvalue()).decode()
                data = await asyncio.to_thread(capture)
                allowed(device_id, "screen")
                return {"image": data, "at": time.time()}
            if operation in ("roots", "files", "download"):
                allowed(device_id, "files")
                from core.permission_manager import manager
                if manager.settings().get("file_read") != "Allow":
                    raise PermissionError("PC file read permission does not allow remote browsing")
                roots = load_api_keys().get("remote_file_roots", [])
                if operation == "roots":
                    return {"roots": [{"id": i, "name": Path(p).name} for i, p in enumerate(roots)]}
                path = scoped_path(roots, body.get("root"), body.get("path", ""))
                if operation == "files":
                    if not path.is_dir():
                        raise ValueError("Folder required")
                    rows = []
                    for p in path.iterdir():
                        if len(rows) >= 500:
                            break
                        try:
                            safe = scoped_path(roots, body["root"], str(p.relative_to(Path(roots[body["root"]]).resolve())))
                            rows.append({"name": p.name, "directory": safe.is_dir(), "size": safe.stat().st_size})
                        except (PermissionError, OSError):
                            continue
                    return {"files": sorted(rows, key=lambda r: (not r["directory"], r["name"].lower())), "limit": 500}
                if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError("Download requires a file of at most 10 MB")
                def read():
                    with path.open("rb") as f:
                        data = f.read(10 * 1024 * 1024 + 1)
                    if len(data) > 10 * 1024 * 1024:
                        raise ValueError("File grew beyond download limit")
                    return base64.b64encode(data).decode()
                data = await asyncio.to_thread(read)
                allowed(device_id, "files")
                return {"name": path.name, "data": data}
            if operation == "projects":
                allowed(device_id, "projects")
                from core import jobs
                from core.project_memory import projects
                commands = [{k: r[k] for k in ("id", "name", "kind", "enabled", "revision", "timeout", "port")} for r in db.profiles()]
                return {"projects": projects.list(), "jobs": jobs.recent(), "commands": commands}
            if operation == "project-run":
                allowed(device_id, "projects")
                if set(body) - {"profile_id", "revision", "request_id"}:
                    raise ValueError("Phone requests cannot change approved command arguments")
                command_id, created = await asyncio.to_thread(projects_runner().start, device_id,
                    body.get("profile_id"), body.get("revision"), body.get("request_id"))
                return {"id": command_id, "new": created}
            if operation == "project-stop":
                return {"message": projects_runner().cancel(device_id, body.get("id"))}
            if operation == "workflows":
                allowed(device_id, "workflows")
                return {"workflows": workflows_runner().listing()}
            if operation == "workflow-run":
                if set(body) - {"id", "version", "request_id"}:
                    raise ValueError("Phone requests cannot replace saved workflow steps")
                command_id, created = workflows_runner().start(device_id, body.get("id"), body.get("version"), body.get("request_id"))
                return {"id": command_id, "new": created}
            if operation == "workflow-stop":
                return {"message": workflows_runner().cancel(device_id, body.get("id"))}
            if operation == "automations":
                return automation_engine(device_id).describe()
            if operation == "automation-control":
                engine = automation_engine(device_id)
                ident, revision, action = body.get("id"), body.get("revision"), body.get("action")
                if not isinstance(ident, str) or type(revision) is not int or action not in ("enable", "disable", "run"):
                    raise ValueError("Automation ID, revision and action are required")
                rule = engine.get(ident)
                if rule["revision"] != revision:
                    raise ValueError("Automation changed; refresh before using it")
                if action != "run":
                    changed = engine.set_enabled(ident, action == "enable", revision)
                    return {"id": ident, "revision": changed["revision"], "enabled": changed["enabled"]}
                command_id, created = db.enqueue(device_id, body.get("request_id"),
                    {"type": "automation", "automation_id": ident, "revision": revision, "text": rule["name"]})
                if created:
                    task = asyncio.create_task(execute_automation(command_id, device_id, ident, revision))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                return {"id": command_id, "new": created}
            return JSONResponse({"error": "Unknown operation"}, status_code=404)
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=400)
