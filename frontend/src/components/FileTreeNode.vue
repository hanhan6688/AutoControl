<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowRight, Document, Folder, FolderOpened, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { createScript as apiCreateScript, createFolder as apiCreateFolder, type FileTreeItem } from '../api'

const props = withDefaults(defineProps<{
  item: FileTreeItem
  activePath: string | null
  expandedFolders: Set<string>
  depth?: number
}>(), {
  depth: 0,
})

const emit = defineEmits<{
  toggleFolder: [path: string]
  openFile: [item: { path: string; name: string }]
  deleteFile: [item: { path: string; name: string }]
  deleteFolder: [path: string]
  refresh: []
}>()

const isExpanded = computed(() => props.expandedFolders.has(props.item.path))
const isFolder = computed(() => props.item.type === 'folder')
const indentStyle = computed(() => `padding-left: ${props.depth * 16 + 4}px`)

// Inline creation state
const creatingInFolder = ref(false)
const creatingType = ref<'file' | 'folder'>('file')
const createValue = ref('')
const createInput = ref<HTMLInputElement>()

const sortedChildren = computed(() => {
  if (!props.item.children) return []
  return [...props.item.children].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
    return a.name.localeCompare(b.name)
  })
})

function startCreating(type: 'file' | 'folder') {
  creatingType.value = type
  createValue.value = ''
  creatingInFolder.value = true
  // Auto-expand the folder
  if (!isExpanded.value) {
    emit('toggleFolder', props.item.path)
  }
  nextTick(() => createInput.value?.focus())
}

async function confirmCreate() {
  const name = createValue.value.trim()
  if (!name) {
    creatingInFolder.value = false
    return
  }
  try {
    const fullName = props.item.path ? `${props.item.path}/${name}` : name
    if (creatingType.value === 'folder') {
      await apiCreateFolder(fullName)
    } else {
      const scriptName = name.endsWith('.py') ? fullName : `${fullName}.py`
      await apiCreateScript(scriptName, '')
    }
    creatingInFolder.value = false
    emit('refresh')
    ElMessage.success(creatingType.value === 'folder' ? '文件夹已创建' : '脚本已创建')
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

function cancelCreate() {
  creatingInFolder.value = false
}
</script>

<template>
  <!-- Folder -->
  <div v-if="isFolder" class="tree-folder">
    <div class="folder-item" :style="indentStyle" @click="emit('toggleFolder', item.path)">
      <!-- Expand/collapse arrow (VSCode-style) -->
      <span class="expand-arrow" :class="{ expanded: isExpanded }">
        <el-icon :size="14"><ArrowRight /></el-icon>
      </span>
      <el-icon class="folder-icon">
        <FolderOpened v-if="isExpanded" />
        <Folder v-else />
      </el-icon>
      <span class="folder-name">{{ item.name }}</span>
      <div class="folder-actions">
        <button class="action-btn" title="新建文件" @click.stop="startCreating('file')">
          <el-icon :size="12"><Document /></el-icon>
        </button>
        <button class="action-btn" title="新建文件夹" @click.stop="startCreating('folder')">
          <el-icon :size="12"><Folder /></el-icon>
        </button>
        <button class="action-btn delete-btn" title="删除文件夹" @click.stop="emit('deleteFolder', item.path)">
          <el-icon :size="12"><Delete /></el-icon>
        </button>
      </div>
    </div>

    <!-- Inline creation input -->
    <div
      v-if="creatingInFolder"
      class="create-input-row"
      :style="`padding-left: ${(depth + 1) * 16 + 4}px`"
    >
      <span class="expand-arrow placeholder" />
      <el-icon class="node-icon">
        <Folder v-if="creatingType === 'folder'" />
        <Document v-else />
      </el-icon>
      <input
        ref="createInput"
        v-model="createValue"
        class="inline-input"
        :placeholder="creatingType === 'folder' ? '文件夹名称' : '脚本名称 (.py)'"
        @keydown.enter="confirmCreate"
        @keydown.escape="cancelCreate"
      />
    </div>

    <div v-if="isExpanded && item.children" class="folder-children">
      <FileTreeNode
        v-for="child in sortedChildren"
        :key="child.path"
        :item="child"
        :active-path="activePath"
        :expanded-folders="expandedFolders"
        :depth="depth + 1"
        @toggle-folder="(p) => emit('toggleFolder', p)"
        @open-file="(i) => emit('openFile', i)"
        @delete-file="(i) => emit('deleteFile', i)"
        @delete-folder="(p) => emit('deleteFolder', p)"
        @refresh="emit('refresh')"
      />
    </div>
  </div>

  <!-- File -->
  <div
    v-else
    class="file-item"
    :class="{ active: activePath === item.path }"
    :style="indentStyle"
    @click="emit('openFile', { path: item.path, name: item.name })"
  >
    <span class="expand-arrow placeholder" />
    <el-icon class="file-icon"><Document /></el-icon>
    <span class="file-name">{{ item.name }}</span>
    <div class="file-actions">
      <button class="action-btn delete-btn" @click.stop="emit('deleteFile', { path: item.path, name: item.name })">
        <el-icon :size="12"><Delete /></el-icon>
      </button>
    </div>
  </div>
</template>

<style scoped>
.tree-folder {
  display: flex;
  flex-direction: column;
}

.folder-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
  border-radius: 3px;
}

.folder-item:hover {
  background: var(--bg-tertiary);
}

/* Expand arrow — VSCode-style right-pointing triangle */
.expand-arrow {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.15s ease;
}

.expand-arrow.expanded {
  transform: rotate(90deg);
}

.expand-arrow.placeholder {
  visibility: hidden;
}

.folder-icon {
  flex-shrink: 0;
  color: var(--el-color-warning, #e6a23c);
}

.folder-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Actions — shown on hover, like VSCode */
.folder-actions,
.file-actions {
  display: none;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  margin-left: auto;
}

.folder-item:hover .folder-actions,
.file-item:hover .file-actions {
  display: flex;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
}

.action-btn:hover {
  background: var(--bg-primary);
  color: var(--text-primary);
}

.action-btn.delete-btn:hover {
  color: var(--danger);
}

.folder-children {
  display: flex;
  flex-direction: column;
}

/* Inline creation input */
.create-input-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
}

.inline-input {
  flex: 1;
  border: 1px solid var(--el-color-primary);
  border-radius: 3px;
  padding: 2px 6px;
  height: 22px;
  font-size: 13px;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  outline: none;
  min-width: 80px;
}

/* File item */
.file-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
  border-radius: 3px;
}

.file-item:hover {
  background: var(--bg-tertiary);
}

.file-item.active {
  background: var(--el-color-primary-light-9, rgba(64, 158, 255, 0.1));
  color: var(--el-color-primary);
}

.file-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>