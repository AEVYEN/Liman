export type Role = "system" | "user" | "assistant";

export interface Message {
  role: Role;
  content: string;
}

export type Status = "downloading" | "loading" | "ready" | "error";

export interface Health {
  status: Status;
  model: string;
  model_file: string | null;
  engine: string;
  device: string | null;
  error: string | null;
  progress: { downloaded: number; total: number } | null;
  resources: {
    ram_total: number | null;
    ram_available: number | null;
    vram_total: number | null;
    vram_free: number | null;
  };
  defaults: { max_context: number; max_new_tokens: number; temperature: number };
}

export interface GenerationOptions {
  temperature: number;
  maxTokens: number;
}

export interface HubResult {
  id: string;
  downloads: number;
  likes: number;
  gated: boolean;
  gguf: boolean;
  transformers: boolean;
}

export interface GgufVariant {
  file: string;
  size: number;
  parts: number;
}

export interface RepoOptions {
  id: string;
  gated: boolean;
  transformers: { size: number } | null;
  gguf: GgufVariant[];
}

export interface LocalModel {
  id: string;
  size: number;
  options: { model_file: string; size: number }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export const fetchHealth = () => request<Health>("/health");

export const searchHub = async (query: string, signal: AbortSignal) =>
  (await request<{ results: HubResult[] }>(`/api/hub/search?q=${encodeURIComponent(query)}`, { signal })).results;

export const fetchRepo = (modelId: string) =>
  request<RepoOptions>(`/api/hub/repo?model_id=${encodeURIComponent(modelId)}`);

export const fetchLocalModels = async () => (await request<{ models: LocalModel[] }>("/api/models/local")).models;

export const deleteLocalModel = (modelId: string) =>
  request<{ deleted: string }>(`/api/models/local?model_id=${encodeURIComponent(modelId)}`, { method: "DELETE" });

export const loadModel = (modelId: string, modelFile: string) =>
  request<Health>("/api/models/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, model_file: modelFile }),
  });

export const cancelDownload = () => request<Health>("/api/models/cancel", { method: "POST" });

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.error?.message ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export async function streamChat(
  messages: Message[],
  options: GenerationOptions,
  signal: AbortSignal,
  onDelta: (text: string) => void,
): Promise<void> {
  const res = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "local",
      messages,
      stream: true,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
    }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(await readError(res));

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const data = event.replace(/^data: ?/, "").trim();
      if (!data || data === "[DONE]") continue;
      const payload = JSON.parse(data);
      if (payload.error) throw new Error(payload.error.message);
      const text = payload.choices?.[0]?.delta?.content;
      if (text) onDelta(text);
    }
  }
}
