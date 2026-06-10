<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { CheckCircle2, ExternalLink, Loader2, Sparkles, Trash2 } from "lucide-vue-next";
import { Button, Dialog, Input } from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { ConfigStatus } from "@/api/types";
import { useSetupDialog } from "@/stores/setup";
import { useToasts } from "@/stores/toasts";

const { dialogOpen, close } = useSetupDialog();
const toasts = useToasts();

interface KeyField {
  key: keyof FormState;
  label: string;
  placeholder: string;
  hint: string;
  signupUrl?: string;
}

interface FormState {
  gemini_api_key: string;
  openai_api_key: string;
  exa_api_key: string;
  dataforseo_login: string;
  dataforseo_password: string;
  brightdata_api_key: string;
  brightdata_chatgpt_dataset_id: string;
  brightdata_gemini_dataset_id: string;
  brightdata_google_ai_mode_dataset_id: string;
}

const REQUIRED_FIELDS: KeyField[] = [
  {
    key: "gemini_api_key",
    label: "Gemini API key",
    placeholder: "AIza...",
    hint: "Query generation and sentiment classification.",
    signupUrl: "https://aistudio.google.com/apikey",
  },
  {
    key: "exa_api_key",
    label: "Exa API key",
    placeholder: "exa_...",
    hint: "Competitor discovery and site content during prompt generation.",
    signupUrl: "https://exa.ai",
  },
  {
    key: "dataforseo_login",
    label: "DataForSEO login",
    placeholder: "you@example.com",
    hint: "Account email shown on the DataForSEO dashboard.",
    signupUrl: "https://app.dataforseo.com/register",
  },
  {
    key: "dataforseo_password",
    label: "DataForSEO API password",
    placeholder: "•••••••",
    hint: "API password from the dashboard (not the account login).",
  },
];

const OPTIONAL_FIELDS: KeyField[] = [
  {
    key: "openai_api_key",
    label: "OpenAI API key",
    placeholder: "sk-...",
    hint: "Optional — enables the WildChat corpus stage of prompt generation (used only for embeddings).",
    signupUrl: "https://platform.openai.com/api-keys",
  },
];

const BRIGHTDATA_FIELDS: KeyField[] = [
  {
    key: "brightdata_api_key",
    label: "Bright Data API key",
    placeholder: "bd_...",
    hint: "Unlocks ChatGPT, Gemini, and Google AI Mode — the AI assistants this tool measures.",
    signupUrl: "https://brightdata.com/",
  },
  {
    key: "brightdata_chatgpt_dataset_id",
    label: "Bright Data — ChatGPT dataset ID",
    placeholder: "gd_...",
    hint: "Pre-filled with Bright Data's public default; override if yours differs.",
  },
  {
    key: "brightdata_gemini_dataset_id",
    label: "Bright Data — Gemini dataset ID",
    placeholder: "gd_...",
    hint: "Set to enable the Gemini provider; leave empty to disable.",
  },
  {
    key: "brightdata_google_ai_mode_dataset_id",
    label: "Bright Data — Google AI Mode dataset ID",
    placeholder: "gd_...",
    hint: "Recommended for Polish-market measurement (Gemini source rejects country=PL).",
  },
];

const status = ref<ConfigStatus | null>(null);
const isDemo = ref(false);
const saving = ref(false);
const demoBusy = ref(false);
const errorMsg = ref<string | null>(null);

const form = reactive<FormState>({
  gemini_api_key: "",
  openai_api_key: "",
  exa_api_key: "",
  dataforseo_login: "",
  dataforseo_password: "",
  brightdata_api_key: "",
  brightdata_chatgpt_dataset_id: "",
  brightdata_gemini_dataset_id: "",
  brightdata_google_ai_mode_dataset_id: "",
});

async function refresh() {
  try {
    const [cfg, demo] = await Promise.all([api.configStatus(), api.demoStatus()]);
    status.value = cfg;
    isDemo.value = demo.is_demo;
  } catch {
    /* leave nulls — the form still works, just no "configured" badges */
  }
}

