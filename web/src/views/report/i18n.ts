/**
 * Translations for the audit report.
 *
 * Keep this file flat and explicit — no nested namespaces, no key fallback
 * chains. The audit report has a fixed set of strings; if a translation is
 * missing for a non-English locale we fall back to English silently.
 *
 * Adding a new language: add a new entry to `dict` and translate every key.
 * Adding a new string: add the key to `STRINGS` (the source of truth for
 * type completeness) and translate it for every language. TypeScript will
 * flag any locale that doesn't cover the key.
 */

export type LocaleCode = "en" | "pl";

const STRINGS = {
  // Cover page
  audit_report_title: "AI Visibility Audit",
  prepared_for: "Prepared for",
  reporting_period: "Reporting period",
  generated_on: "Generated",
  single_run_label: "Single run",

  // Executive summary
  exec_summary: "Executive summary",
  exec_summary_visibility:
    "Your brand was mentioned in {pct} of {total} non-branded AI responses across this period.",
  exec_summary_recommendation:
    "Of those mentions, the AI explicitly recommended your brand {rec_pct} of the time.",
  exec_summary_sentiment_pos:
    "Sentiment was overwhelmingly positive — {pos} of {total} mentions.",
  exec_summary_sentiment_mixed:
    "Sentiment was mixed: {pos} positive, {neu} neutral, {neg} negative.",
  exec_summary_sentiment_neg:
    "Sentiment skewed negative: {neg} of {total} mentions were negative.",
  exec_summary_no_mentions:
    "Your brand was not mentioned in any non-branded AI response in this window — there is no recommendation or sentiment data to report.",

  // KPI labels
  kpi_visibility: "Visibility",
  kpi_recommendation: "Recommendation",
  kpi_citation: "Citation",
  kpi_positive_sentiment: "Positive sentiment",
  kpi_visibility_hint: "of responses mention you",
  kpi_recommendation_hint: "of responses recommend you",
  kpi_citation_hint: "of responses cite your pages",
  kpi_positive_sentiment_hint: "of mentions are positive",
  vs_prior_period: "vs previous period",

  // Brand awareness
  brand_awareness_title: "Brand awareness — when users ask about you by name",
  brand_awareness_description:
    "Brand-intent prompts grouped by what the AI said about you. Negative answers come first because they need attention now.",
  brand_awareness_summary:
    "{prompts} brand-intent prompts produced {responses} responses. {pos} positive · {neu} neutral · {neg} negative · recommended in {rec_pct} of responses.",
  group_negative: "Negative",
  group_neutral: "Neutral",
  group_positive: "Positive",
  group_not_mentioned: "Not mentioned",
  no_brand_intent_prompts:
    "No brand-intent prompts ran in this period. Add a few prompts asking about your brand by name to populate this section.",

  // Per-source
  per_source_title: "Per-source breakdown",
  per_source_description: "How each AI assistant treats your brand.",
  col_source: "Source",
  col_responses: "Responses",
  col_visibility: "Visibility",
  col_citation: "Citation",
  col_sentiment: "Sentiment",

  // Per-source short summaries. One small card per source above
  // the data table. Each card has a strength pill (relative to the
  // overall window visibility) and a one- or two-sentence prose summary.
  per_source_pill_strong: "Strong",
  per_source_pill_average: "Average",
  per_source_pill_weak: "Weak",
  per_source_pill_absent: "Absent",
  per_source_pill_no_data: "No data",
  per_source_summary_visibility:
    "Your brand was mentioned in {pct} of {total} responses ({mentioned} mentions).",
  per_source_summary_absent:
    "Your brand was not mentioned in any of the {total} responses from this source.",
  per_source_summary_no_data:
    "No responses from this source in the period.",
  per_source_summary_above_avg:
    "That's notably above the overall {overall_pct} average across sources.",
  per_source_summary_below_avg:
    "That's notably below the overall {overall_pct} average across sources.",
  per_source_summary_recommendation:
    "{rec_pct} of responses include an explicit recommendation.",
  per_source_summary_no_recommendation:
    "No explicit recommendations on this source.",
  per_source_summary_sentiment_pos:
    "Sentiment is positive ({pos}+ / {neu}~).",
  per_source_summary_sentiment_mixed:
    "Sentiment is mixed: {pos}+ / {neu}~ / {neg}−.",
  per_source_summary_sentiment_neg:
    "Sentiment skews negative: {neg}− / {neu}~ / {pos}+.",

  // Citations
  citations_title: "Top cited domains",
  citations_description:
    "Share of responses that included a link to this domain. Measures linking behavior — different from how often a brand is named in the answer text (see the competitive landscape below).",
  col_domain: "Domain",
  col_citations: "Citations",
  col_share: "Share",
  badge_you: "you",

  // Competitor visibility
  competitor_title: "Competitive landscape",
  competitor_description:
    "Share of responses that named each brand in the answer text — counted across non-brand-intent prompts only (questions that don't already ask about a specific brand). A brand can be named without being linked, and vice versa, so these numbers will differ from the cited-domains table above.",
  col_brand: "Brand",
  col_mentions: "Mentions",

  // Samples
  samples_title: "Sample AI responses",
  samples_description:
    "A handful of representative answers — picked to surface negative tone, recommendations, and citations of your pages where available.",
  sample_prompt_label: "Prompt",
  sample_source_label: "Source",
  sample_status_mentioned: "Mentioned",
  sample_status_not_mentioned: "Not mentioned",
  sample_status_recommended: "Recommended",
  sample_status_negative: "Negative",
  sample_status_positive: "Positive",
  sample_status_neutral: "Neutral",
  sample_cited_label: "Cited",

  // Advanced sections
  tier_advanced_badge: "Advanced",
  tier_simple_badge: "Simple",
  recs_title: "Top opportunities",
  recs_description:
    "Prompts where competitors are mentioned but you aren't — winnable surface area, with concrete next steps.",
  recs_score_label: "Opportunity",
  rec_kind_get_cited: "Get cited",
  rec_kind_publish_comparison: "Publish comparison",
  rec_kind_target_query: "Target query",
  rec_kind_publish_content: "Publish content",
  citation_gap_title: "Citation gap",
  citation_gap_description:
    "Domains AIs cite when they answer category questions and don't mention you — content / authority gaps.",
  citation_gap_owner_third_party: "third-party",
  search_terms_title: "Search-term frequency",
  search_terms_description:
    "Queries the AIs actually issued during grounding. The terms AIs gravitate to in your category.",
  col_term: "Term",
  col_count: "Count",
  col_prompts: "Prompts",
  col_sources: "Sources",

  // Footer
  prepared_with: "Prepared with",
  product_label: "AI Visibility Audit",

  // Confidentiality
  confidential_badge: "Confidential",
  confidential_notice:
    "Confidential — prepared for {brand}. Not for distribution outside the recipient organization.",
  confidential_footer: "Confidential — not for redistribution.",
} as const;

