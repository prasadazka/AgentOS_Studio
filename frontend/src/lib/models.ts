export interface ModelOption {
  id: string;
  label: string;
  provider: "OpenAI" | "Anthropic" | "Google";
  context: string; // human-readable context window
}

export const MODELS: ModelOption[] = [
  // OpenAI
  { id: "gpt-4o-mini",    label: "GPT-4o Mini",       provider: "OpenAI",    context: "128K" },
  { id: "gpt-4o",         label: "GPT-4o",            provider: "OpenAI",    context: "128K" },
  { id: "gpt-4-turbo",    label: "GPT-4 Turbo",       provider: "OpenAI",    context: "128K" },
  { id: "o3-mini",        label: "o3 Mini",            provider: "OpenAI",    context: "200K" },

  // Anthropic
  { id: "claude-sonnet-4-20250514",    label: "Claude Sonnet 4",   provider: "Anthropic", context: "200K" },
  { id: "claude-haiku-4-5-20251001",   label: "Claude Haiku 4.5",  provider: "Anthropic", context: "200K" },
  { id: "claude-opus-4-20250514",      label: "Claude Opus 4",     provider: "Anthropic", context: "200K" },

  // Google
  { id: "gemini-2.0-flash",   label: "Gemini 2.0 Flash",  provider: "Google", context: "1M" },
  { id: "gemini-2.5-pro",     label: "Gemini 2.5 Pro",    provider: "Google", context: "1M" },
  { id: "gemini-2.5-flash",   label: "Gemini 2.5 Flash",  provider: "Google", context: "1M" },
];

/** Flat list of model IDs for quick checks */
export const MODEL_IDS = MODELS.map((m) => m.id);
