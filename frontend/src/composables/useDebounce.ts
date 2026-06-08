import { ref, watch, onUnmounted, type Ref } from 'vue'

export function useDebouncedRef<T>(initialValue: T, delay: number): Ref<T> {
  const state = ref<T>(initialValue) as Ref<T>
  let timeout: number | null = null

  watch(state, (newValue) => {
    if (timeout) clearTimeout(timeout)
    timeout = window.setTimeout(() => {
      state.value = newValue
    }, delay)
  })

  onUnmounted(() => {
    if (timeout) clearTimeout(timeout)
  })

  return state
}

export function debounce<T extends (...args: Parameters<T>) => ReturnType<T>>(fn: T, delay: number): T {
  let timeout: ReturnType<typeof setTimeout> | null = null
  return ((...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => fn(...args), delay)
  }) as T
}

export function throttle<T extends (...args: Parameters<T>) => ReturnType<T>>(fn: T, limit: number): T {
  let inThrottle = false
  return ((...args: Parameters<T>) => {
    if (!inThrottle) {
      fn(...args)
      inThrottle = true
      setTimeout(() => { inThrottle = false }, limit)
    }
  }) as T
}

export function useDebounce<T extends (...args: Parameters<T>) => ReturnType<T>>(fn: T, delay: number) {
  let timeout: ReturnType<typeof setTimeout> | null = null

  function debouncedFn(...args: Parameters<T>) {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => fn(...args), delay)
  }

  function flush() {
    if (timeout) {
      clearTimeout(timeout)
      timeout = null
    }
  }

  onUnmounted(flush)

  return { debouncedFn, flush }
}
