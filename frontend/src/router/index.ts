import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/devices' },
  { path: '/devices', name: 'devices', component: () => import('../views/DeviceManager.vue') },
  { path: '/cases', name: 'cases', component: () => import('../views/TestCaseManager.vue') },
  { path: '/pc-autoexecute', name: 'pc-autoexecute', component: () => import('../views/PCAutoExecute.vue') },
  { path: '/api-tests', name: 'api-tests', component: () => import('../views/ApiTestManager.vue') },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

function isLazyRouteLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || '')
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(message)
}

router.onError((error, to) => {
  console.error('[Router error]', error)
  if (!isLazyRouteLoadError(error)) return

  if (to.path !== '/devices') {
    router.replace('/devices').catch((replaceError) => {
      console.error('[Router recovery failed]', replaceError)
    })
    return
  }

  if (typeof window !== 'undefined') {
    window.location.reload()
  }
})