type StringKey = keyof typeof STRINGS;

const dict: Record<LocaleCode, Record<StringKey, string>> = {
  en: STRINGS,
  pl: {
    audit_report_title: "Audyt widoczności w AI",
    prepared_for: "Przygotowano dla",
    reporting_period: "Zakres raportu",
    generated_on: "Wygenerowano",
    single_run_label: "Pojedynczy benchmark",

    exec_summary: "Podsumowanie",
    exec_summary_visibility:
      "Twoja marka została wymieniona w {pct} z {total} odpowiedzi AI niezwiązanych z marką w tym okresie.",
    exec_summary_recommendation:
      "Spośród tych wystąpień AI wprost zarekomendowało Twoją markę w {rec_pct} przypadków.",
    exec_summary_sentiment_pos:
      "Wydźwięk był głównie pozytywny — {pos} z {total} wystąpień.",
    exec_summary_sentiment_mixed:
      "Wydźwięk był mieszany: {pos} pozytywnych, {neu} neutralnych, {neg} negatywnych.",
    exec_summary_sentiment_neg:
      "Wydźwięk był negatywny: {neg} z {total} wystąpień było negatywnych.",
    exec_summary_no_mentions:
      "Twoja marka nie pojawiła się w żadnej odpowiedzi AI niezwiązanej z marką w tym okresie — brak danych o rekomendacji i wydźwięku.",

    kpi_visibility: "Widoczność",
    kpi_recommendation: "Rekomendacja",
    kpi_citation: "Cytowania",
    kpi_positive_sentiment: "Wydźwięk pozytywny",
    kpi_visibility_hint: "odpowiedzi wymienia Twoją markę",
    kpi_recommendation_hint: "odpowiedzi rekomenduje Twoją markę",
    kpi_citation_hint: "odpowiedzi cytuje Twoje strony",
    kpi_positive_sentiment_hint: "wystąpień ma wydźwięk pozytywny",
    vs_prior_period: "wzgl. poprzedniego okresu",

    brand_awareness_title:
      "Świadomość marki — gdy użytkownicy pytają o Ciebie po nazwie",
    brand_awareness_description:
      "Prompty z intencją marki, pogrupowane według tego, co AI o Tobie powiedziało. Odpowiedzi negatywne są na początku — to one wymagają najszybszej reakcji.",
    brand_awareness_summary:
      "{prompts} promptów z intencją marki, {responses} odpowiedzi. {pos} pozytywnych · {neu} neutralnych · {neg} negatywnych · rekomendacja w {rec_pct} odpowiedzi.",
    group_negative: "Negatywne",
    group_neutral: "Neutralne",
    group_positive: "Pozytywne",
    group_not_mentioned: "Bez wymienienia",
    no_brand_intent_prompts:
      "W tym okresie nie uruchomiono żadnych promptów z intencją marki. Dodaj kilka promptów pytających o Twoją markę po nazwie, aby zasilić tę sekcję.",

    per_source_title: "Według źródła AI",
    per_source_description:
      "Jak każde z AI traktuje Twoją markę.",
    per_source_pill_strong: "Mocne",
    per_source_pill_average: "Średnie",
    per_source_pill_weak: "Słabe",
    per_source_pill_absent: "Brak",
    per_source_pill_no_data: "Brak danych",
    per_source_summary_visibility:
      "Twoja marka pojawiła się w {pct} z {total} odpowiedzi ({mentioned} wystąpień).",
    per_source_summary_absent:
      "Twoja marka nie pojawiła się w żadnej z {total} odpowiedzi z tego źródła.",
    per_source_summary_no_data:
      "W tym okresie brak odpowiedzi z tego źródła.",
    per_source_summary_above_avg:
      "To zauważalnie powyżej ogólnej średniej {overall_pct} we wszystkich źródłach.",
    per_source_summary_below_avg:
      "To zauważalnie poniżej ogólnej średniej {overall_pct} we wszystkich źródłach.",
    per_source_summary_recommendation:
      "{rec_pct} odpowiedzi zawiera wprost rekomendację.",
    per_source_summary_no_recommendation:
      "Brak wprost rekomendacji na tym źródle.",
    per_source_summary_sentiment_pos:
      "Wydźwięk pozytywny ({pos}+ / {neu}~).",
    per_source_summary_sentiment_mixed:
      "Wydźwięk mieszany: {pos}+ / {neu}~ / {neg}−.",
    per_source_summary_sentiment_neg:
      "Wydźwięk negatywny: {neg}− / {neu}~ / {pos}+.",
    col_source: "Źródło",
    col_responses: "Odp.",
    col_visibility: "Widoczność",
    col_citation: "Cytowania",
    col_sentiment: "Wydźwięk",

    citations_title: "Najczęściej cytowane domeny",
    citations_description:
      "Udział odpowiedzi, w których AI zalinkowało do tej domeny. Mierzy linkowanie — to inna metryka niż wymienianie marki w treści odpowiedzi (zobacz „Konkurencja” poniżej).",
    col_domain: "Domena",
    col_citations: "Cytowania",
    col_share: "Udział",
    badge_you: "Ty",

    competitor_title: "Konkurencja",
    competitor_description:
      "Udział odpowiedzi, w których AI wymieniło markę w treści — liczone tylko na zapytaniach niemarkowych (czyli takich, które nie pytają wprost o konkretną markę). Marka może zostać wymieniona bez linku (i odwrotnie), więc liczby różnią się od tabeli „Najczęściej cytowane domeny” powyżej.",
    col_brand: "Marka",
    col_mentions: "Wystąpienia",

    samples_title: "Przykładowe odpowiedzi AI",
    samples_description:
      "Wybrane odpowiedzi — uwzględniono negatywny wydźwięk, rekomendacje i cytowania Twoich stron, jeśli były dostępne.",
    sample_prompt_label: "Prompt",
    sample_source_label: "Źródło",
    sample_status_mentioned: "Wymieniono",
    sample_status_not_mentioned: "Nie wymieniono",
    sample_status_recommended: "Zarekomendowano",
    sample_status_negative: "Negatywny",
    sample_status_positive: "Pozytywny",
    sample_status_neutral: "Neutralny",
    sample_cited_label: "Cytowane",

    tier_advanced_badge: "Zaawansowany",
    tier_simple_badge: "Podstawowy",
    recs_title: "Najlepsze szanse",
    recs_description:
      "Prompty, w których konkurenci są wymieniani, a Ty nie — pole do wygrania, z konkretnymi działaniami.",
    recs_score_label: "Szansa",
    rec_kind_get_cited: "Zdobądź cytowanie",
    rec_kind_publish_comparison: "Opublikuj porównanie",
    rec_kind_target_query: "Wyceluj w frazę",
    rec_kind_publish_content: "Opublikuj treść",
    citation_gap_title: "Luka w cytowaniach",
    citation_gap_description:
      "Domeny, które AI cytują, gdy odpowiadają na pytania kategorii i nie wymieniają Cię — luki w treści / autorytecie.",
    citation_gap_owner_third_party: "zewnętrzna",
    search_terms_title: "Frazy wyszukiwań",
    search_terms_description:
      "Frazy, których AI faktycznie używały podczas groundingu. Słowa, do których AI ciążą w Twojej kategorii.",
    col_term: "Fraza",
    col_count: "Liczba",
    col_prompts: "Prompty",
    col_sources: "Źródła",

    prepared_with: "Przygotowano z użyciem",
    product_label: "AI Visibility Audit",

    confidential_badge: "Poufne",
    confidential_notice:
      "Poufne — przygotowano dla {brand}. Nie do dystrybucji poza organizacją odbiorcy.",
    confidential_footer: "Poufne — nie do dalszego udostępniania.",
  },
};

const SUPPORTED: LocaleCode[] = ["en", "pl"];

export function resolveLocale(code: string | null | undefined): LocaleCode {
  if (!code) return "en";
  const lower = code.toLowerCase();
  return (SUPPORTED.includes(lower as LocaleCode) ? (lower as LocaleCode) : "en");
}

/**
 * Look up a translation. Falls back to English if the key is missing on
 * the active locale (shouldn't happen with the typed STRINGS source-of-truth,
 * but the fallback keeps the report rendering instead of blowing up).
 */
export function t(
  locale: LocaleCode,
  key: StringKey,
  vars: Record<string, string | number> = {},
): string {
  const template = dict[locale]?.[key] ?? dict.en[key] ?? key;
  return Object.entries(vars).reduce(
    (s, [k, v]) => s.replaceAll(`{${k}}`, String(v)),
    template,
  );
}

/** Locale-aware date formatter for the cover page period label. */
export function formatPeriodDate(iso: string, locale: LocaleCode): string {
  const d = new Date(iso);
  return d.toLocaleDateString(locale === "pl" ? "pl-PL" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
