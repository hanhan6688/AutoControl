import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles.css'
import App from './App.vue'
import { initializeApiBaseUrl } from './api'
import { router } from './router'

function bootstrap() {
  const app = createApp(App)
  app.config.errorHandler = (error, instance, info) => {
    console.error('[Vue error]', { error, instance, info })
  }
  app.use(createPinia()).use(ElementPlus).use(router).mount('#app')

  initializeApiBaseUrl().catch((error) => {
    console.error('[API discovery failed]', error)
  })
}

bootstrap()
