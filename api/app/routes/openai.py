import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..engines import ModelManager
from ..engines.base import GenerationParams
from ..schemas import ChatCompletionRequest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")


def error_response(status: int, message: str, type_: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": type_, "code": code}},
    )


def _manager(request: Request) -> ModelManager:
    return request.app.state.manager


@router.get("/models")
async def list_models(request: Request):
    manager = _manager(request)
    active = manager.active
    return {
        "object": "list",
        "data": [
            {
                "id": active.model_id,
                "object": "model",
                "created": manager.loaded_at or 0,
                "owned_by": "liman",
                "engine": active.engine_name,
                "status": manager.status,
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    manager = _manager(request)
    if manager.busy:
        return error_response(503, "Model hâlâ hazırlanıyor, lütfen biraz sonra tekrar deneyin.", "model_loading")
    if manager.status == "error":
        return error_response(500, f"Model yüklenemedi: {manager.error}", "model_error")

    settings = manager.settings
    params = GenerationParams(
        max_new_tokens=body.max_completion_tokens or body.max_tokens or settings.max_new_tokens,
        temperature=settings.temperature if body.temperature is None else body.temperature,
        top_p=body.top_p,
        stop=body.stop_list,
    )
    messages = [m.model_dump() for m in body.messages]
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model_id = manager.active.model_id

    if body.stream:
        return StreamingResponse(
            _sse(manager, messages, params, completion_id, created, model_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    text_parts: list[str] = []
    final = None
    try:
        async for chunk in manager.stream(messages, params):
            text_parts.append(chunk.text)
            if chunk.finish_reason:
                final = chunk
    except ValueError as exc:
        return error_response(400, str(exc), "invalid_request_error", "context_length_exceeded")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": final.finish_reason if final else "stop",
            }
        ],
        "usage": _usage(final),
    }


def _usage(chunk) -> dict:
    prompt = chunk.prompt_tokens if chunk else 0
    completion = chunk.completion_tokens if chunk else 0
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


async def _sse(
    manager: ModelManager,
    messages: list[dict[str, str]],
    params: GenerationParams,
    completion_id: str,
    created: int,
    model_id: str,
) -> AsyncIterator[str]:
    def event(delta: dict, finish_reason: str | None = None, **extra) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            **extra,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    yield event({"role": "assistant", "content": ""})
    try:
        async for chunk in manager.stream(messages, params):
            if chunk.text:
                yield event({"content": chunk.text})
            if chunk.finish_reason:
                yield event({}, chunk.finish_reason, usage=_usage(chunk))
    except Exception as exc:
        log.exception("Akış sırasında hata")
        error = {"error": {"message": str(exc), "type": "server_error", "code": None}}
        yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
