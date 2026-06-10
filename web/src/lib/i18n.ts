/**
 * App-wide i18n.
 *
 * Strings live in `src/locales/<code>.json`. The English file is the
 * source-of-truth — every other locale must cover the same keys (a
 * runtime check below logs missing keys in dev, falls back to EN at
 * lookup time so the UI never crashes).
 *
 * Usage:
 *   import { t, locale, setLocale } from "@/lib/i18n";
 *   {{ t('nav.dashboard') }}
 *   {{ t('runs.dek', { total: 42 }) }}
 *
 * Adding a string:
 *   1. Append the key to en.json
 *   2. Add a translation to every other locale file
 *   3. Reference it via t("the.key") in the view
 *
 * Adding a locale:
 *   1. Copy en.json → <code>.json, translate every value
 *   2. Add the import + register in `dict` below
 *   3. Add the code to SUPPORTED + the picker label in en.json + the
 *      new locale's own file
 *
 * The printable audit report has its own copy in
 * `src/views/report/i18n.ts`.
 */
import { ref, computed } from "vue";
import enRaw from "@/locales/en.json";
import plRaw from "@/locales/pl.json";

export type LocaleCode = "en" | "pl";

const STORAGE_KEY = "ai-visibility-audit.locale";

// Strip the underscore-prefixed metadata keys (e.g. `_comment`) so
// they never get returned by t() if someone asks for them. JSON allows
// comments via convention only; we use `_comment` as the convention.
function _strip(raw: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!k.startsWith("_")) out[k] = v;
  }
  return out;
}

const STRINGS_EN = _strip(enRaw as Record<string, string>);
const STRINGS_PL = _strip(plRaw as Record<string, string>);

// Source-of-truth key set is whatever en.json defines. We log (in dev)
// any missing translations on other locales so they don't silently
// regress as the EN copy grows.
type StringKey = keyof typeof STRINGS_EN;

const dict: Record<LocaleCode, Record<string, string>> = {
  en: STRINGS_EN,
  pl: STRINGS_PL,
};

const SUPPORTED: LocaleCode[] = ["en", "pl"];

if (import.meta.env.DEV) {
  for (const code of SUPPORTED) {
    if (code === "en") continue;
    const missing = Object.keys(STRINGS_EN).filter((k) => !(k in dict[code]));
    if (missing.length > 0) {
      console.warn(
        `[i18n] ${code}.json missing ${missing.length} keys — falling back to EN:`,
        missing,
      );
    }
  }
}

function loadLocale(): LocaleCode {
  if (typeof localStorage === "undefined") return "en";
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && SUPPORTED.includes(saved as LocaleCode)) return saved as LocaleCode;
  // First-run fallback to browser language if recognised
  const browser = (navigator?.language ?? "").slice(0, 2).toLowerCase();
  return SUPPORTED.includes(browser as LocaleCode) ? (browser as LocaleCode) : "en";
}

const _locale = ref<LocaleCode>(loadLocale());

export const locale = computed<LocaleCode>(() => _locale.value);

export function setLocale(code: LocaleCode) {
  _locale.value = code;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(STORAGE_KEY, code);
  }
  // Set the html lang attribute so screen-readers and Chrome translate
  // prompts pick up the right language.
  if (typeof document !== "undefined") {
    document.documentElement.lang = code;
  }
}

export function supportedLocales(): LocaleCode[] {
  return [...SUPPORTED];
}

/**
 * Translate a key. Falls back to English if the active locale is
 * missing it (shouldn't happen with the missing-key dev warning, but
 * defends against hot-reload edge cases). `vars` are interpolated via
 * {placeholder} syntax — same convention as the report's i18n.
 *
 * Plural form: when the value contains a literal `|` separator, the
 * left side is used for `{count} === 1`, the right side otherwise.
 * Example value: `"{count} mention | {count} mentions"`.
 */
export function t(
  key: StringKey | string,
  vars: Record<string, string | number> = {},
): string {
  const template = dict[_locale.value]?.[key] ?? dict.en[key] ?? key;

  let chosen = template;
  if (template.includes("|") && typeof vars.count === "number") {
    const [singular, plural] = template.split("|").map((s) => s.trim());
    chosen = vars.count === 1 ? singular : plural;
  }

  return Object.entries(vars).reduce(
    (s, [k, v]) => s.replaceAll(`{${k}}`, String(v)),
    chosen,
  );
}

// Initialise document lang on module load so SSR-shaped flows pick
// up the default locale immediately.
if (typeof document !== "undefined") {
  document.documentElement.lang = _locale.value;
}
