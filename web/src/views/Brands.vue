<script setup lang="ts">
/**
 * Brands → self brand + competitors.
 *
 * Self brands are pinned at top. Competitors below, sorted by visibility
 * descending. Add/edit goes through a dialog. The "Mine" button on a
 * competitor flips it to self-brand status (useful when the user
 * accidentally added their own brand as a competitor).
 */
import { computed, onMounted, ref, watch } from "vue";
import {
  Loader2,
  Plus,
  Pencil,
  Trash2,
  Bookmark,
  Info as InfoIcon,
} from "lucide-vue-next";
import {
  Button,
  Card,
  CardHeader,
  Badge,
  Input,
  Select,
  Switch,
  Dialog,
  Tooltip,
} from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { Brand, BrandComparisonEntry, GeoCountry, GeoLanguage } from "@/api/types";
import { pct } from "@/lib/format";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();

const brands = ref<Brand[]>([]);
const comparisonEntries = ref<BrandComparisonEntry[]>([]);
const comparisonTotal = ref(0);
const countries = ref<GeoCountry[]>([]);
const languages = ref<GeoLanguage[]>([]);
const loading = ref(true);
const showForm = ref(false);
const editingId = ref<number | null>(null);

interface BrandFormState {
  name: string;
  domains: string;
  aliases: string;
  is_self: boolean;
  country_code: string;
  language_code: string;
}

function emptyForm(): BrandFormState {
  return {
    name: "",
    domains: "",
    aliases: "",
    is_self: false,
    country_code: "US",
    language_code: "en",
  };
}

const form = ref<BrandFormState>(emptyForm());

watch(
  () => form.value.country_code,
  (newCode, oldCode) => {
    if (oldCode === undefined || newCode === oldCode) return;
    const country = countries.value.find((c) => c.country_code === newCode);
    if (country) form.value.language_code = country.default_language_code;
  },
);

async function loadAll() {
  loading.value = true;
  try {
    const [b, comp, geo] = await Promise.all([
      api.listBrands(),
      api.comparison(),
      api.geoOptions(),
    ]);
    brands.value = b;
    comparisonEntries.value = comp.brands;
    comparisonTotal.value = comp.total_responses;
    countries.value = geo.countries;
    languages.value = geo.languages;
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load brands");
  } finally {
    loading.value = false;
  }
}

const entryById = computed(() => {
  const m = new Map<number, BrandComparisonEntry>();
  for (const e of comparisonEntries.value) m.set(e.brand_id, e);
  return m;
});

const selfBrands = computed(() => brands.value.filter((b) => b.is_self));
const competitors = computed(() => brands.value.filter((b) => !b.is_self));

const sortedCompetitors = computed(() =>
  [...competitors.value].sort((a, b) => {
    const sa = entryById.value.get(a.id)?.metrics.visibility_rate ?? 0;
    const sb = entryById.value.get(b.id)?.metrics.visibility_rate ?? 0;
    return sb - sa;
  }),
);

const countryOptions = computed(() =>
  countries.value.map((c) => ({ label: c.name, value: c.country_code })),
);
const languageOptions = computed(() =>
  languages.value.map((l) => ({ label: l.name, value: l.code })),
);

function openCreate() {
  editingId.value = null;
  form.value = emptyForm();
  showForm.value = true;
}

function openEdit(brand: Brand) {
  editingId.value = brand.id;
  form.value = {
    name: brand.name,
    domains: brand.domains.join(", "),
    aliases: brand.aliases.join(", "),
    is_self: brand.is_self,
    country_code: brand.country_code,
    language_code: brand.language_code,
  };
  showForm.value = true;
}

async function submitForm() {
  const payload = {
    name: form.value.name,
    domains: form.value.domains.split(",").map((d) => d.trim()).filter(Boolean),
    aliases: form.value.aliases.split(",").map((a) => a.trim()).filter(Boolean),
    is_self: form.value.is_self,
    country_code: form.value.country_code,
    language_code: form.value.language_code,
  };
  try {
    if (editingId.value === null) {
      await api.createBrand(payload);
      toasts.success("Brand created");
    } else {
      await api.updateBrand(editingId.value, payload);
      toasts.success("Brand updated");
    }
    showForm.value = false;
    editingId.value = null;
    form.value = emptyForm();
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to save brand");
  }
}

