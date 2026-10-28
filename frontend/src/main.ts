import naive from 'naive-ui'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import './assets/apple-glass.css'
import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import { router } from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)

// session 过期/被撤销时,清除登录状态并导回登录页
setUnauthorizedHandler(() => {
  useAuthStore().reset()
  if (router.currentRoute.value.name !== 'login') {
    router.push({ name: 'login' })
  }
})

app.mount('#app')
