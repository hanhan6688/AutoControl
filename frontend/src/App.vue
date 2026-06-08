<script setup lang="ts">
import { computed, ref, provide, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Cellphone, Files, Cpu, Monitor, Link } from '@element-plus/icons-vue'
import { DiagnosticPanel } from './components/diagnostic'
import RouteErrorBoundary from './components/common/RouteErrorBoundary.vue'
import { useScreenStream, type ScreenStreamHandle } from './composables'

const route = useRoute()
const router = useRouter()

const showDiagnostic = ref(false)
const routeReloadVersion = ref(0)
const routeViewKey = computed(() => `${route.fullPath}:${routeReloadVersion.value}`)

// ── Shared screen stream singleton ────────────────────────────────────
// Each route page used to create its own useScreenStream() instance,
// causing WebSocket conflicts when switching between modules.
// Now we create one instance in App.vue and provide it to children.
const screen = useScreenStream()
provide<ScreenStreamHandle>('screenStream', screen)

onBeforeUnmount(() => {
  screen.disconnect()
})

function reloadCurrentRoute() {
  routeReloadVersion.value += 1
}
</script>

<template>
  <div class="app-root">
    <!-- Global Nav -->
    <nav class="global-nav">
      <div class="nav-brand">Mobile AI TestOps</div>
      <div class="nav-tabs">
        <button
          class="nav-tab"
          :class="{ active: route.path === '/devices' }"
          @click="router.push('/devices')"
        >
          <el-icon><Cellphone /></el-icon>
          <span>自动化</span>
        </button>
        <button
          class="nav-tab"
          :class="{ active: route.path === '/cases' }"
          @click="router.push('/cases')"
        >
          <el-icon><Files /></el-icon>
          <span>AutoGLM</span>
        </button>
        <button
          class="nav-tab"
          :class="{ active: route.path === '/pc-autoexecute' }"
          @click="router.push('/pc-autoexecute')"
        >
          <el-icon><Monitor /></el-icon>
          <span>PC AutoExecute</span>
        </button>
        <button
          class="nav-tab"
          :class="{ active: route.path === '/api-tests' }"
          @click="router.push('/api-tests')"
        >
          <el-icon><Link /></el-icon>
          <span>接口测试</span>
        </button>
      </div>
      <div class="nav-actions">
        <el-button
          :icon="Cpu"
          size="small"
          :type="showDiagnostic ? 'primary' : 'default'"
          @click="showDiagnostic = !showDiagnostic"
        >
          诊断
        </el-button>
      </div>
    </nav>

    <!-- Main Content -->
    <div class="main-content">
      <div class="page-area" :class="{ 'with-diagnostic': showDiagnostic }">
        <RouteErrorBoundary :reset-key="route.fullPath" @retry="reloadCurrentRoute">
          <router-view :key="routeViewKey" />
        </RouteErrorBoundary>
      </div>
      <transition name="slide">
        <div v-if="showDiagnostic" class="diagnostic-area">
          <DiagnosticPanel />
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-primary);
}

.global-nav {
  display: flex;
  align-items: center;
  gap: 24px;
  height: 44px;
  padding: 0 16px;
  background: var(--bg-nav);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.nav-brand {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
  user-select: none;
  white-space: nowrap;
}

.nav-tabs {
  display: flex;
  gap: 4px;
  flex: 1;
}

.nav-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-tab:hover {
  color: var(--text-primary);
  background: var(--bg-tertiary);
}

.nav-tab.active {
  color: var(--accent);
  background: var(--accent-subtle);
  font-weight: 500;
}

.nav-actions {
  display: flex;
  gap: 8px;
}

.main-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.page-area {
  flex: 1;
  min-height: 0;
  overflow: auto;
  transition: flex 0.3s ease;
}

.page-area.with-diagnostic {
  flex: 1;
}

.diagnostic-area {
  width: 400px;
  border-left: 1px solid var(--border-color);
  background: var(--bg-secondary);
  overflow: hidden;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  width: 0;
  opacity: 0;
}

@media (max-width: 720px) {
  .global-nav {
    gap: 12px;
    padding: 0 8px;
  }

  .nav-brand {
    font-size: 12px;
  }

  .nav-tab {
    padding: 0 8px;
    font-size: 11px;
  }

  .nav-tab span {
    display: none;
  }

  .nav-tab .el-icon {
    margin: 0;
  }
}
</style>