function isConfigured(key: string): boolean {
  return Boolean(status.value?.configured?.[key]);
}

async function save() {
  saving.value = true;
  errorMsg.value = null;
  try {
    const payload: Partial<FormState> = {};
    for (const f of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS, ...BRIGHTDATA_FIELDS]) {
      const v = form[f.key].trim();
      if (v) (payload as Record<string, string>)[f.key] = v;
    }
    status.value = await api.saveConfigKeys(payload);
    for (const f of [...REQUIRED_FIELDS, ...OPTIONAL_FIELDS, ...BRIGHTDATA_FIELDS]) {
      if (form[f.key].trim()) form[f.key] = "";
    }
    if (!status.value.setup_required) {
      toasts.success("Keys saved — you're all set");
      close();
    } else {
      toasts.success("Saved");
    }
  } catch (e) {
    errorMsg.value = e instanceof ApiError ? (e.detail ?? e.message) : (e as Error).message;
  } finally {
    saving.value = false;
  }
}

async function loadDemo() {
  demoBusy.value = true;
  try {
    await api.demoSeed();
    toasts.success("Sample data loaded — exploring demo brand “Vellar”");
    // Hard reload so every view (dashboard, sidebar, banner) reflects the
    // seeded state without per-component refetch wiring.
    window.location.assign("/");
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load sample data");
    demoBusy.value = false;
  }
}

