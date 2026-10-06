import asyncio

from fastapi import APIRouter, Query, Request
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError
from pydantic import BaseModel

from .. import hub
from ..engines import Busy, ModelManager, ModelRef
from .health import health
from .openai import error_response

router = APIRouter(prefix="/api")


class LoadRequest(BaseModel):
    model_id: str
    model_file: str = ""


def _manager(request: Request) -> ModelManager:
    return request.app.state.manager


def _hub_error(exc: Exception):
    if isinstance(exc, RepositoryNotFoundError):
        status = 404
    elif isinstance(exc, GatedRepoError):
        status = 403
    else:
        status = 502
    return error_response(status, hub.friendly_error(exc), "hub_error")


@router.get("/hub/search")
async def search(request: Request, q: str = Query("", max_length=200)):
    token = _manager(request).settings.hf_token
    try:
        return {"results": await asyncio.to_thread(hub.search_models, q.strip(), token)}
    except Exception as exc:
        return _hub_error(exc)


@router.get("/hub/repo")
async def repo(request: Request, model_id: str = Query(min_length=1)):
    token = _manager(request).settings.hf_token
    try:
        return await asyncio.to_thread(hub.repo_options, model_id, token)
    except Exception as exc:
        return _hub_error(exc)


@router.get("/models/local")
async def local_models():
    return {"models": await asyncio.to_thread(hub.list_local_models)}


@router.delete("/models/local")
async def delete_local(request: Request, model_id: str = Query(min_length=1)):
    manager = _manager(request)
    in_use = {ref.model_id for ref in (manager.current, manager.target) if ref}
    if model_id in in_use:
        return error_response(409, "Kullanımdaki model silinemez; önce başka bir modele geçin.", "model_in_use")
    try:
        await asyncio.to_thread(hub.delete_local_model, model_id)
    except FileNotFoundError as exc:
        return error_response(404, str(exc), "not_found")
    return {"deleted": model_id}


@router.post("/models/load", status_code=202)
async def load(body: LoadRequest, request: Request):
    manager = _manager(request)
    try:
        await manager.switch(ModelRef(body.model_id.strip(), body.model_file.strip()))
    except Busy as exc:
        return error_response(409, str(exc), "busy")
    return await health(request)


@router.post("/models/cancel")
async def cancel(request: Request):
    try:
        _manager(request).cancel()
    except Busy as exc:
        return error_response(409, str(exc), "not_downloading")
    return await health(request)
