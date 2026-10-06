import logging
import threading
from collections.abc import Iterator

from .base import Chunk, Engine, GenerationParams, resolve_device

log = logging.getLogger(__name__)


class TransformersEngine(Engine):
    name = "transformers"

    def __init__(self, model_path: str, device: str, max_context: int):
        self.model_path = model_path
        self.device = resolve_device(device)
        self.max_context = max_context
        self.model = None
        self.tokenizer = None

    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        log.info("Model yükleniyor: %s (cihaz: %s)", self.model_path, self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        if self.device == "cuda":
            kwargs = {"torch_dtype": "auto", "device_map": "auto"}
        else:
            kwargs = {"torch_dtype": torch.float32}
        self.model = AutoModelForCausalLM.from_pretrained(self.model_path, **kwargs)
        if self.device == "cpu":
            self.model.to("cpu")
        self.model.eval()

    def unload(self) -> None:
        import gc

        import torch

        self.model = None
        self.tokenizer = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def stream(
        self,
        messages: list[dict[str, str]],
        params: GenerationParams,
        cancel: threading.Event,
    ) -> Iterator[Chunk]:
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        encoded = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
        )
        input_ids = encoded["input_ids"].to(self.model.device)
        prompt_tokens = input_ids.shape[-1]
        if prompt_tokens >= self.max_context:
            raise ValueError(
                f"İstem {prompt_tokens} token; bağlam sınırı (MAX_CONTEXT) {self.max_context}."
            )
        max_new_tokens = min(params.max_new_tokens, self.max_context - prompt_tokens)

        class _Cancelled(StoppingCriteria):
            def __call__(self, *args, **kwargs) -> bool:
                return cancel.is_set()

        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs = {
            "input_ids": input_ids,
            "attention_mask": input_ids.new_ones(input_ids.shape),
            "max_new_tokens": max_new_tokens,
            "streamer": streamer,
            "stopping_criteria": StoppingCriteriaList([_Cancelled()]),
            "pad_token_id": self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
        }
        if params.temperature > 0:
            gen_kwargs.update(do_sample=True, temperature=params.temperature, top_p=params.top_p)
        else:
            gen_kwargs.update(do_sample=False, temperature=None, top_p=None)

        result: dict = {}

        def _generate() -> None:
            try:
                result["output"] = self.model.generate(**gen_kwargs)
            except Exception as exc:
                result["error"] = exc
                streamer.end()

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

        stops = [s for s in (params.stop or []) if s]
        hold = max((len(s) for s in stops), default=1) - 1
        text = ""
        emitted = 0
        finish_reason = None
        try:
            for piece in streamer:
                text += piece
                hit = min((i for i in (text.find(s) for s in stops) if i != -1), default=-1)
                if hit != -1:
                    if hit > emitted:
                        yield Chunk(text=text[emitted:hit])
                    text = text[:hit]
                    finish_reason = "stop"
                    cancel.set()
                    break
                safe = len(text) - hold
                if safe > emitted:
                    yield Chunk(text=text[emitted:safe])
                    emitted = safe
        finally:
            cancel.set()
            thread.join()

        if "error" in result:
            raise result["error"]

        if finish_reason is None:
            if len(text) > emitted:
                yield Chunk(text=text[emitted:])
            output = result.get("output")
            new_tokens = output.shape[-1] - prompt_tokens if output is not None else 0
            finish_reason = "length" if new_tokens >= max_new_tokens else "stop"

        completion_tokens = len(self.tokenizer.encode(text, add_special_tokens=False))
        yield Chunk(
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
