import json
import os
import re
import shutil
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.constants import HF_HUB_CACHE
from huggingface_hub.errors import (
    EntryNotFoundError,
    GatedRepoError,
    RepositoryNotFoundError,
)

SPLIT_GGUF = re.compile(r"^(?P<base>.+)-(?P<part>\d{5})-of-(?P<total>\d{5})\.gguf$")
TRANSFORMERS_PATTERNS = ["*.json", "*.model", "*.tiktoken", "*.txt", "*.jinja"]


@dataclass
class DownloadPlan:
    model_id: str
    model_file: str
    files: list[tuple[str, int]] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(size for _, size in self.files)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, GatedRepoError):
        return (
            "Bu model erişim izni gerektiriyor (gated). Hugging Face'te model sayfasından "
            "lisansı kabul edin ve .env dosyasına HF_TOKEN ekleyin."
        )
    if isinstance(exc, RepositoryNotFoundError):
        return "Model bulunamadı. Kimliği kontrol edin; özel bir depoysa HF_TOKEN gerekir."
    if isinstance(exc, EntryNotFoundError):
        return "İstenen dosya bu depoda bulunamadı."
    if isinstance(exc, (ValueError, FileNotFoundError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _token(token: str | None) -> str | None:
    return token or None


def search_models(query: str, token: str | None, limit: int = 30) -> list[dict]:
    models = HfApi().list_models(
        search=query or None,
        pipeline_tag="text-generation",
        sort="downloads",
        limit=limit,
        expand=["downloads", "likes", "tags", "gated", "library_name"],
        token=_token(token),
    )
    results = []
    for m in models:
        tags = m.tags or []
        gguf = "gguf" in tags
        transformers = m.library_name == "transformers" or "transformers" in tags
        if not (gguf or transformers):
            continue
        results.append(
            {
                "id": m.id,
                "downloads": m.downloads or 0,
                "likes": m.likes or 0,
                "gated": bool(m.gated),
                "gguf": gguf,
                "transformers": transformers,
            }
        )
    return results


def _transformers_files(siblings: list[tuple[str, int]]) -> list[tuple[str, int]]:
    root = [(n, s) for n, s in siblings if "/" not in n]
    names = {n for n, _ in root}
    if "config.json" not in names:
        return []
    weights = [
        (n, s) for n, s in root if n.endswith(".safetensors") and not n.startswith("consolidated")
    ]
    if not weights:
        weights = [(n, s) for n, s in root if fnmatch(n, "pytorch_model*.bin")]
    if not weights:
        return []
    extras = [(n, s) for n, s in root if any(fnmatch(n, p) for p in TRANSFORMERS_PATTERNS)]
    return extras + weights


def _gguf_variants(siblings: list[tuple[str, int]]) -> list[dict]:
    variants: dict[str, dict] = {}
    for name, size in siblings:
        if not name.endswith(".gguf") or "mmproj" in name.lower():
            continue
        split = SPLIT_GGUF.match(name)
        key = split["base"] if split else name
        v = variants.setdefault(key, {"file": name, "size": 0, "parts": 0})
        v["size"] += size
        v["parts"] += 1
        if split and split["part"] == "00001":
            v["file"] = name
    return sorted(variants.values(), key=lambda v: v["size"])


def _remote_siblings(model_id: str, token: str | None) -> tuple[list[tuple[str, int]], bool]:
    info = HfApi().model_info(model_id, files_metadata=True, token=_token(token))
    return [(s.rfilename, s.size or 0) for s in info.siblings], bool(info.gated)


def repo_options(model_id: str, token: str | None) -> dict:
    siblings, gated = _remote_siblings(model_id, token)
    tf = _transformers_files(siblings)
    return {
        "id": model_id,
        "gated": gated,
        "transformers": {"size": sum(s for _, s in tf)} if tf else None,
        "gguf": _gguf_variants(siblings),
    }


def _resolve_gguf(model_id: str, pattern: str, siblings: list[tuple[str, int]]) -> list[tuple[str, int]]:
    matches = [(n, s) for n, s in siblings if n.endswith(".gguf") and fnmatch(n, pattern)]
    if not matches:
        raise FileNotFoundError(f"{model_id} içinde '{pattern}' ile eşleşen GGUF dosyası yok.")
    groups: dict[str, list[tuple[str, int]]] = {}
    for n, s in matches:
        split = SPLIT_GGUF.match(n)
        groups.setdefault(split["base"] if split else n, []).append((n, s))
    if len(groups) > 1:
        names = ", ".join(sorted(groups))
        raise ValueError(f"'{pattern}' birden fazla GGUF dosyasıyla eşleşti: {names}. Tam dosya adı verin.")
    (base, files), = groups.items()
    if SPLIT_GGUF.match(files[0][0]):
        files = [(n, s) for n, s in siblings if (m := SPLIT_GGUF.match(n)) and m["base"] == base]
    return sorted(files)


def plan_download(model_id: str, model_file: str, token: str | None) -> DownloadPlan:
    try:
        siblings, _ = _remote_siblings(model_id, token)
    except (GatedRepoError, RepositoryNotFoundError):
        raise
    except Exception:
        siblings = local_files(model_id)
        if not siblings:
            raise

    if model_file:
        files = _resolve_gguf(model_id, model_file, siblings)
        return DownloadPlan(model_id, files[0][0], files)

    files = _transformers_files(siblings)
    if not files:
        raise ValueError(
            f"{model_id} transformers ile yüklenebilecek bir model değil "
            "(config.json ya da safetensors bulunamadı). GGUF deposuysa bir dosya seçin."
        )
    return DownloadPlan(model_id, "", files)


def download_worker(model_id: str, files: list[str], token: str | None, errors) -> None:
    try:
        for name in files:
            hf_hub_download(model_id, name, token=_token(token))
    except Exception as exc:
        errors.put(friendly_error(exc))


def _repo_dir(model_id: str) -> Path:
    return Path(HF_HUB_CACHE) / f"models--{model_id.replace('/', '--')}"


def snapshot_dir(model_id: str) -> Path | None:
    repo = _repo_dir(model_id)
    ref = repo / "refs" / "main"
    if ref.is_file():
        snap = repo / "snapshots" / ref.read_text().strip()
        if snap.is_dir():
            return snap
    snaps = sorted((repo / "snapshots").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return snaps[0] if snaps else None


def local_files(model_id: str) -> list[tuple[str, int]]:
    snap = snapshot_dir(model_id)
    if not snap:
        return []
    files = []
    for path in snap.rglob("*"):
        if path.is_file():
            files.append((path.relative_to(snap).as_posix(), path.stat().st_size))
    return files


def is_cached(model_id: str, filename: str) -> bool:
    snap = snapshot_dir(model_id)
    return bool(snap and (snap / filename).is_file())


def local_path(model_id: str, filename: str = "") -> Path:
    snap = snapshot_dir(model_id)
    if not snap:
        raise FileNotFoundError(f"{model_id} önbellekte yok.")
    return snap / filename if filename else snap


def downloaded_bytes(plan: DownloadPlan) -> int:
    done = sum(size for name, size in plan.files if is_cached(plan.model_id, name))
    blobs = _repo_dir(plan.model_id) / "blobs"
    partial = sum(p.stat().st_size for p in blobs.glob("*.incomplete")) if blobs.is_dir() else 0
    return min(done + partial, plan.total_bytes)


def list_local_models() -> list[dict]:
    cache = Path(HF_HUB_CACHE)
    if not cache.is_dir():
        return []
    repos = []
    for repo in sorted(cache.glob("models--*")):
        model_id = repo.name.removeprefix("models--").replace("--", "/")
        files = local_files(model_id)
        options = []
        tf = _transformers_files(files)
        if tf:
            options.append({"model_file": "", "size": sum(s for _, s in tf)})
        for v in _gguf_variants(files):
            options.append({"model_file": v["file"], "size": v["size"]})
        if options:
            size = sum(p.stat().st_size for p in (repo / "blobs").glob("*") if p.is_file())
            repos.append({"id": model_id, "size": size, "options": options})
    return repos


def delete_local_model(model_id: str) -> None:
    repo = _repo_dir(model_id)
    if not repo.is_dir():
        raise FileNotFoundError(f"{model_id} önbellekte yok.")
    shutil.rmtree(repo)


STATE_FILE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "liman-state.json"


def read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
