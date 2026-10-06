import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .engines import ModelManager
from .routes import health, models, openai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = ModelManager(get_settings())
    app.state.manager = manager
    manager.start_loading()
    yield


app = FastAPI(
    title="Liman API",
    description="Hugging Face modelleri için OpenAI uyumlu yerel çıkarım API'si.",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return openai.error_response(422, str(exc.errors()), "invalid_request_error")


app.include_router(health.router)
app.include_router(openai.router)
app.include_router(models.router)
