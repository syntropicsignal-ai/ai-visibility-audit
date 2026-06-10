/**
 * App entrypoint.
 *
 * Light only — there's no theme switcher and no `<html class="dark">`
 * applied. If we ever bring dark back it should go through CSS vars in
 * style.css, not a separate JS plugin.
 */
import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { router } from "./router";
import "./style.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount("#app");
