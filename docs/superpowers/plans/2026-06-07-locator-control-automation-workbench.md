# Locator Control And Automation Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add locator-aware Android control on top of the existing `scrcpy + uiautomator2` stack, surface assertion/image-compare/script actions clearly in the Device Manager sidebar, and remove dead control-path code that is no longer referenced.

**Architecture:** Keep `scrcpy` as the low-latency transport for manual pointer gestures, but allow structured control commands to carry a locator payload so backend execution can resolve to `uiautomator2` selectors before falling back to raw coordinates. Split the bulky automation tab UI out of `DeviceManager.vue` into a focused child component that receives state via props and emits intent back up to the route view.

**Tech Stack:** FastAPI, Pydantic, Python pytest, Vue 3 `<script setup lang="ts">`, Element Plus, Node built-in test runner, Vite, `uiautomator2`, scrcpy.

---

### Task 1: Lock The Current Contract With Failing Tests

**Files:**
- Modify: `D:\Mobile-AI-TestOps\backend\tests\test_devices_ui_routes.py`
- Modify: `D:\Mobile-AI-TestOps\frontend\tests\appStability.test.mjs`

- [ ] **Step 1: Write the failing backend tests for locator-aware tap control**

```python
async def test_websocket_tap_with_locator_prefers_ui_element_service(monkeypatch) -> None:
    from app.routers import devices

    ui_click_calls: list[dict] = []
    scrcpy_calls: list[tuple[str, tuple[int, ...]]] = []
    adb_calls: list[tuple[str, str]] = []

    class FakeUIElementService:
        def click(self, **kwargs):
            ui_click_calls.append(kwargs)
            return True

    class FakeScrcpyClient:
        def tap(self, *args: int) -> None:
            scrcpy_calls.append(("tap", args))

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return FakeScrcpyClient()

        def unregister(self, udid: str, client) -> None:
            pass

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            adb_calls.append((udid, command))

    class FakeADBService:
        def input_text(self, udid: str, value: str) -> None:
            raise AssertionError("locator tap should not route through adb text input")

    monkeypatch.setattr(devices, "UIElementService", FakeUIElementService)
    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {
            "type": "tap",
            "x": 12,
            "y": 34,
            "locator": {
                "resource_id": "com.demo:id/login",
                "package": "com.demo",
                "fallback": [12, 34],
            },
        },
    )

    assert len(ui_click_calls) == 1
    assert ui_click_calls[0]["resource_id"] == "com.demo:id/login"
    assert scrcpy_calls == []
    assert adb_calls == []


async def test_websocket_tap_without_locator_keeps_scrcpy_path(monkeypatch) -> None:
    from app.routers import devices

    scrcpy_calls: list[tuple[str, tuple[int, ...]]] = []

    class FakeScrcpyClient:
        def tap(self, *args: int) -> None:
            scrcpy_calls.append(("tap", args))

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return FakeScrcpyClient()

        def unregister(self, udid: str, client) -> None:
            pass

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            raise AssertionError("plain tap should stay on scrcpy path")

    class FakeADBService:
        pass

    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {"type": "tap", "x": 80, "y": 120},
    )

    assert scrcpy_calls == [("tap", (80, 120))]
```

- [ ] **Step 2: Run backend tests to verify they fail**

Run:

```bash
python -m pytest backend/tests/test_devices_ui_routes.py -q
```

Expected: FAIL because `_handle_control_command()` currently ignores `locator` and always routes `tap` to `_send_scrcpy_or_adb(...)`.

- [ ] **Step 3: Write the failing frontend structure tests for the automation sidebar split**

```javascript
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
```

- [ ] **Step 4: Run frontend structure tests to verify they fail**

Run:

```bash
node --test frontend/tests/appStability.test.mjs
```

Expected: FAIL because `AutomationSidebar.vue` does not exist yet and `DeviceManager.vue` still renders the automation tab inline.


### Task 2: Implement Locator-Aware Control On The Backend

**Files:**
- Modify: `D:\Mobile-AI-TestOps\backend\app\routers\devices.py`
- Modify: `D:\Mobile-AI-TestOps\backend\app\schemas.py`
- Test: `D:\Mobile-AI-TestOps\backend\tests\test_devices_ui_routes.py`

- [ ] **Step 1: Add typed locator payload models**

```python
class DeviceControlLocatorPayload(BaseModel):
    text: str | None = None
    resource_id: str | None = None
    content_desc: str | None = None
    class_name: str | None = None
    package: str | None = None
    xpath: str | None = None
    ocr_text: str | None = None
    image_path: str | None = None
    fallback: list[int] | None = None


class DeviceControlCommandRequest(BaseModel):
    type: str
    x: int | None = None
    y: int | None = None
    x1: int | None = None
    y1: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int | None = None
    drag_duration_ms: int | None = None
    keycode: int | None = None
    text: str | None = None
    locator: DeviceControlLocatorPayload | None = None
```

