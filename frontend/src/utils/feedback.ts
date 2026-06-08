import { ElMessage, ElNotification } from 'element-plus'

export interface FeedbackOptions {
  message: string
  type?: 'success' | 'warning' | 'error' | 'info'
  duration?: number
  showNotification?: boolean
  title?: string
}

const defaultDuration = 2000

export function showFeedback(options: FeedbackOptions) {
  const { message, type = 'info', duration = defaultDuration, showNotification = false, title } = options

  // Quick toast message
  ElMessage({
    message,
    type,
    duration,
    grouping: true,
  })

  // Optional notification for important events
  if (showNotification && title) {
    ElNotification({
      title,
      message,
      type,
      duration: duration * 2,
      position: 'bottom-right',
    })
  }
}

export function showSuccess(message: string, title?: string) {
  showFeedback({ message, type: 'success', showNotification: Boolean(title), title })
}

export function showError(message: string, title?: string) {
  showFeedback({ message, type: 'error', duration: 4000, showNotification: Boolean(title), title })
}

export function showWarning(message: string) {
  showFeedback({ message, type: 'warning', duration: 3000 })
}

export function showInfo(message: string) {
  showFeedback({ message, type: 'info' })
}

export function showLoading(message: string) {
  return ElMessage({
    message,
    type: 'info',
    duration: 0,
    grouping: true,
    icon: 'Loading',
  })
}

export function closeLoading(instance: ReturnType<typeof ElMessage>) {
  instance.close()
}