async function clearDemo() {
  demoBusy.value = true;
  try {
    await api.demoClear();
    toasts.success("Sample data cleared");
    window.location.assign("/");
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to clear sample data");
    demoBusy.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <Dialog
    v-model:open="dialogOpen"
    title="Set up AI Visibility Audit"
    description="Add your API keys to run real benchmarks — or explore with sample data first. Keys are stored locally in api/data/config.json."
    size="xl"
  >
    <div class="space-y-6">
      <!-- Sample-data path -->
      <section
        class="rounded-[var(--radius-md)] border border-[color-mix(in_srgb,var(--color-accent,var(--color-warning))_30%,transparent)] bg-[var(--color-accent-soft,var(--color-warning-soft))] p-4"
      >
        <div class="flex items-start gap-3">
          <Sparkles class="h-4 w-4 mt-0.5 shrink-0 text-[var(--color-accent,var(--color-warning))]" />
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium">Just looking around?</p>
            <p class="text-xs text-[var(--color-fg-2)] mt-1">
              Load a fictional sample dataset and explore the whole product — dashboard,
              funnel, citations, audit report — with no API keys.
            </p>
            <div class="mt-3">
              <Button
                v-if="!isDemo"
                variant="primary"
                :disabled="demoBusy"
                @click="loadDemo"
              >
                <Loader2 v-if="demoBusy" class="h-3.5 w-3.5 animate-spin" />
                <Sparkles v-else class="h-3.5 w-3.5" />
                Load sample data
              </Button>
              <Button v-else variant="ghost" :disabled="demoBusy" @click="clearDemo">
                <Loader2 v-if="demoBusy" class="h-3.5 w-3.5 animate-spin" />
                <Trash2 v-else class="h-3.5 w-3.5" />
                Clear sample data
              </Button>
            </div>
          </div>
        </div>
      </section>

      <!-- Keys form -->
      <form @submit.prevent="save" class="space-y-5">
        <div>
          <h3 class="text-sm font-semibold mb-1">Required</h3>
          <p class="text-xs text-[var(--color-fg-2)] mb-3">
            Needed for the prompt generator and core analytics.
          </p>
          <div class="space-y-3.5">
            <div v-for="f in REQUIRED_FIELDS" :key="f.key">
              <label class="flex items-center justify-between text-[13px] font-medium mb-1">
                <span>{{ f.label }}</span>
                <span
                  v-if="isConfigured(f.key)"
                  class="inline-flex items-center gap-1 text-xs text-[var(--color-success)]"
                >
                  <CheckCircle2 class="h-3.5 w-3.5" /> configured
                </span>
              </label>
              <Input
                v-model="form[f.key]"
                :placeholder="isConfigured(f.key) ? '•••••••• (leave empty to keep)' : f.placeholder"
                :type="f.key === 'dataforseo_password' || f.key.endsWith('_api_key') ? 'password' : 'text'"
                autocomplete="off"
              />
              <p class="mt-1 text-xs text-[var(--color-fg-2)]">
                {{ f.hint }}
                <a
                  v-if="f.signupUrl"
                  :href="f.signupUrl"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-0.5 ml-1 text-[var(--color-accent)] hover:underline"
                >
                  Sign up <ExternalLink class="h-3 w-3" />
                </a>
              </p>
            </div>
          </div>
        </div>

        <div>
          <h3 class="text-sm font-semibold mb-1">Optional</h3>
          <p class="text-xs text-[var(--color-fg-2)] mb-3">
            Enhances prompt generation but isn't required to run.
          </p>
          <div class="space-y-3.5">
            <div v-for="f in OPTIONAL_FIELDS" :key="f.key">
              <label class="flex items-center justify-between text-[13px] font-medium mb-1">
                <span>{{ f.label }}</span>
                <span
                  v-if="isConfigured(f.key)"
                  class="inline-flex items-center gap-1 text-xs text-[var(--color-success)]"
                >
                  <CheckCircle2 class="h-3.5 w-3.5" /> configured
                </span>
              </label>
              <Input
                v-model="form[f.key]"
                :placeholder="isConfigured(f.key) ? '•••••••• (leave empty to keep)' : f.placeholder"
                :type="f.key.endsWith('_api_key') ? 'password' : 'text'"
                autocomplete="off"
              />
              <p class="mt-1 text-xs text-[var(--color-fg-2)]">
                {{ f.hint }}
                <a
                  v-if="f.signupUrl"
                  :href="f.signupUrl"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-0.5 ml-1 text-[var(--color-accent)] hover:underline"
                >
                  Sign up <ExternalLink class="h-3 w-3" />
                </a>
              </p>
            </div>
          </div>
        </div>

        <div>
          <h3 class="text-sm font-semibold mb-1">AI assistant sources — Bright Data</h3>
          <p class="text-xs text-[var(--color-fg-2)] mb-3">
            ChatGPT, Gemini, and Google AI Mode are the main surfaces this tool
            measures. Add your Bright Data key for full coverage — without it,
            only Google AI Overview (via DataForSEO) is tracked.
          </p>
          <div class="space-y-3.5">
            <div v-for="f in BRIGHTDATA_FIELDS" :key="f.key">
              <label class="flex items-center justify-between text-[13px] font-medium mb-1">
                <span>{{ f.label }}</span>
                <span
                  v-if="isConfigured(f.key)"
                  class="inline-flex items-center gap-1 text-xs text-[var(--color-success)]"
                >
                  <CheckCircle2 class="h-3.5 w-3.5" /> configured
                </span>
              </label>
              <Input
                v-model="form[f.key]"
                :placeholder="isConfigured(f.key) ? '•••••••• (leave empty to keep)' : f.placeholder"
                :type="f.key.endsWith('_api_key') ? 'password' : 'text'"
                autocomplete="off"
              />
              <p class="mt-1 text-xs text-[var(--color-fg-2)]">
                {{ f.hint }}
                <a
                  v-if="f.signupUrl"
                  :href="f.signupUrl"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-0.5 ml-1 text-[var(--color-accent)] hover:underline"
                >
                  Sign up <ExternalLink class="h-3 w-3" />
                </a>
              </p>
            </div>
          </div>
        </div>

        <p v-if="errorMsg" class="text-sm text-[var(--color-danger)]">{{ errorMsg }}</p>
      </form>
    </div>

    <template #footer>
      <Button variant="ghost" @click="close">Close</Button>
      <Button variant="primary" :disabled="saving" @click="save">
        <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
        {{ saving ? "Saving…" : "Save keys" }}
      </Button>
    </template>
  </Dialog>
</template>
