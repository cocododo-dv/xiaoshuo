import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import "./styles/app.css";
import "./styles/design-tokens.css";
import "./styles/design-base.css";
import "./styles/shell.css";

const app = createApp(App);

app.use(createPinia());
app.mount("#app");