- [ ] **Step 2: Add a small helper that routes tap-by-locator through `UIElementService.click()`**

```python
async def _handle_locator_tap(udid: str, locator: dict) -> bool:
    fallback_raw = locator.get("fallback")
    fallback = None
    if isinstance(fallback_raw, (list, tuple)) and len(fallback_raw) == 2:
        fallback = (int(fallback_raw[0]), int(fallback_raw[1]))

    return await asyncio.to_thread(
        UIElementService().click,
        udid=udid,
        text=locator.get("text"),
        resource_id=locator.get("resource_id"),
        content_desc=locator.get("content_desc"),
        class_name=locator.get("class_name"),
        package=locator.get("package"),
        xpath=locator.get("xpath"),
        fallback=fallback,
        ocr_text=locator.get("ocr_text"),
        image_path=locator.get("image_path"),
    )
```

- [ ] **Step 3: Update `_handle_control_command()` so `tap` prefers locator semantics when provided**

```python
elif cmd_type == "tap":
    locator = command.get("locator")
    if isinstance(locator, dict) and locator:
        await _handle_locator_tap(udid, locator)
        return

    x, y = command["x"], command["y"]
    await _send_scrcpy_or_adb(
        udid,
        lambda client: client.tap(int(x), int(y)),
        f"input tap {int(x)} {int(y)}",
    )
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run:

```bash
python -m pytest backend/tests/test_devices_ui_routes.py -q
```

Expected: PASS with the new locator-aware tap behavior and the existing scrcpy-path behavior preserved.


### Task 3: Split The Automation Sidebar Out Of `DeviceManager.vue`

**Files:**
- Create: `D:\Mobile-AI-TestOps\frontend\src\components\device\AutomationSidebar.vue`
- Modify: `D:\Mobile-AI-TestOps\frontend\src\views\DeviceManager.vue`
- Modify: `D:\Mobile-AI-TestOps\frontend\src\components\device\index.ts`
- Test: `D:\Mobile-AI-TestOps\frontend\tests\appStability.test.mjs`

- [ ] **Step 1: Create a focused automation sidebar component with explicit props/emits**

```vue
<script setup lang="ts">
import { CircleCheck, Picture, WarningFilled } from '@element-plus/icons-vue'

interface ImageCompareResult {
  matched: boolean
  score: number
  location: number[] | null
}

const props = defineProps<{
  disabled: boolean
  autoExecuteRecording: boolean
  assertType: 'element_exists' | 'text_visible' | 'ocr_contains' | 'image_exists' | 'app_foreground'
  assertTargetText: string
  assertTargetResourceId: string
  assertTargetAppId: string
  assertImageThreshold: number
  assertImageTemplateName: string
  imageCompareBusy: boolean
  imageCompareResult: ImageCompareResult | null
}>()

const emit = defineEmits<{
  updateAssertType: [value: typeof props.assertType]
  updateAssertTargetText: [value: string]
  updateAssertTargetResourceId: [value: string]
  updateAssertTargetAppId: [value: string]
  updateAssertImageThreshold: [value: number]
  pickAssertImage: []
  addAssert: []
  captureTemplate: []
  runImageCompare: []
}>()
</script>
```

- [ ] **Step 2: Move the automation tab markup into the new component**

```vue
<template>
  <div class="automation-sidebar">
    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><CircleCheck /></el-icon>
        <span>断言</span>
      </div>
      <!-- select + inputs -->
    </div>

    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><Picture /></el-icon>
        <span>图像对比</span>
      </div>
      <!-- capture / compare controls -->
    </div>

    <div class="automation-section">
      <div class="automation-section-title">
        <el-icon><WarningFilled /></el-icon>
        <span>自动化脚本</span>
      </div>
      <p class="automation-hint">
        断言、模板、图像对比结果都会写回当前脚本；录制关闭时按钮仅做预览，不写入文件。
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Replace the inline automation tab in `DeviceManager.vue` with the child component**

```vue
<AutomationSidebar
  v-if="activeLeftTab === 'automation'"
  :disabled="!deviceStore.activeDevice || !activeScriptPath"
  :auto-execute-recording="autoExecuteRecording"
  :assert-type="assertType"
  :assert-target-text="assertTargetText"
  :assert-target-resource-id="assertTargetResourceId"
  :assert-target-app-id="assertTargetAppId"
  :assert-image-threshold="assertImageThreshold"
  :assert-image-template-name="assertImageTemplateName"
  :image-compare-busy="imageCompareBusy"
  :image-compare-result="imageCompareResult"
  @update-assert-type="assertType = $event"
  @update-assert-target-text="assertTargetText = $event"
  @update-assert-target-resource-id="assertTargetResourceId = $event"
  @update-assert-target-app-id="assertTargetAppId = $event"
  @update-assert-image-threshold="assertImageThreshold = $event"
  @pick-assert-image="pickAssertImageFile"
  @add-assert="addAssertToRecording"
  @capture-template="captureAssertTemplate"
  @run-image-compare="runAssertImageCompare"
/>
```

