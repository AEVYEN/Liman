import asyncio

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    manager = request.app.state.manager
    settings = manager.settings
    active = manager.active
    return {
        "status": manager.status,
        "model": active.model_id,
        "model_file": active.model_file or None,
        "engine": active.engine_name,
        "device": manager.device,
        "error": manager.error,
        "progress": await asyncio.to_thread(manager.progress),
        "resources": manager.resources(),
        "defaults": {
            "max_context": settings.max_context,
            "max_new_tokens": settings.max_new_tokens,
            "temperature": settings.temperature,
        },
    }
