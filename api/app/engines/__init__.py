import asyncio
import logging
import multiprocessing
import queue
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from starlette.concurrency import iterate_in_threadpool

from .. import hub
from ..config import Settings
from .base import Chunk, Engine, GenerationParams, resolve_device

log = logging.getLogger(__name__)

Status = Literal["downloading", "loading", "ready", "error"]


@dataclass(frozen=True)
class ModelRef:
    model_id: str
    model_file: str = ""

    @property
    def engine_name(self) -> str:
        return "llama.cpp" if self.model_file else "transformers"


class Cancelled(Exception):
    pass


class DownloadError(Exception):
    pass


class Busy(Exception):
    pass


def create_engine(ref: ModelRef, path: str, settings: Settings) -> Engine:
    if ref.model_file:
        from .llamacpp_engine import LlamaCppEngine

        return LlamaCppEngine(path, settings.device, settings.max_context)

    from .transformers_engine import TransformersEngine

    return TransformersEngine(path, settings.device, settings.max_context)


class ModelManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.device = resolve_device(settings.device)
        self.current: ModelRef | None = None
        self.target: ModelRef | None = None
        self.engine: Engine | None = None
        self.status: Status = "loading"
        self.error: str | None = None
        self.loaded_at: int | None = None
        self.plan: hub.DownloadPlan | None = None
        self._cancel = threading.Event()
        self._lock = asyncio.Lock()

    @property
    def active(self) -> ModelRef:
        return self.target or self.current or self._env_ref()

    @property
    def busy(self) -> bool:
        return self.status in ("downloading", "loading")

    def progress(self) -> dict | None:
        plan = self.plan
        if self.status != "downloading" or plan is None:
            return None
        return {"downloaded": hub.downloaded_bytes(plan), "total": plan.total_bytes}

    def resources(self) -> dict:
        ram_total = ram_available = vram_total = vram_free = None
        try:
            with open("/proc/meminfo") as f:
                info = {k: int(v.split()[0]) * 1024 for k, v in (line.split(":", 1) for line in f)}
            ram_total, ram_available = info.get("MemTotal"), info.get("MemAvailable")
        except OSError:
            pass
        if self.device == "cuda":
            import torch

            vram_free, vram_total = torch.cuda.mem_get_info()
        return {
            "ram_total": ram_total,
            "ram_available": ram_available,
            "vram_total": vram_total,
            "vram_free": vram_free,
        }

    def _env_ref(self) -> ModelRef:
        return ModelRef(self.settings.model_id, self.settings.model_file)

    def _initial_ref(self) -> ModelRef:
        env = self._env_ref()
        state = hub.read_state()
        if state and state.get("env") == [env.model_id, env.model_file]:
            return ModelRef(state["model_id"], state.get("model_file", ""))
        return env

    def start_loading(self) -> None:
        self._start(self._initial_ref(), fallback=None)

    async def switch(self, ref: ModelRef) -> None:
        if self.busy:
            raise Busy("Başka bir model hazırlanıyor; bitmesini bekleyin ya da iptal edin.")
        if ref == self.current and self.status == "ready":
            return
        self.target, self.error, self.status = ref, None, "loading"
        async with self._lock:
            previous = self.current
            await asyncio.to_thread(self._unload)
        self._start(ref, fallback=previous)

    def cancel(self) -> None:
        if self.status != "downloading":
            raise Busy("İptal edilecek bir indirme yok.")
        self._cancel.set()

    def _start(self, ref: ModelRef, fallback: ModelRef | None) -> None:
        self.target = ref
        self._cancel.clear()
        threading.Thread(target=self._run, args=(ref, fallback), name="model-loader", daemon=True).start()

    def _unload(self) -> None:
        if self.engine is not None:
            self.engine.unload()
        self.engine, self.current = None, None

    def _run(self, ref: ModelRef, fallback: ModelRef | None) -> None:
        started = time.time()
        try:
            engine = self._prepare(ref)
        except Cancelled:
            log.info("İndirme iptal edildi: %s", ref.model_id)
            message = None if fallback else "İndirme iptal edildi."
        except DownloadError as exc:
            message = str(exc)
        except Exception as exc:
            log.exception("Model yüklenemedi: %s", ref.model_id)
            message = hub.friendly_error(exc)
        else:
            self.engine, self.current, self.target, self.plan = engine, ref, None, None
            self.loaded_at = int(time.time())
            self.status = "ready"
            env = self._env_ref()
            hub.write_state(
                {"model_id": ref.model_id, "model_file": ref.model_file, "env": [env.model_id, env.model_file]}
            )
            log.info("Model hazır: %s [%s, %s] (%.1f sn)", ref.model_id, engine.name, engine.device, time.time() - started)
            return

        self.plan = None
        if fallback is None:
            self.status, self.error = "error", message
            return
        log.warning("Önceki modele dönülüyor: %s", fallback.model_id)
        self._cancel.clear()
        self._run(fallback, None)
        if self.status == "ready" and message:
            self.error = f"{ref.model_id} yüklenemedi, önceki modele dönüldü. {message}"

    def _prepare(self, ref: ModelRef) -> Engine:
        self.status = "loading"
        plan = hub.plan_download(ref.model_id, ref.model_file, self.settings.hf_token)
        missing = [name for name, _ in plan.files if not hub.is_cached(ref.model_id, name)]
        if missing:
            self.plan, self.status = plan, "downloading"
            log.info("İndiriliyor: %s (%d dosya, %.2f GB)", ref.model_id, len(missing), plan.total_bytes / 1e9)
            self._download(ref.model_id, missing)
            self.plan, self.status = None, "loading"

        path = hub.local_path(ref.model_id, plan.model_file)
        engine = create_engine(ref, str(path), self.settings)
        engine.load()
        return engine

    def _download(self, model_id: str, files: list[str]) -> None:
        ctx = multiprocessing.get_context("spawn")
        errors = ctx.Queue()
        proc = ctx.Process(
            target=hub.download_worker,
            args=(model_id, files, self.settings.hf_token, errors),
            daemon=True,
        )
        proc.start()
        while proc.is_alive():
            if self._cancel.wait(0.5):
                proc.terminate()
                proc.join()
                raise Cancelled()
        proc.join()
        try:
            message = errors.get(timeout=0.2)
        except queue.Empty:
            message = None
        if message or proc.exitcode != 0:
            raise DownloadError(message or f"İndirme süreci beklenmedik şekilde sonlandı (kod {proc.exitcode}).")

    async def stream(
        self, messages: list[dict[str, str]], params: GenerationParams
    ) -> AsyncIterator[Chunk]:
        cancel = threading.Event()
        async with self._lock:
            if self.engine is None or self.status != "ready":
                raise RuntimeError("Model henüz hazır değil.")
            chunks = self.engine.stream(messages, params, cancel)
            try:
                async for chunk in iterate_in_threadpool(chunks):
                    yield chunk
            finally:
                cancel.set()
                try:
                    await asyncio.to_thread(chunks.close)
                except ValueError:
                    pass
