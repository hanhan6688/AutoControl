import { onMounted, onUnmounted } from 'vue'

type KeyboardHandler = (event: KeyboardEvent) => void

export interface KeyboardShortcut {
  key: string
  ctrl?: boolean
  shift?: boolean
  alt?: boolean
  handler: () => void
  description?: string
}

export function useKeyboard(shortcuts: KeyboardShortcut[]) {
  function handleKeyDown(event: KeyboardEvent) {
    for (const shortcut of shortcuts) {
      const ctrlMatch = shortcut.ctrl ? event.ctrlKey || event.metaKey : true
      const shiftMatch = shortcut.shift ? event.shiftKey : !event.shiftKey
      const altMatch = shortcut.alt ? event.altKey : !event.altKey
      const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase()

      if (ctrlMatch && shiftMatch && altMatch && keyMatch) {
        event.preventDefault()
        shortcut.handler()
        return
      }
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
  })

  return {
    shortcuts,
  }
}

export function formatShortcut(shortcut: KeyboardShortcut): string {
  const parts: string[] = []
  if (shortcut.ctrl) parts.push('Ctrl')
  if (shortcut.shift) parts.push('Shift')
  if (shortcut.alt) parts.push('Alt')
  parts.push(shortcut.key.toUpperCase())
  return parts.join('+')
}
