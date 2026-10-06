import logging
import threading
from collections.abc import Iterator

from .base import Chunk, Engine, GenerationParams, resolve_device

log = logging.getLogger(__name__)


class LlamaCppEngine(Engine):
    name = "llama.cpp"

    def __init__(self, model_path: str, device: str, max_context: int):
        self.model_path = model_path
        self.device = resolve_device(device)
        self.max_context = max_context
        self.llm = None

    def load(self) -> None:
        from llama_cpp import Llama

        log.info("GGUF yükleniyor: %s (cihaz: %s)", self.model_path, self.device)
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=self.max_context,
            n_gpu_layers=-1 if self.device == "cuda" else 0,
            verbose=False,
        )

    def unload(self) -> None:
        import gc

        if self.llm is not None:
            self.llm.close()
            self.llm = None
        gc.collect()

    def stream(
        self,
        messages: list[dict[str, str]],
        params: GenerationParams,
        cancel: threading.Event,
    ) -> Iterator[Chunk]:
        completion_tokens = 0
        finish_reason = None
        for part in self.llm.create_chat_completion(
            messages=messages,
            stream=True,
            max_tokens=params.max_new_tokens,
            temperature=params.temperature,
            top_p=params.top_p,
            stop=params.stop or None,
        ):
            if cancel.is_set():
                return
            choice = part["choices"][0]
            text = choice["delta"].get("content") or ""
            if text:
                completion_tokens += 1
                yield Chunk(text=text)
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

        yield Chunk(
            finish_reason=finish_reason or "stop",
            prompt_tokens=max(self.llm.n_tokens - completion_tokens, 0),
            completion_tokens=completion_tokens,
        )
