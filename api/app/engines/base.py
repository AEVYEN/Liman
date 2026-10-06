import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class GenerationParams:
    max_new_tokens: int
    temperature: float
    top_p: float = 1.0
    stop: list[str] | None = None


@dataclass
class Chunk:
    text: str = ""
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Engine(ABC):
    name: str
    device: str

    @abstractmethod
    def load(self) -> None:
        pass

    @abstractmethod
    def unload(self) -> None:
        pass

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, str]],
        params: GenerationParams,
        cancel: threading.Event,
    ) -> Iterator[Chunk]:
        pass


def resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