- [ ] **Step 4: Re-run frontend structure tests**

Run:

```bash
node --test frontend/tests/appStability.test.mjs
```

Expected: PASS with the new `AutomationSidebar.vue` component and the route-view composition still intact.


### Task 4: Teach The Sidebar To Reuse Recorded Locators Instead Of Duplicating Script Logic

**Files:**
- Modify: `D:\Mobile-AI-TestOps\frontend\src\views\DeviceManager.vue`
- Test: `D:\Mobile-AI-TestOps\frontend\tests\appStability.test.mjs`

- [ ] **Step 1: Add a small helper that converts the latest selected assertion state into a script line**

```ts
function buildAssertionCommand(): string | null {
  if (assertType.value === 'text_visible' && assertTargetText.value.trim()) {
    return `auto_execute.assert_text_visible(expected_text=${pythonStringLiteral(assertTargetText.value.trim())})`
  }
  if (assertType.value === 'element_exists' && assertTargetResourceId.value.trim()) {
    return `auto_execute.assert_element(resource_id=${pythonStringLiteral(assertTargetResourceId.value.trim())})`
  }
  if (assertType.value === 'ocr_contains' && assertTargetText.value.trim()) {
    return `auto_execute.assert_ocr_contains(${pythonStringLiteral(assertTargetText.value.trim())})`
  }
  if (assertType.value === 'app_foreground' && assertTargetAppId.value.trim()) {
    return `auto_execute.assert_foreground_app(${pythonStringLiteral(assertTargetAppId.value.trim())})`
  }
  if (assertType.value === 'image_exists' && assertImageTemplateName.value.trim()) {
    return `image.assert_exists(${pythonStringLiteral(assertImageTemplateName.value.trim())}, threshold=${assertImageThreshold.value})`
  }
  return null
}
```

- [ ] **Step 2: Update the button handlers so preview-only actions never append scripts and recording actions do**

```ts
async function addAssertToRecording() {
  if (!deviceStore.activeDevice) return
  const command = buildAssertionCommand()
  if (!command) {
    ElMessage.warning('请先填写完整的断言参数')
    return
  }
  if (!autoExecuteRecording.value || activeScriptContent.value === null) {
    ElMessage.info('当前未开启录制，只预览断言，不写入脚本')
    return
  }
  appendCommandToActiveScript(command)
  autoExecuteStatusText.value = `已写入断言：${command}`
}
```

- [ ] **Step 3: Run `vue-tsc` / build verification**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS with no TypeScript errors and the automation sidebar still compiling cleanly after extraction.


### Task 5: Remove Confirmed Dead Control-Path Code

**Files:**
- Modify: `D:\Mobile-AI-TestOps\backend\app\services\screen_stream_service.py`
- Modify: `D:\Mobile-AI-TestOps\frontend\src\composables\useScreenStream.ts`
- Test: `D:\Mobile-AI-TestOps\backend\tests\test_screen_stream_service.py`
- Test: `D:\Mobile-AI-TestOps\frontend\tests\appStability.test.mjs`

- [ ] **Step 1: Remove the legacy `socketio-scrcpy` provider alias if it is not emitted anywhere**

```python
# before
if selected_provider in {"scrcpy-webcodecs", "socketio-scrcpy"}:
    selected_provider = "scrcpy-h264"

# after
if selected_provider == "scrcpy-webcodecs":
    selected_provider = "scrcpy-h264"
```

- [ ] **Step 2: Remove matching dead alias references on the frontend if no caller uses them**

```ts
// keep socketio mode for iOS; remove only the dead scrcpy alias comments/branches
```

- [ ] **Step 3: Re-run targeted regression tests**

Run:

```bash
python -m pytest backend/tests/test_screen_stream_service.py backend/tests/test_devices_ui_routes.py -q
node --test frontend/tests/appStability.test.mjs
```

Expected: PASS with scrcpy/webcodecs behavior unchanged and no references left to the removed dead alias.


### Task 6: Final Verification

**Files:**
- No code changes required unless verification fails

- [ ] **Step 1: Run the backend regression set**

Run:

```bash
python -m pytest backend/tests/test_devices_ui_routes.py backend/tests/test_screen_stream_service.py backend/tests/test_u2_service.py backend/tests/test_ui_element_service.py -q
```

Expected: PASS

- [ ] **Step 2: Run the frontend regression set**

Run:

```bash
node --test frontend/tests/appStability.test.mjs frontend/tests/mobileGesture.test.mjs frontend/tests/h264Decoder.test.mjs
npm --prefix frontend run build
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/devices.py backend/app/schemas.py backend/tests/test_devices_ui_routes.py backend/app/services/screen_stream_service.py frontend/src/views/DeviceManager.vue frontend/src/components/device/AutomationSidebar.vue frontend/src/components/device/index.ts frontend/tests/appStability.test.mjs
git commit -m "feat: add locator-aware mobile control"
```
