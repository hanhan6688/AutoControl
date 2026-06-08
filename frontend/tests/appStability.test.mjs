import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'

const root = resolve(import.meta.dirname, '..')

function readSource(path) {
  return readFileSync(resolve(root, path), 'utf8')
}

test('frontend mounts Vue app before asynchronous backend discovery can fail', () => {
  const source = readSource('src/main.ts')
  const mountIndex = source.indexOf(".mount('#app')")
  const apiInitIndex = source.indexOf('initializeApiBaseUrl()')

  assert.notEqual(mountIndex, -1)
  assert.notEqual(apiInitIndex, -1)
  assert.ok(
    mountIndex < apiInitIndex,
    'main.ts should mount the app before initializeApiBaseUrl() starts backend discovery',
  )
  assert.doesNotMatch(source, /await\s+initializeApiBaseUrl\(\)/)
})

test('app shell wraps router-view with a route error boundary', () => {
  const appSource = readSource('src/App.vue')
  const boundarySource = readSource('src/components/common/RouteErrorBoundary.vue')

  assert.match(appSource, /import\s+RouteErrorBoundary\s+from/)
  assert.match(appSource, /<RouteErrorBoundary[\s\S]*<router-view[\s\S]*<\/RouteErrorBoundary>/)
  assert.match(boundarySource, /onErrorCaptured/)
  assert.match(boundarySource, /重新加载模块/)
})

test('router handles lazy route chunk failures instead of leaving a blank page', () => {
  const source = readSource('src/router/index.ts')

  assert.match(source, /router\.onError/)
  assert.match(source, /isLazyRouteLoadError/)
  assert.match(source, /router\.replace\('\/devices'\)/)
})

test('screen stream releases h264 decoder when route canvas is replaced', () => {
  const source = readSource('src/composables/useScreenStream.ts')
  const setCanvasIndex = source.indexOf('function setCanvas')
  const setNativeHostIndex = source.indexOf('function setNativeHost')
  const setCanvasSource = source.slice(setCanvasIndex, setNativeHostIndex)

  assert.notEqual(setCanvasIndex, -1)
  assert.match(setCanvasSource, /stopH264Decoder\(\)/)
  assert.match(setCanvasSource, /if\s*\(\s*canvas\.value\s*===\s*nextCanvas\s*\)/)
  assert.match(setCanvasSource, /needsH264StreamRestartOnCanvasAttach/)
  assert.match(setCanvasSource, /initH264Decoder\(\)/)
})

test('device manager leaves native scrcpy embed mode opt-in inside Electron', () => {
  const source = readSource('src/views/DeviceManager.vue')
  const connectScreenIndex = source.indexOf('function connectScreen')
  const autoConnectIndex = source.indexOf('function autoConnectActiveDevice')
  const connectScreenSource = source.slice(connectScreenIndex, autoConnectIndex)

  assert.notEqual(connectScreenIndex, -1)
  assert.match(source, /const\s+isElectron\s*=/)
  assert.match(source, /const\s+preferNativeScrcpySurface\s*=/)
  assert.doesNotMatch(connectScreenSource, /useNativeScrcpySurface:\s*isElectron/)
  assert.match(connectScreenSource, /useNativeScrcpySurface:\s*preferNativeScrcpySurface/)
  assert.match(connectScreenSource, /preferApiTouchControl:\s*isElectron/)
})

test('device manager delegates automation tab markup to a focused sidebar component', () => {
  const source = readSource('src/views/DeviceManager.vue')
  const sidebarSource = readSource('src/components/device/AutomationSidebar.vue')

  assert.match(source, /import\s+AutomationSidebar\s+from/)
  assert.match(source, /<AutomationSidebar[\s\S]*@add-assert/)
  assert.match(sidebarSource, /defineProps</)
  assert.match(sidebarSource, /defineEmits</)
  assert.match(sidebarSource, /断言/)
  assert.match(sidebarSource, /图像对比/)
  assert.match(sidebarSource, /自动化脚本/)
})

test('test case manager leaves native scrcpy embed mode opt-in inside Electron', () => {
  const source = readSource('src/views/TestCaseManager.vue')
  const connectScreenIndex = source.indexOf('function connectScreen')
  const autoConnectIndex = source.indexOf('function autoConnectActiveDevice')
  const connectScreenSource = source.slice(connectScreenIndex, autoConnectIndex)

  assert.notEqual(connectScreenIndex, -1)
  assert.match(source, /const\s+isElectron\s*=/)
  assert.match(source, /const\s+preferNativeScrcpySurface\s*=/)
  assert.doesNotMatch(connectScreenSource, /useNativeScrcpySurface:\s*isElectron/)
  assert.match(connectScreenSource, /useNativeScrcpySurface:\s*preferNativeScrcpySurface/)
  assert.match(connectScreenSource, /preferApiTouchControl:\s*isElectron/)
})

test('screen stream can prefer API control over websocket control when requested', () => {
  const source = readSource('src/composables/useScreenStream.ts')

  assert.match(source, /preferApiTouchControl\?: boolean/)
  assert.match(source, /const\s+preferApiTouchControl\s*=\s*currentOptions\.preferApiTouchControl\s*===\s*true/)
  assert.match(source, /if\s*\(\s*preferApiTouchControl\s*&&\s*canUseApiControl\(\)\s*\)/)
})

test('test case manager leaves mapped raw h264 streams on the canvas path', () => {
  const source = readSource('src/views/TestCaseManager.vue')
  const predicateIndex = source.indexOf('const isScrcpyWebCodecsStream')
  const aspectRatioIndex = source.indexOf('const screenAspectRatio')
  const predicateSource = source.slice(predicateIndex, aspectRatioIndex)

  assert.notEqual(predicateIndex, -1)
  assert.doesNotMatch(predicateSource, /provider\s*===\s*'scrcpy-h264'/)
})

test('electron native scrcpy embed remains behind an explicit preload opt-in', () => {
  const source = readSource('../desktop/preload.js')

  assert.match(source, /getScreenStreamConfig:\s*\(\)\s*=>\s*\(\{/)
  assert.match(source, /preferNativeScrcpySurface:\s*false/)
})

test('electron opens devtools in detached mode during development', () => {
  const source = readSource('../desktop/main.js')

  assert.match(source, /openDevTools\(\{\s*mode:\s*'detach'\s*\}\)/)
})

test('auto execute panel registers ArrowDown icon instead of relying on lowercase component resolution', () => {
  const source = readSource('src/components/device/AutoExecutePanel.vue')

  assert.match(source, /ArrowDown/)
  assert.match(source, /<ArrowDown\s*\/>/)
  assert.doesNotMatch(source, /<arrow-down\s*\/>/)
})
