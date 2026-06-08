export const TAP_DISTANCE_PX = 24
export const LIVE_TOUCH_START_DISTANCE_PX = 18
export const LONG_PRESS_MIN_DURATION_MS = 550
export const DRAG_MIN_DURATION_MS = 700
export const MIN_GESTURE_DURATION_MS = 80
export const CONTINUOUS_TOUCH_MIN_DURATION_MS = 600

export type MobileGestureKind = 'tap' | 'long_press' | 'swipe' | 'drag'

export function shouldStartLiveTouch(
  distance: number,
  threshold: number = LIVE_TOUCH_START_DISTANCE_PX,
): boolean {
  return distance >= threshold
}

export function shouldUseContinuousTouch(input: {
  distance: number
  durationMs: number
  pointerType?: string
}): boolean {
  if (input.pointerType === 'mouse') return false
  return (
    input.distance >= LIVE_TOUCH_START_DISTANCE_PX &&
    input.durationMs >= CONTINUOUS_TOUCH_MIN_DURATION_MS
  )
}

export function classifyMobileGesture(input: {
  distance: number
  durationMs: number
}): MobileGestureKind {
  if (input.distance < TAP_DISTANCE_PX) {
    return input.durationMs >= LONG_PRESS_MIN_DURATION_MS ? 'long_press' : 'tap'
  }
  return input.durationMs > DRAG_MIN_DURATION_MS ? 'drag' : 'swipe'
}

export function normalizedGestureDuration(startedAt: number, endedAt: number): number {
  return Math.max(MIN_GESTURE_DURATION_MS, Math.round(endedAt - startedAt))
}
