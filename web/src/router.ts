import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "dashboard",
      component: () => import("./views/Dashboard.vue"),
    },
    {
      path: "/responses",
      name: "responses",
      component: () => import("./views/Responses.vue"),
    },
    {
      path: "/prompts",
      name: "prompts",
      component: () => import("./views/Prompts.vue"),
    },
    {
      path: "/prompts/:id",
      name: "prompt-detail",
      component: () => import("./views/PromptDetail.vue"),
      props: true,
    },
    {
      path: "/runs",
      name: "runs",
      component: () => import("./views/Runs.vue"),
    },
    {
      path: "/topics",
      name: "topics",
      component: () => import("./views/Topics.vue"),
    },
    {
      path: "/search-terms",
      name: "search-terms",
      component: () => import("./views/SearchTerms.vue"),
    },
    {
      path: "/runs/:id",
      name: "run-detail",
      component: () => import("./views/RunDetail.vue"),
      props: true,
    },
    {
      path: "/brands",
      name: "brands",
      component: () => import("./views/Brands.vue"),
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("./views/Settings.vue"),
    },
    {
      // Audit report. Standalone print-styled view — no app shell,
      // no sidebar — so the user can hit Print to PDF cleanly.
      path: "/report",
      name: "report",
      component: () => import("./views/Report.vue"),
      meta: { layout: "blank" },
    },
    {
      // Prompt-generator run review page.
      path: "/generator",
      name: "generator-run",
      component: () => import("./views/GeneratorRun.vue"),
    },
  ],
});
