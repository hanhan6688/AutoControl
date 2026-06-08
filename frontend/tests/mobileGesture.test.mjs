import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from '../node_modules/typescript/lib/typescript.js'

const sourcePath = resolve(import.meta.dirname, '../src/utils/mobileGesture.ts')
const source = readFileSync(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText

const moduleUrl = `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
const gesture = await import(moduleUrl)

assert.equal(gesture.shouldStartLiveTouch(0), false)
assert.equal(gesture.shouldStartLiveTouch(gesture.LIVE_TOUCH_START_DISTANCE_PX - 1), false)
assert.equal(gesture.shouldStartLiveTouch(gesture.LIVE_TOUCH_START_DISTANCE_PX), true)

assert.equal(
  gesture.shouldUseContinuousTouch({
    distance: 180,
    durationMs: 180,
    pointerType: 'mouse',
  }),
  false,
)
assert.equal(
  gesture.shouldUseContinuousTouch({
    distance: 180,
    durationMs: 180,
    pointerType: 'touch',
  }),
  false,
)
assert.equal(
  gesture.shouldUseContinuousTouch({
    distance: 180,
    durationMs: 650,
    pointerType: 'touch',
  }),
  true,
)

assert.equal(gesture.classifyMobileGesture({ distance: 3, durationMs: 120 }), 'tap')
assert.equal(gesture.classifyMobileGesture({ distance: 3, durationMs: 420 }), 'tap')
assert.equal(gesture.classifyMobileGesture({ distance: 3, durationMs: 560 }), 'long_press')
assert.equal(gesture.classifyMobileGesture({ distance: 80, durationMs: 160 }), 'swipe')
assert.equal(gesture.classifyMobileGesture({ distance: 80, durationMs: 420 }), 'swipe')
assert.equal(gesture.classifyMobileGesture({ distance: 80, durationMs: 720 }), 'drag')

assert.equal(gesture.normalizedGestureDuration(1000, 1020), 80)
assert.equal(gesture.normalizedGestureDuration(1000, 1250), 250)
