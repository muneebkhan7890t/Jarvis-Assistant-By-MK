"""Authenticated phone endpoints; project status works without a live voice session."""
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from core import jobs
from core.battery import snapshot


def register(app, auth, server):
    @app.get('/api/projects')
    async def list_projects(req: Request):
        if not auth(req):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        rows = await asyncio.to_thread(jobs.recent)
        return {'jobs': rows, 'battery': await asyncio.to_thread(snapshot),
                'assistant_online': server._session_ready()}

    @app.post('/api/projects')
    async def start_project(req: Request):
        if not auth(req):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        try:
            body = await req.json()
            description = body.get('description', '')
            if not isinstance(description, str) or not description.strip() or len(description) > 12000:
                raise ValueError()
        except (ValueError, AttributeError):
            return JSONResponse({'error': 'Enter a project description (1–12000 characters).'}, status_code=400)
        from memory.config_manager import get_gemini_key
        if not get_gemini_key():
            return JSONResponse({'error': 'Set up the Gemini key on the PC first.'}, status_code=503)
        from actions.dev_agent import dev_agent
        from core.permission_manager import manager
        result = await asyncio.to_thread(manager.invoke, 'dev_agent', {'description': description}, dev_agent, 'phone')
        return {'message': result}

    @app.post('/api/projects/{job_id}/{action}')
    async def change_project(job_id: str, action: str, req: Request):
        if not auth(req):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        if action not in ('cancel', 'retry'):
            return JSONResponse({'error': 'Unknown action'}, status_code=400)
        if not jobs.get(job_id):
            return JSONResponse({'error': 'Job not found'}, status_code=404)
        from actions.project_jobs import run
        from core.permission_manager import manager
        result = await asyncio.to_thread(manager.invoke, 'project_jobs', {'action': action, 'id': job_id}, run, 'phone')
        return {'message': result}
