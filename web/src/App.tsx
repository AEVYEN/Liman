import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchHealth, streamChat, type Health, type Message, type Status } from "./api";
import ModelPanel from "./ModelPanel";
import {
  loadChats,
  loadSettings,
  newChat,
  saveChats,
  saveSettings,
  type Chat,
  type Settings,
} from "./storage";

export default function App() {
  const [chats, setChats] = useState<Chat[]>(() => {
    const stored = loadChats();
    return stored.length ? stored : [newChat()];
  });
  const [activeId, setActiveId] = useState(() => chats[0].id);
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const active = chats.find((c) => c.id === activeId) ?? chats[0];
  const ready = health?.status === "ready";

  useEffect(() => {
    saveChats(chats);
  }, [chats]);
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const pollGen = useRef(0);
  const pollTimer = useRef<number | undefined>(undefined);
  const schedule = useCallback((h: Health | null) => {
    const gen = ++pollGen.current;
    window.clearTimeout(pollTimer.current);
    const delay = h ? POLL_MS[h.status] : 3000;
    pollTimer.current = window.setTimeout(async () => {
      try {
        const next = await fetchHealth();
        if (gen !== pollGen.current) return;
        setHealth(next);
        setHealthError(false);
        schedule(next);
      } catch {
        if (gen !== pollGen.current) return;
        setHealthError(true);
        schedule(null);
      }
    }, delay);
  }, []);

  useEffect(() => {
    pollGen.current++;
    fetchHealth()
      .then((h) => {
        setHealth(h);
        schedule(h);
      })
      .catch(() => {
        setHealthError(true);
        schedule(null);
      });
    return () => {
      pollGen.current++;
      window.clearTimeout(pollTimer.current);
    };
  }, [schedule]);

  const applyHealth = useCallback(
    (h: Health) => {
      setHealth(h);
      setHealthError(false);
      schedule(h);
    },
    [schedule],
  );

  const updateChat = useCallback((id: string, fn: (chat: Chat) => Chat) => {
    setChats((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));
  }, []);

  const send = async (text: string) => {
    const chatId = active.id;
    const history: Message[] = [...active.messages, { role: "user", content: text }];
    const request: Message[] = settings.systemPrompt.trim()
      ? [{ role: "system", content: settings.systemPrompt.trim() }, ...history]
      : history;

    updateChat(chatId, (c) => ({
      ...c,
      title: c.messages.length ? c.title : text.slice(0, 48),
      messages: [...history, { role: "assistant", content: "" }],
      updatedAt: Date.now(),
    }));
    setError(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const appendToReply = (delta: string) =>
      updateChat(chatId, (c) => {
        const messages = [...c.messages];
        const last = messages[messages.length - 1];
        messages[messages.length - 1] = { ...last, content: last.content + delta };
        return { ...c, messages };
      });

    try {
      await streamChat(
        request,
        { temperature: settings.temperature, maxTokens: settings.maxTokens },
        controller.signal,
        appendToReply,
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : String(e));
        updateChat(chatId, (c) => {
          const last = c.messages[c.messages.length - 1];
          return last?.role === "assistant" && !last.content
            ? { ...c, messages: c.messages.slice(0, -1) }
            : c;
        });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const createChat = () => {
    if (!active.messages.length) return setSidebarOpen(false);
    const chat = newChat();
    setChats((cs) => [chat, ...cs]);
    setActiveId(chat.id);
    setSidebarOpen(false);
  };

  const deleteChat = (id: string) => {
    const rest = chats.filter((c) => c.id !== id);
    const next = rest.length ? rest : [newChat()];
    setChats(next);
    if (id === active.id) setActiveId(next[0].id);
  };

  const sortedChats = [...chats].sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <div className={`layout ${sidebarOpen ? "sidebar-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">⚓ Liman</div>
        <button className="new-chat" onClick={createChat} disabled={streaming}>
          + Yeni sohbet
        </button>
        <nav className="chat-list">
          {sortedChats.map((c) => (
            <div key={c.id} className={`chat-item ${c.id === active.id ? "active" : ""}`}>
              <button
                className="chat-title"
                onClick={() => {
                  setActiveId(c.id);
                  setSidebarOpen(false);
                }}
                disabled={streaming}
                title={c.title}
              >
                {c.title}
              </button>
              <button
                className="chat-delete"
                onClick={() => deleteChat(c.id)}
                disabled={streaming}
                aria-label="Sohbeti sil"
              >
                ×
              </button>
            </div>
          ))}
        </nav>
      </aside>
      <div className="scrim" onClick={() => setSidebarOpen(false)} />

      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Menü">
            ☰
          </button>
          <StatusBadge health={health} unreachable={healthError} onClick={() => setModelsOpen(true)} />
          <button className="icon-btn" onClick={() => setSettingsOpen((o) => !o)} aria-label="Ayarlar">
            ⚙
          </button>
        </header>

        {modelsOpen && health && (
          <ModelPanel health={health} onHealth={applyHealth} onClose={() => setModelsOpen(false)} />
        )}

        {settingsOpen && <SettingsPanel settings={settings} onChange={setSettings} health={health} />}

        <MessageList
          messages={active.messages}
          streaming={streaming}
          ready={ready}
          onOpenModels={() => setModelsOpen(true)}
        />

        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => setError(null)} aria-label="Kapat">
              ×
            </button>
          </div>
        )}

        <Composer
          disabled={!ready}
          streaming={streaming}
          onSend={send}
          onStop={() => abortRef.current?.abort()}
        />
      </main>
    </div>
  );
}

const POLL_MS: Record<Status, number> = { downloading: 1000, loading: 2000, ready: 15000, error: 15000 };

function downloadPercent(health: Health): number {
  const p = health.progress;
  return p && p.total ? Math.floor((p.downloaded / p.total) * 100) : 0;
}

function StatusBadge({
  health,
  unreachable,
  onClick,
}: {
  health: Health | null;
  unreachable: boolean;
  onClick: () => void;
}) {
  if (unreachable) return <div className="status status-error">API'ye ulaşılamıyor</div>;
  if (!health) return <div className="status">Bağlanıyor…</div>;
  const label = {
    downloading: `İndiriliyor %${downloadPercent(health)}`,
    loading: "Model yükleniyor…",
    ready: health.device === "cuda" ? "Hazır · GPU" : "Hazır · CPU",
    error: "Model yüklenemedi",
  }[health.status];
  return (
    <button
      className={`status status-${health.status}`}
      onClick={onClick}
      title={health.error ?? "Modeli değiştir"}
    >
      <span className="dot" />
      <span className="model-name">{health.model}</span>
      {health.error && health.status === "ready" && <span className="status-warn">⚠</span>}
      <span className="status-label">{label}</span>
      <span className="status-caret">▾</span>
    </button>
  );
}

function SettingsPanel({
  settings,
  onChange,
  health,
}: {
  settings: Settings;
  onChange: (s: Settings) => void;
  health: Health | null;
}) {
  return (
    <section className="settings">
      <label>
        Sistem istemi
        <textarea
          rows={3}
          value={settings.systemPrompt}
          onChange={(e) => onChange({ ...settings, systemPrompt: e.target.value })}
        />
      </label>
      <div className="settings-row">
        <label>
          <span className="label-row">
            Sıcaklık: {settings.temperature.toFixed(1)}
            <Hint label="Sıcaklık nedir?">
              <p>Modelin kelime seçerken ne kadar rastgele davranacağını belirler.</p>
              <ul>
                <li>
                  <b>0</b>: Hep en olası kelimeyi seçer; aynı soruya aynı yanıtı verir. Kod ve bilgi soruları için.
                </li>
                <li>
                  <b>0.7</b>: Dengeli, doğal sohbet.
                </li>
                <li>
                  <b>1.0+</b>: Daha yaratıcı ve çeşitli; çok yükselirse yanıtlar anlamsızlaşabilir.
                </li>
              </ul>
            </Hint>
          </span>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={settings.temperature}
            onChange={(e) => onChange({ ...settings, temperature: Number(e.target.value) })}
          />
        </label>
        <label>
          <span className="label-row">
            Maks. yanıt uzunluğu (token)
            <Hint label="Maks. yanıt uzunluğu nedir?">
              <p>Modelin tek bir yanıtta en fazla kaç token üreteceğini belirler; bir süre değil, uzunluk sınırıdır.</p>
              <ul>
                <li>Bir token kabaca bir kelime parçasıdır; Türkçede bir kelime ortalama 2–3 token eder.</li>
                <li>Sınıra ulaşılırsa yanıt cümlenin ortasında kesilebilir.</li>
                <li>Düşük değer yanıtı kısaltır; CPU'da bekleme süresini de azaltır.</li>
              </ul>
            </Hint>
          </span>
          <input
            type="number"
            min={16}
            max={health?.defaults.max_context ?? 32768}
            value={settings.maxTokens}
            onChange={(e) => onChange({ ...settings, maxTokens: Number(e.target.value) || 1 })}
          />
        </label>
      </div>
      {health && (
        <p className="settings-meta">
          Motor: {health.engine}
          {health.model_file ? ` · ${health.model_file}` : ""} · Bağlam: {health.defaults.max_context} token
        </p>
      )}
    </section>
  );
}

function Hint({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="hint" tabIndex={0} aria-label={label} onClick={(e) => e.preventDefault()}>
      ⓘ
      <span className="hint-bubble" role="tooltip">
        {children}
      </span>
    </span>
  );
}

function MessageList({
  messages,
  streaming,
  ready,
  onOpenModels,
}: {
  messages: Message[];
  streaming: boolean;
  ready: boolean;
  onOpenModels: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  if (!messages.length) {
    return (
      <div className="empty">
        <div className="empty-logo">⚓</div>
        <h1>Limana hoş geldiniz</h1>
        <p>{ready ? "Bir şey sorarak başlayın." : "Model hazırlanıyor; ilk çalıştırmada indirme birkaç dakika sürebilir."}</p>
        <button className="link" onClick={onOpenModels}>
          Modeli değiştir
        </button>
      </div>
    );
  }

  return (
    <div className="messages">
      {messages.map((m, i) => {
        const pending = streaming && i === messages.length - 1 && m.role === "assistant";
        return (
          <div key={i} className={`message ${m.role}`}>
            {m.role === "assistant" ? (
              m.content ? (
                <div className="markdown">
                  <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>
                </div>
              ) : (
                pending && <span className="typing">●●●</span>
              )
            ) : (
              <div className="bubble">{m.content}</div>
            )}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

function Composer({
  disabled,
  streaming,
  onSend,
  onStop,
}: {
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    const value = text.trim();
    if (!value || disabled || streaming) return;
    setText("");
    onSend(value);
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        value={text}
        rows={1}
        placeholder={disabled ? "Model hazır olduğunda yazabilirsiniz…" : "Mesajınızı yazın…"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {streaming ? (
        <button type="button" className="send stop" onClick={onStop}>
          Durdur
        </button>
      ) : (
        <button type="submit" className="send" disabled={disabled || !text.trim()}>
          Gönder
        </button>
      )}
    </form>
  );
}
