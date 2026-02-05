import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

import './tailwind.css'
import './style.css'
import './agent-builder.css'

const app = createApp(App)

// Element Plus
app.use(ElementPlus)

// Element Plus Icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
}

// Pinia
app.use(createPinia())

// Router
app.use(router)

app.mount('#app')
