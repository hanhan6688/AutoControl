<script setup lang="ts">
import { Pointer, Edit, Mouse } from '@element-plus/icons-vue'

defineProps<{
  elements: any[]
}>()

const emit = defineEmits<{
  click: [ref: string]
  fill: [ref: string, text: string]
  hover: [ref: string]
}>()
</script>

<template>
  <section class="panel-section elements-list">
    <div class="section-title">页面元素</div>
    <div v-if="elements?.length" class="element-items">
      <div
        v-for="(el, idx) in elements"
        :key="idx"
        class="element-item"
      >
        <div class="element-info">
          <el-tag size="small" type="info">{{ el.tag || el.type || '元素' }}</el-tag>
          <span class="element-text">{{ el.text || el.ref || el.selector || `元素 ${idx + 1}` }}</span>
        </div>
        <div class="element-actions">
          <el-tooltip content="点击" placement="top">
            <el-button :icon="Pointer" size="small" @click="emit('click', el.ref || el.selector || '')" />
          </el-tooltip>
          <el-tooltip content="填写" placement="top">
            <el-button :icon="Edit" size="small" @click="emit('fill', el.ref || el.selector || '', '')" />
          </el-tooltip>
          <el-tooltip content="悬停" placement="top">
            <el-button :icon="Mouse" size="small" @click="emit('hover', el.ref || el.selector || '')" />
          </el-tooltip>
        </div>
      </div>
    </div>
    <el-empty v-else description="暂无元素" :image-size="40" />
  </section>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.elements-list {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.section-title {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.element-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow: auto;
}

.element-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
}

.element-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.element-text {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.element-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
</style>
