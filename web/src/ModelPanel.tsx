import { useCallback, useEffect, useState } from "react";
import {
  cancelDownload,
  deleteLocalModel,
  fetchLocalModels,
  fetchRepo,
  loadModel,
  searchHub,
  type Health,
  type HubResult,
  type LocalModel,
  type RepoOptions,
} from "./api";

type Tab = "local" | "hub";

interface Props {
  health: Health;
  onHealth: (h: Health) => void;
  onClose: () => void;
}

const GB = 1024 ** 3;

export function formatBytes(n: number): string {
  if (n >= GB) return `${(n / GB).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(n / 1024 ** 2))} MB`;
}

const formatCount = (n: number) => n.toLocaleString("tr-TR");

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

const variantName = (file: string) => file.split("/").pop()!.replace(/-\d{5}-of-\d{5}(?=\.gguf$)/, "");

export default function ModelPanel({ health, onHealth, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("local");
  const [local, setLocal] = useState<LocalModel[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const busy = health.status === "downloading" || health.status === "loading";

  const localKey = `${health.status}|${health.model}|${health.model_file}`;
  const refreshLocal = useCallback(() => {
    fetchLocalModels()
      .then(setLocal)
      .catch((e) => setActionError(errorText(e)));
  }, []);
  useEffect(refreshLocal, [refreshLocal, localKey]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async (action: () => Promise<Health | unknown>) => {
    setActionError(null);
    try {
      const result = await action();
      if (result && typeof result === "object" && "status" in result) onHealth(result as Health);
    } catch (e) {
      setActionError(errorText(e));
    }
  };

  const use = (modelId: string, modelFile: string) => run(() => loadModel(modelId, modelFile));

  const remove = (model: LocalModel) => {
    if (!window.confirm(`${model.id} diskten silinsin mi? (${formatBytes(model.size)})`)) return;
    run(async () => {
      await deleteLocalModel(model.id);
      refreshLocal();
    });
  };

  const isActive = (modelId: string, modelFile: string) =>
    health.model === modelId && (health.model_file ?? "") === modelFile;

  const cached = new Set(local?.flatMap((m) => m.options.map((o) => `${m.id}|${o.model_file}`)));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Modeller" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>Modeller</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Kapat">
            ×
          </button>
        </header>

        <ActiveModel health={health} onCancel={() => run(cancelDownload)} />
        {actionError && <p className="notice notice-error">{actionError}</p>}

        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "local"} onClick={() => setTab("local")}>
            İndirilenler
          </button>
          <button role="tab" aria-selected={tab === "hub"} onClick={() => setTab("hub")}>
            Hub'da ara
          </button>
        </div>

        <div className="modal-body">
          {tab === "local" ? (
            <LocalList
              models={local}
              health={health}
              busy={busy}
              isActive={isActive}
              onUse={use}
              onDelete={remove}
              onBrowse={() => setTab("hub")}
            />
          ) : (
            <HubSearch health={health} busy={busy} cached={cached} isActive={isActive} onUse={use} />
          )}
        </div>
      </div>
    </div>
  );
}

function ActiveModel({ health, onCancel }: { health: Health; onCancel: () => void }) {
  const p = health.progress;
  const percent = p && p.total ? Math.floor((p.downloaded / p.total) * 100) : 0;
  return (
    <section className="active-model">
      <div className="active-name">
        <span className={`dot dot-${health.status}`} />
        <strong>{health.model}</strong>
        {health.model_file && <span className="muted"> · {variantName(health.model_file)}</span>}
      </div>
      <div className="muted small">
        {
          {
            downloading: "İndiriliyor",
            loading: "Belleğe yükleniyor…",
            ready: `Hazır · ${health.engine} · ${health.device === "cuda" ? "GPU" : "CPU"}`,
            error: "Yüklenemedi",
          }[health.status]
        }
      </div>
      {health.status === "downloading" && (
        <div className="progress-row">
          <div className="progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${percent}%` }} />
          </div>
          <span className="small">
            %{percent}
            {p && ` · ${formatBytes(p.downloaded)} / ${formatBytes(p.total)}`}
          </span>
          <button className="btn" onClick={onCancel}>
            İptal
          </button>
        </div>
      )}
      {health.error && (
        <p className={`notice ${health.status === "error" ? "notice-error" : "notice-warn"}`}>{health.error}</p>
      )}
    </section>
  );
}

function LocalList({
  models,
  health,
  busy,
  isActive,
  onUse,
  onDelete,
  onBrowse,
}: {
  models: LocalModel[] | null;
  health: Health;
  busy: boolean;
  isActive: (id: string, file: string) => boolean;
  onUse: (id: string, file: string) => void;
  onDelete: (m: LocalModel) => void;
  onBrowse: () => void;
}) {
  if (!models) return <p className="muted">Yükleniyor…</p>;
  if (!models.length)
    return (
      <p className="muted">
        Henüz indirilmiş model yok.{" "}
        <button className="link" onClick={onBrowse}>
          Hub'da arayın
        </button>
        .
      </p>
    );

  return (
    <ul className="model-list">
      {models.map((m) => {
        const inUse = m.options.some((o) => isActive(m.id, o.model_file));
        return (
          <li key={m.id} className="model-card">
            <div className="model-card-head">
              <strong className="model-id">{m.id}</strong>
              <span className="muted small">{formatBytes(m.size)}</span>
              <button
                className="icon-btn danger"
                onClick={() => onDelete(m)}
                disabled={inUse}
                title={inUse ? "Kullanımdaki model silinemez" : "Diskten sil"}
                aria-label={`${m.id} modelini sil`}
              >
                🗑
              </button>
            </div>
            {m.options.map((o) => (
              <OptionRow
                key={o.model_file}
                label={o.model_file ? variantName(o.model_file) : "Transformers"}
                size={o.size}
                kind={o.model_file ? "gguf" : "transformers"}
                health={health}
                active={isActive(m.id, o.model_file)}
                busy={busy}
                cached
                onUse={() => onUse(m.id, o.model_file)}
              />
            ))}
          </li>
        );
      })}
    </ul>
  );
}

function HubSearch({
  health,
  busy,
  cached,
  isActive,
  onUse,
}: {
  health: Health;
  busy: boolean;
  cached: Set<string>;
  isActive: (id: string, file: string) => boolean;
  onUse: (id: string, file: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HubResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setError(null);
      searchHub(query.trim(), controller.signal)
        .then((rs) => setResults(rs.filter((r) => !r.gated)))
        .catch((e) => !controller.signal.aborted && setError(errorText(e)));
    }, 400);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  return (
    <>
      <input
        className="search"
        type="search"
        autoFocus
        placeholder="Model ara: qwen, llama, gemma, gguf…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p className="notice notice-error">{error}</p>}
      {!results && !error && <p className="muted">Aranıyor…</p>}
      {results && !results.length && <p className="muted">Sonuç bulunamadı.</p>}
      <ul className="model-list">
        {results?.map((r) => (
          <li key={r.id} className="model-card">
            <button
              className="model-card-head result"
              onClick={() => setExpanded(expanded === r.id ? null : r.id)}
              aria-expanded={expanded === r.id}
            >
              <strong className="model-id">{r.id}</strong>
              {r.gguf && <span className="tag">GGUF</span>}
              {r.transformers && <span className="tag">Transformers</span>}
              <span className="muted small nowrap" title="Son 30 günde indirilme">
                ↓ {formatCount(r.downloads)}
              </span>
            </button>
            {expanded === r.id && (
              <RepoDetails modelId={r.id} health={health} busy={busy} cached={cached} isActive={isActive} onUse={onUse} />
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function RepoDetails({
  modelId,
  health,
  busy,
  cached,
  isActive,
  onUse,
}: {
  modelId: string;
  health: Health;
  busy: boolean;
  cached: Set<string>;
  isActive: (id: string, file: string) => boolean;
  onUse: (id: string, file: string) => void;
}) {
  const [repo, setRepo] = useState<RepoOptions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRepo(modelId)
      .then(setRepo)
      .catch((e) => setError(errorText(e)));
  }, [modelId]);

  if (error) return <p className="notice notice-error">{error}</p>;
  if (!repo) return <p className="muted small">Dosyalar okunuyor…</p>;

  const single = new Set(repo.gguf.filter((v) => v.parts === 1).map((v) => variantName(v.file)));
  const variants = repo.gguf.filter((v) => v.parts === 1 || !single.has(variantName(v.file)));

  const option = (file: string, label: string, size: number, kind: Kind, parts = 1) => (
    <OptionRow
      key={file || "transformers"}
      label={parts > 1 ? `${label} (${parts} parça)` : label}
      size={size}
      kind={kind}
      health={health}
      active={isActive(modelId, file)}
      busy={busy}
      cached={cached.has(`${modelId}|${file}`)}
      onUse={() => onUse(modelId, file)}
    />
  );

  return (
    <div className="options">
      {variants.length > 0 && <p className="muted small">GGUF sürümleri (küçük olan daha hızlı, büyük olan daha kaliteli):</p>}
      {variants.map((v) => option(v.file, variantName(v.file), v.size, "gguf", v.parts))}
      {repo.transformers && option("", "Transformers (tam model)", repo.transformers.size, "transformers")}
      {!repo.gguf.length && !repo.transformers && <p className="muted small">Bu depoda kullanılabilir dosya yok.</p>}
    </div>
  );
}

type Kind = "gguf" | "transformers";
type Fit = "ok" | "tight" | "over";

function estimateFit(size: number, kind: Kind, health: Health): { need: number; budget: number | null; fit: Fit } {
  const gpu = health.device === "cuda";
  const weights = kind === "transformers" && !gpu ? size * 2 : size;
  const need = weights * 1.1 + 0.5 * GB;
  const budget = gpu ? health.resources.vram_total : health.resources.ram_total;
  if (!budget) return { need, budget, fit: "ok" };
  return { need, budget, fit: need > budget ? "over" : need > budget * 0.8 ? "tight" : "ok" };
}

function OptionRow({
  label,
  size,
  kind,
  health,
  active,
  busy,
  cached,
  onUse,
}: {
  label: string;
  size: number;
  kind: Kind;
  health: Health;
  active: boolean;
  busy: boolean;
  cached: boolean;
  onUse: () => void;
}) {
  const { need, budget, fit } = estimateFit(size, kind, health);
  const gpu = health.device === "cuda";
  const fitText = {
    ok: null,
    tight: `Sınırda: ~${formatBytes(need)} gerekir, ${gpu ? "GPU belleği" : "RAM"} ${formatBytes(budget ?? 0)}.`,
    over: `${gpu ? "GPU belleğine" : "RAM'e"} sığmayabilir: ~${formatBytes(need)} gerekir, ${formatBytes(budget ?? 0)} var.`,
  }[fit];

  return (
    <div className={`option ${active ? "option-active" : ""}`}>
      <div className="option-main">
        <span className="option-label">{label}</span>
        <span className="muted small">
          {formatBytes(size)}
          {cached ? " · indirildi" : ""}
        </span>
        {fitText && <span className={`small fit-${fit}`}>{fitText}</span>}
      </div>
      {active ? (
        <span className="tag tag-active">Kullanımda</span>
      ) : (
        <button className="btn btn-primary" onClick={onUse} disabled={busy}>
          {cached ? "Kullan" : "İndir ve kullan"}
        </button>
      )}
    </div>
  );
}
