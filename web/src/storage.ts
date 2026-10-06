import type { Message } from "./api";

export interface Chat {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

export interface Settings {
  systemPrompt: string;
  temperature: number;
  maxTokens: number;
}

const CHATS_KEY = "liman.chats";
const SETTINGS_KEY = "liman.settings";

export const defaultSettings: Settings = {
  systemPrompt:
    "You are a helpful assistant. Reply only in English, even if the user writes in another language. Keep answers short and simple: at most a few sentences.",
  temperature: 0.7,
  maxTokens: 1024,
};

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
  }
}

export const loadChats = () => read<Chat[]>(CHATS_KEY, []);
export const saveChats = (chats: Chat[]) => write(CHATS_KEY, chats);
const OLD_DEFAULT_PROMPTS = [
  "Sen yardımsever bir asistansın. Kullanıcının dilinde yanıt ver.",
  "You are a helpful assistant. Always reply in English. Keep answers short and simple.",
];

export function loadSettings(): Settings {
  const settings = { ...defaultSettings, ...read<Partial<Settings>>(SETTINGS_KEY, {}) };
  if (OLD_DEFAULT_PROMPTS.includes(settings.systemPrompt)) settings.systemPrompt = defaultSettings.systemPrompt;
  return settings;
}
export const saveSettings = (settings: Settings) => write(SETTINGS_KEY, settings);

export function newChat(): Chat {
  return { id: crypto.randomUUID(), title: "Yeni sohbet", messages: [], updatedAt: Date.now() };
}