async function deleteBrand(id: number) {
  if (!confirm("Delete this brand? Historical analyses are preserved.")) return;
  try {
    await api.deleteBrand(id);
    toasts.success("Brand deleted");
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to delete brand");
  }
}

async function toggleSelf(brand: Brand) {
  try {
    await api.updateBrand(brand.id, { is_self: !brand.is_self });
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to update brand");
  }
}

function rateOf(b: Brand): number {
  return entryById.value.get(b.id)?.metrics.visibility_rate ?? 0;
}
function mentionsOf(b: Brand): number {
  return entryById.value.get(b.id)?.metrics.brand_mentioned ?? 0;
}

onMounted(loadAll);
</script>

<template>
  <header class="flex items-end justify-between mb-7 gap-4">
    <div>
      <p class="label-eyebrow">Configure</p>
      <h1 class="font-display text-3xl tracking-tight mt-1">Brands</h1>
      <p class="text-sm text-[var(--color-fg-2)] mt-2">
        Track your brand and the competitors you want to compare against.
      </p>
    </div>
    <Button variant="primary" @click="openCreate">
      <Plus class="h-3.5 w-3.5" />
      Add brand
    </Button>
  </header>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <Card v-else-if="brands.length === 0" class="text-center py-16">
    <Bookmark class="h-10 w-10 mx-auto text-[var(--color-fg-muted)] stroke-[1.4]" />
    <h3 class="font-display text-lg mt-4">No brands yet</h3>
    <p class="text-sm text-[var(--color-fg-2)] mt-2 max-w-md mx-auto">
      Add your brand and the competitors you want to track.
    </p>
    <Button variant="primary" class="mt-6" @click="openCreate">
      <Plus class="h-3.5 w-3.5" />
      Add your first brand
    </Button>
  </Card>

  <template v-else>
    <!-- Self brands -->
    <Card v-if="selfBrands.length" class="mb-5">
      <CardHeader title="Your brands" subtitle="One per market — duplicate to track in multiple countries">
        <template #actions>
          <Tooltip content="Visibility rate: percentage of non-brand-intent prompts where this brand was mentioned.">
            <span tabindex="0" class="text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] cursor-help">
              <InfoIcon class="h-3.5 w-3.5" />
            </span>
          </Tooltip>
        </template>
      </CardHeader>

      <ul>
        <li
          v-for="(b, i) in selfBrands"
          :key="b.id"
          :class="[
            'flex items-center gap-4 py-3.5',
            i > 0 ? 'border-t border-[var(--color-line)]' : '',
          ]"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <Badge tone="accent">SELF</Badge>
              <span class="font-medium text-[var(--color-fg)]">{{ b.name }}</span>
              <span class="text-xs text-[var(--color-fg-muted)]">
                {{ b.country_name }} · {{ b.language_name }}
              </span>
            </div>
            <p class="text-xs text-[var(--color-fg-2)] mt-1 truncate font-mono">
              <span v-if="b.domains.length">{{ b.domains.join(", ") }}</span>
              <span v-if="b.aliases.length"> · {{ b.aliases.join(", ") }}</span>
              <span v-if="!b.domains.length && !b.aliases.length" class="italic">
                no domains or aliases
              </span>
            </p>
          </div>
          <div class="text-right tabular-nums">
            <p class="font-display text-xl leading-none tracking-tight">
              {{ pct(rateOf(b)) }}
            </p>
            <p class="text-[10.5px] text-[var(--color-fg-muted)] mt-1">
              {{ mentionsOf(b) }} / {{ comparisonTotal }}
            </p>
          </div>
          <div class="w-24 h-[5px] rounded-full bg-[var(--color-surface-2)] overflow-hidden">
            <div
              class="h-full bg-[var(--color-accent)] rounded-full"
              :style="{ width: `${Math.max(2, rateOf(b) * 100)}%` }"
            />
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <Button variant="ghost" size="icon" aria-label="Edit" @click="openEdit(b)">
              <Pencil class="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Delete" @click="deleteBrand(b.id)">
              <Trash2 class="h-3.5 w-3.5 text-[var(--color-danger)]" />
            </Button>
          </div>
        </li>
      </ul>
    </Card>

    <Card v-else class="mb-5 bg-[var(--color-warning-soft)] border-[color-mix(in_srgb,var(--color-warning),transparent_70%)]">
      <p class="text-sm text-[var(--color-warning)]">
        <strong>No self-brand configured.</strong> Mark one of your brands as <em>your brand</em>
        to start tracking visibility.
      </p>
    </Card>

    <!-- Competitors -->
    <Card>
      <CardHeader title="Competitors" subtitle="Sorted by visibility rate (highest first)">
        <template #actions>
          <Tooltip content="Branded queries are excluded for a fair comparison — every brand is measured against the same pool.">
            <span tabindex="0" class="text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] cursor-help">
              <InfoIcon class="h-3.5 w-3.5" />
            </span>
          </Tooltip>
        </template>
      </CardHeader>

      <div v-if="sortedCompetitors.length === 0" class="text-sm text-[var(--color-fg-muted)] py-6 text-center">
        No competitors added yet.
      </div>
      <ul v-else>
        <li
          v-for="(b, i) in sortedCompetitors"
          :key="b.id"
          :class="[
            'flex items-center gap-4 py-2.5',
            i > 0 ? 'border-t border-[var(--color-line)]' : '',
          ]"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline gap-2">
              <span class="font-medium text-[var(--color-fg)] truncate">{{ b.name }}</span>
              <span v-if="b.domains.length" class="font-mono text-xs text-[var(--color-fg-muted)] truncate">
                {{ b.domains[0] }}
              </span>
            </div>
          </div>
          <span class="text-xs text-[var(--color-fg-muted)] tabular-nums w-20 text-right">
            {{ mentionsOf(b) }} / {{ comparisonTotal }}
          </span>
          <span class="text-sm text-[var(--color-fg)] font-medium tabular-nums w-12 text-right">
            {{ pct(rateOf(b)) }}
          </span>
          <div class="w-20 h-[4px] rounded-full bg-[var(--color-surface-2)] overflow-hidden">
            <div
              class="h-full bg-[var(--color-fg-2)] rounded-full"
              :style="{ width: `${Math.max(2, rateOf(b) * 100)}%` }"
            />
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <Button variant="ghost" size="icon" aria-label="Edit" @click="openEdit(b)">
              <Pencil class="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="sm" @click="toggleSelf(b)">Mine</Button>
            <Button variant="ghost" size="icon" aria-label="Delete" @click="deleteBrand(b.id)">
              <Trash2 class="h-3.5 w-3.5 text-[var(--color-danger)]" />
            </Button>
          </div>
        </li>
      </ul>
    </Card>
  </template>

  <!-- Add / edit dialog -->
  <Dialog
    v-model:open="showForm"
    :title="editingId === null ? 'Add brand' : 'Edit brand'"
    description="Domains and aliases drive how mentions are detected in AI assistant responses."
    size="lg"
  >
    <form @submit.prevent="submitForm" class="space-y-4">
      <div>
        <label class="label-eyebrow block mb-1.5">Brand name</label>
        <Input v-model="form.name" required />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="label-eyebrow block mb-1.5">Domains</label>
          <Input v-model="form.domains" placeholder="example.com, shop.example.com" />
          <p class="text-xs text-[var(--color-fg-muted)] mt-1">comma separated</p>
        </div>
        <div>
          <label class="label-eyebrow block mb-1.5">Aliases</label>
          <Input v-model="form.aliases" placeholder="My Brand, mybrand" />
          <p class="text-xs text-[var(--color-fg-muted)] mt-1">comma separated</p>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="label-eyebrow block mb-1.5">Country (search market)</label>
          <Select v-model="form.country_code" :options="countryOptions" />
        </div>
        <div>
          <label class="label-eyebrow block mb-1.5">Language</label>
          <Select v-model="form.language_code" :options="languageOptions" />
        </div>
      </div>
      <p class="text-xs text-[var(--color-fg-muted)] leading-snug">
        Used as the SERP location for DataForSEO and as a country hint for Bright Data. To
        track this brand in multiple countries, create one brand per market.
      </p>
      <label class="flex items-center gap-3 text-sm text-[var(--color-fg)]">
        <Switch v-model="form.is_self" />
        This is my brand
      </label>
    </form>
    <template #footer>
      <Button variant="ghost" @click="showForm = false">Cancel</Button>
      <Button variant="primary" @click="submitForm">
        {{ editingId === null ? "Create" : "Save" }}
      </Button>
    </template>
  </Dialog>
</template>
