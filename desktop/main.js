const { app, BrowserWindow, ipcMain, shell } = require('electron')
const fs = require('fs')
const path = require('path')
const { spawn, execFile } = require('child_process')

let mainWindow = null
let backendProcess = null
let scrcpyProcess = null
let scrcpyNative = null

const isDev = process.env.ELECTRON_DEV === 'true' || !app.isPackaged
const backendHost = process.env.BACKEND_HOST || '127.0.0.1'
let backendPort = process.env.BACKEND_PORT || '8000'
let backendBaseUrl = process.env.BACKEND_BASE_URL || `http://${backendHost}:${backendPort}`
const viteDevUrl = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173'
const resourceRoot = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..')
const loopbackNoProxy = '127.0.0.1,localhost,::1'
const nativeScrcpyLogPath = path.join(resourceRoot, 'logs', 'electron-native-scrcpy.log')

process.env.NO_PROXY = [process.env.NO_PROXY, loopbackNoProxy].filter(Boolean).join(',')
process.env.no_proxy = [process.env.no_proxy, loopbackNoProxy].filter(Boolean).join(',')
app.commandLine.appendSwitch('proxy-bypass-list', '<-loopback>;127.0.0.1;localhost;::1')
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')

function resourcePath(...segments) {
  return path.join(resourceRoot, ...segments)
}

function logNativeScrcpy(message, detail = '') {
  try {
    fs.mkdirSync(path.dirname(nativeScrcpyLogPath), { recursive: true })
    const line = `[${new Date().toISOString()}] ${message}${detail ? ` ${detail}` : ''}\n`
    fs.appendFileSync(nativeScrcpyLogPath, line, 'utf8')
  } catch {
    // Logging must not break the app.
  }
}

function firstExistingPath(candidates) {
  return candidates.find(candidate => fs.existsSync(candidate)) || candidates[0]
}

function frontendIndexPath() {
  return firstExistingPath([
    resourcePath('frontend', 'dist', 'index.html'),
    path.join(__dirname, '..', 'frontend', 'dist', 'index.html'),
  ])
}

function backendDirPath() {
  return firstExistingPath([
    resourcePath('backend'),
    path.join(__dirname, '..', 'backend'),
  ])
}

function backendLaunchConfig() {
  const backendDir = backendDirPath()
  const packagedBackendExe = path.join(backendDir, 'mobile-ai-testops-backend.exe')
  if (app.isPackaged && fs.existsSync(packagedBackendExe)) {
    return { command: packagedBackendExe, args: [], cwd: backendDir }
  }
  const projectVenvPython = path.join(resourceRoot, '.venv', 'Scripts', 'python.exe')
  const pythonCommand = process.env.PYTHON || (fs.existsSync(projectVenvPython) ? projectVenvPython : 'python')
  return {
    command: pythonCommand,
    args: ['-m', 'uvicorn', 'app.main:app', '--host', backendHost, '--port', backendPort],
    cwd: backendDir,
  }
}

function backendPortCandidates() {
  const configured = process.env.BACKEND_PORT ? [Number(process.env.BACKEND_PORT)] : []
  const defaults = [8000, 8001, 8002, 8003, 8004, 8005, 8010]
  return [...new Set([...configured, ...defaults].filter(port => Number.isInteger(port) && port > 0))]
}

async function isPortAvailable(port) {
  const net = require('net')
  return new Promise((resolve) => {
    const server = net.createServer()
    server.once('error', () => resolve(false))
    server.once('listening', () => server.close(() => resolve(true)))
    server.listen(port, backendHost)
  })
}

async function waitForHttp(url, label, maxAttempts = 30, logWait = true) {
  const http = require('http')
  const https = require('https')
  const client = url.startsWith('https:') ? https : http

  for (let i = 0; i < maxAttempts; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = client.get(url, (res) => {
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 500) {
            resolve(true)
          } else {
            reject(new Error('Not ready'))
          }
        })
        req.on('error', reject)
        req.setTimeout(1000, () => {
          req.destroy()
          reject(new Error('Timeout'))
        })
      })
      console.log(`${label} is ready`)
      return true
    } catch (e) {
      if (logWait) console.log(`Waiting for ${label}... (${i + 1}/${maxAttempts})`)
      await new Promise(r => setTimeout(r, 500))
    }
  }
  return false
}

async function pickBackendLaunchUrl() {
  if (process.env.BACKEND_BASE_URL) {
    backendBaseUrl = process.env.BACKEND_BASE_URL
    const parsed = new URL(backendBaseUrl)
    backendPort = parsed.port || (parsed.protocol === 'https:' ? '443' : '80')
    return
  }

  for (const port of backendPortCandidates()) {
    const candidateUrl = `http://${backendHost}:${port}`
    if (await waitForHttp(`${candidateUrl}/api/health`, `existing backend ${candidateUrl}`, 1, false)) {
      backendPort = String(port)
      backendBaseUrl = candidateUrl
      return
    }
  }

  for (const port of backendPortCandidates()) {
    if (await isPortAvailable(port)) {
      backendPort = String(port)
      backendBaseUrl = `http://${backendHost}:${backendPort}`
      return
    }
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
    backgroundColor: '#1a1a2e',
    title: 'Mobile AI TestOps',
    show: false,
  })

  if (isDev) {
    mainWindow.loadURL(viteDevUrl)
  } else {
    mainWindow.loadFile(frontendIndexPath())
  }

  mainWindow.once('ready-to-show', () => mainWindow.show())

  if (isDev) {
    mainWindow.webContents.openDevTools()
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function startBackend() {
  const launch = backendLaunchConfig()
  console.log(`Starting backend server on ${backendBaseUrl}...`)

  backendProcess = spawn(launch.command, launch.args, {
    cwd: launch.cwd,
    stdio: 'inherit',
    shell: false,
    env: {
      ...process.env,
      BACKEND_BASE_URL: backendBaseUrl,
      MOBILE_AI_TESTOPS_RUNTIME_ROOT: resourceRoot,
    },
  })

  backendProcess.on('error', (err) => console.error('Failed to start backend:', err))
}

// IPC handlers
ipcMain.handle('get-backend-url', () => backendBaseUrl)
ipcMain.handle('get-app-version', () => app.getVersion())
ipcMain.handle('is-dev', () => isDev)
ipcMain.on('open-external', (event, url) => shell.openExternal(url))

// scrcpy management
function scrcpyBinaryPath() {
  const candidates = [
    path.join(resourceRoot, 'tools', 'scrcpy-win64', 'scrcpy.exe'),
    path.join(__dirname, '..', 'tools', 'scrcpy-win64', 'scrcpy.exe'),
    path.join(__dirname, '..', 'backend', 'tools', 'scrcpy-win64', 'scrcpy.exe'),
  ]
  return candidates.find(p => fs.existsSync(p)) || 'scrcpy'
}

function adbBinaryPath() {
  const candidates = [
    path.join(resourceRoot, 'tools', 'scrcpy-win64', 'adb.exe'),
    path.join(__dirname, '..', 'tools', 'scrcpy-win64', 'adb.exe'),
    path.join(__dirname, '..', 'tools', 'platform-tools', 'adb.exe'),
    path.join(__dirname, '..', 'backend', 'tools', 'scrcpy-win64', 'adb.exe'),
  ]
  return candidates.find(p => fs.existsSync(p)) || 'adb'
}

function isChildProcessRunning(childProcess) {
  return Boolean(
    childProcess &&
    childProcess.pid &&
    childProcess.exitCode === null &&
    !childProcess.killed,
  )
}

function waitForProcessStartup(childProcess, label, detailProvider = () => '', timeoutMs = 900) {
  return new Promise((resolve) => {
    let settled = false
    const finish = (result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      childProcess.removeListener('error', onError)
      childProcess.removeListener('exit', onExit)
      resolve(result)
    }
    const onError = (err) => {
      const detail = detailProvider()
      finish({
        running: false,
        error: `${label} 启动失败: ${err.message || err}${detail ? ` (${detail})` : ''}`,
      })
    }
    const onExit = (code, signal) => {
      const detail = detailProvider()
      const exitText = signal ? `signal=${signal}` : `code=${code}`
      finish({
        running: false,
        error: `${label} 启动后立即退出: ${exitText}${detail ? ` (${detail})` : ''}`,
      })
    }
    const timer = setTimeout(() => {
      finish({ running: isChildProcessRunning(childProcess), pid: childProcess.pid })
    }, timeoutMs)
    childProcess.once('error', onError)
    childProcess.once('exit', onExit)
  })
}

function hwndBufferToDecimalString(buffer) {
  if (!buffer || buffer.length < 4) return '0'
  const hwnd = buffer.length >= 8 ? buffer.readBigUInt64LE(0) : BigInt(buffer.readUInt32LE(0))
  return hwnd.toString()
}

function runPowerShell(script, args = []) {
  const encodedArgBlob = args.map(arg => Buffer.from(String(arg), 'utf8').toString('base64')).join('|')
  const wrappedScript = `
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$argv = @()
$encodedArgBlob = "${encodedArgBlob}"
if ($encodedArgBlob.Length -gt 0) {
  foreach ($encodedArg in $encodedArgBlob.Split("|")) {
    $argv += [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encodedArg))
  }
}
${script}
`
  const encodedCommand = Buffer.from(wrappedScript, 'utf16le').toString('base64')
  return new Promise((resolve, reject) => {
    execFile(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encodedCommand],
      { windowsHide: true },
      (error, stdout, stderr) => {
        if (error) {
          error.message = `${error.message}${stderr ? `\n${stderr}` : ''}`
          logNativeScrcpy('powershell failed', error.message)
          reject(error)
          return
        }
        if (stderr) {
          logNativeScrcpy('powershell stderr', String(stderr))
        }
        resolve(String(stdout || '').trim())
      },
    )
  })
}

const win32Source = `
using System;
using System.Runtime.InteropServices;
public static class NativeWindowApi {
  [DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern IntPtr SetParent(IntPtr hWndChild, IntPtr hWndNewParent);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, UInt32 uFlags);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool RedrawWindow(IntPtr hWnd, IntPtr lprcUpdate, IntPtr hrgnUpdate, UInt32 flags);
  [DllImport("user32.dll", SetLastError=true, EntryPoint="GetWindowLongPtrW")]
  public static extern IntPtr GetWindowLongPtr64(IntPtr hWnd, int nIndex);
  [DllImport("user32.dll", SetLastError=true, EntryPoint="SetWindowLongPtrW")]
  public static extern IntPtr SetWindowLongPtr64(IntPtr hWnd, int nIndex, IntPtr dwNewLong);
  [DllImport("user32.dll", SetLastError=true, EntryPoint="GetWindowLongW")]
  public static extern int GetWindowLong32(IntPtr hWnd, int nIndex);
  [DllImport("user32.dll", SetLastError=true, EntryPoint="SetWindowLongW")]
  public static extern int SetWindowLong32(IntPtr hWnd, int nIndex, int dwNewLong);
  public static IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex) {
    return IntPtr.Size == 8 ? GetWindowLongPtr64(hWnd, nIndex) : new IntPtr(GetWindowLong32(hWnd, nIndex));
  }
  public static IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong) {
    return IntPtr.Size == 8 ? SetWindowLongPtr64(hWnd, nIndex, dwNewLong) : new IntPtr(SetWindowLong32(hWnd, nIndex, dwNewLong.ToInt32()));
  }
  public static IntPtr FindMainWindowByPid(uint pid) {
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
      uint windowPid;
      GetWindowThreadProcessId(hWnd, out windowPid);
      if (windowPid == pid && IsWindowVisible(hWnd)) {
        found = hWnd;
        return false;
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
`

function win32Prelude() {
  return `
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
${win32Source}
"@
`
}

async function findWindowByTitle(title) {
  if (process.platform !== 'win32') return null
  const script = `${win32Prelude()}
$title = $argv[0]
$hwnd = [NativeWindowApi]::FindWindow($null, $title)
if ($hwnd -eq [IntPtr]::Zero) { "" } else { $hwnd.ToInt64().ToString() }
`
  const output = await runPowerShell(script, [title])
  return output || null
}

async function waitForWindowByTitle(title, timeoutMs = 8000) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const hwnd = await findWindowByTitle(title)
    if (hwnd) return hwnd
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  return null
}

async function findWindowByPid(pid) {
  if (process.platform !== 'win32') return null
  const script = `${win32Prelude()}
$pidValue = [UInt32]$argv[0]
$hwnd = [NativeWindowApi]::FindMainWindowByPid($pidValue)
if ($hwnd -eq [IntPtr]::Zero) { "" } else { $hwnd.ToInt64().ToString() }
`
  const output = await runPowerShell(script, [pid])
  return output || null
}

async function waitForWindowByPid(pid, timeoutMs = 8000) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const hwnd = await findWindowByPid(pid)
    if (hwnd) return hwnd
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  return null
}

function normalizeNativeRect(rect = {}) {
  const scale = Number(rect.scaleFactor || 1) || 1
  const x = Math.max(0, Math.round(Number(rect.x || 0) * scale))
  const y = Math.max(0, Math.round(Number(rect.y || 0) * scale))
  const width = Math.max(1, Math.round(Number(rect.width || 1) * scale))
  const height = Math.max(1, Math.round(Number(rect.height || 1) * scale))
  return { x, y, width, height }
}

async function positionNativeWindow(parentHwnd, childHwnd, rect) {
  if (process.platform !== 'win32') return
  const bounds = normalizeNativeRect(rect)
const script = `${win32Prelude()}
$parent = [IntPtr]::new([Int64]$argv[0])
$child = [IntPtr]::new([Int64]$argv[1])
$x = [Int32]$argv[2]
$y = [Int32]$argv[3]
$w = [Int32]$argv[4]
$h = [Int32]$argv[5]
$GWL_STYLE = -16
$GWL_EXSTYLE = -20
$WS_CHILD = 0x40000000
$WS_POPUP = 0x80000000
$WS_CAPTION = 0x00C00000
$WS_THICKFRAME = 0x00040000
$WS_MINIMIZEBOX = 0x00020000
$WS_MAXIMIZEBOX = 0x00010000
$WS_EX_TRANSPARENT = 0x00000020
$WS_EX_NOACTIVATE = 0x08000000
$WS_EX_TOOLWINDOW = 0x00000080
$HWND_TOP = [IntPtr]::Zero
$SWP_NOACTIVATE = 0x0010
$SWP_SHOWWINDOW = 0x0040
$style = [NativeWindowApi]::GetWindowLongPtr($child, $GWL_STYLE).ToInt64()
$style = $style -bor $WS_CHILD
$style = $style -band (-bnot $WS_POPUP)
$style = $style -band (-bnot $WS_CAPTION)
$style = $style -band (-bnot $WS_THICKFRAME)
$style = $style -band (-bnot $WS_MINIMIZEBOX)
$style = $style -band (-bnot $WS_MAXIMIZEBOX)
[NativeWindowApi]::SetWindowLongPtr($child, $GWL_STYLE, [IntPtr]::new($style)) | Out-Null
$exStyle = [NativeWindowApi]::GetWindowLongPtr($child, $GWL_EXSTYLE).ToInt64()
$exStyle = $exStyle -bor $WS_EX_TRANSPARENT -bor $WS_EX_NOACTIVATE -bor $WS_EX_TOOLWINDOW
[NativeWindowApi]::SetWindowLongPtr($child, $GWL_EXSTYLE, [IntPtr]::new($exStyle)) | Out-Null
[NativeWindowApi]::SetParent($child, $parent) | Out-Null
[NativeWindowApi]::SetWindowPos($child, $HWND_TOP, $x, $y, $w, $h, $SWP_NOACTIVATE -bor $SWP_SHOWWINDOW) | Out-Null
[NativeWindowApi]::ShowWindow($child, 5) | Out-Null
"ok"
`
  return runPowerShell(script, [parentHwnd, childHwnd, bounds.x, bounds.y, bounds.width, bounds.height])
}

async function resizeNativeWindow(childHwnd, rect) {
  if (process.platform !== 'win32') return
  const bounds = normalizeNativeRect(rect)
  const script = `${win32Prelude()}
$child = [IntPtr]::new([Int64]$argv[0])
$x = [Int32]$argv[1]
$y = [Int32]$argv[2]
$w = [Int32]$argv[3]
$h = [Int32]$argv[4]
$HWND_TOP = [IntPtr]::Zero
$SWP_NOACTIVATE = 0x0010
$SWP_SHOWWINDOW = 0x0040
[NativeWindowApi]::SetWindowPos($child, $HWND_TOP, $x, $y, $w, $h, $SWP_NOACTIVATE -bor $SWP_SHOWWINDOW) | Out-Null
"ok"
`
  return runPowerShell(script, [childHwnd, bounds.x, bounds.y, bounds.width, bounds.height])
}

ipcMain.handle('scrcpy:start', async (event, udid, options = {}) => {
  if (isChildProcessRunning(scrcpyProcess)) {
    return { running: true, pid: scrcpyProcess.pid }
  }
  scrcpyProcess = null

  const maxSize = options.maxSize || 1280
  const maxFps = options.maxFps || 30
  const scrcpyPath = scrcpyBinaryPath()
  let scrcpyStderr = ''

  const args = [
    '--serial', udid,
    '--max-size', String(maxSize),
    '--max-fps', String(maxFps),
    '--window-title', `Mobile AI TestOps - ${udid}`,
    '--stay-awake',
    '--no-audio',
  ]

  let childProcess
  try {
    childProcess = spawn(scrcpyPath, args, {
      stdio: ['ignore', 'ignore', 'pipe'],
      windowsHide: false,
    })
  } catch (err) {
    return { running: false, error: err.message }
  }

  scrcpyProcess = childProcess
  childProcess.stderr?.on('data', chunk => {
    scrcpyStderr += chunk.toString()
    if (scrcpyStderr.length > 4000) scrcpyStderr = scrcpyStderr.slice(-4000)
  })
  childProcess.on('error', () => {
    if (scrcpyProcess === childProcess) scrcpyProcess = null
  })
  childProcess.on('exit', () => {
    if (scrcpyProcess === childProcess) scrcpyProcess = null
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('scrcpy:exited')
    }
  })

  const startup = await waitForProcessStartup(
    childProcess,
    'scrcpy',
    () => scrcpyStderr.trim(),
  )
  if (!startup.running) {
    if (scrcpyProcess === childProcess) scrcpyProcess = null
    return startup
  }

  return { running: true, pid: childProcess.pid }
})

ipcMain.handle('scrcpy:native-start', async (event, udid, options = {}) => {
  logNativeScrcpy('native-start requested', JSON.stringify({ udid, options }))
  if (process.platform !== 'win32') {
    return { running: false, error: 'Electron 原生嵌入投屏目前只支持 Windows' }
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return { running: false, error: 'Electron 主窗口不可用' }
  }
  if (scrcpyNative?.process && scrcpyNative.process.pid && !scrcpyNative.process.killed) {
    if (options.rect && scrcpyNative.hwnd) {
      await resizeNativeWindow(scrcpyNative.hwnd, options.rect)
    }
    return { running: true, pid: scrcpyNative.process.pid, hwnd: scrcpyNative.hwnd }
  }

  const maxSize = options.maxSize || 1280
  const maxFps = options.maxFps || 60
  const renderDriver = options.renderDriver || process.env.SCRCPY_NATIVE_RENDER_DRIVER || 'opengl'
  const title = `Mobile AI TestOps Native Surface - ${udid} - ${Date.now()}`
  const scrcpyPath = scrcpyBinaryPath()
  const parentHwnd = hwndBufferToDecimalString(mainWindow.getNativeWindowHandle())
  const initialRect = normalizeNativeRect(options.rect || { x: 0, y: 0, width: 480, height: 720, scaleFactor: 1 })
  const args = [
    '--serial', udid,
    '--max-size', String(maxSize),
    '--max-fps', String(maxFps),
    '--window-title', title,
    '--window-borderless',
    '--window-x', String(initialRect.x),
    '--window-y', String(initialRect.y),
    '--window-width', String(initialRect.width),
    '--window-height', String(initialRect.height),
    '--render-driver', renderDriver,
    '--stay-awake',
    '--no-audio',
  ]

  let childProcess
  try {
    childProcess = spawn(scrcpyPath, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: false })
    logNativeScrcpy('scrcpy spawned', JSON.stringify({ pid: childProcess.pid, scrcpyPath, args }))
  } catch (err) {
    logNativeScrcpy('scrcpy spawn failed', err.message || String(err))
    return { running: false, error: err.message }
  }

  scrcpyNative = { process: childProcess, hwnd: null, title }
  let scrcpyStdout = ''
  let scrcpyStderr = ''
  childProcess.stdout?.on('data', chunk => {
    scrcpyStdout += chunk.toString()
    if (scrcpyStdout.length > 8000) scrcpyStdout = scrcpyStdout.slice(-8000)
  })
  childProcess.stderr?.on('data', chunk => {
    scrcpyStderr += chunk.toString()
    if (scrcpyStderr.length > 8000) scrcpyStderr = scrcpyStderr.slice(-8000)
  })
  childProcess.on('exit', () => {
    logNativeScrcpy('scrcpy exited', JSON.stringify({ stdout: scrcpyStdout, stderr: scrcpyStderr }))
    scrcpyNative = null
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('scrcpy:native-exited')
    }
  })

  try {
    const hwnd = await waitForWindowByPid(childProcess.pid) || await waitForWindowByTitle(title)
    if (!hwnd) {
      const errorDetail = `scrcpy 窗口创建超时，无法嵌入 Electron。stdout=${scrcpyStdout.trim()} stderr=${scrcpyStderr.trim()}`
      logNativeScrcpy('native-start no hwnd', errorDetail)
      childProcess.kill()
      scrcpyNative = null
      return { running: false, error: errorDetail }
    }
    // Allow scrcpy/SDL to finish initializing its renderer before reparenting.
    await new Promise(resolve => setTimeout(resolve, 600))
    await positionNativeWindow(parentHwnd, hwnd, options.rect || { x: 0, y: 0, width: 480, height: 720, scaleFactor: 1 })
    logNativeScrcpy('native-start embedded', JSON.stringify({ pid: childProcess.pid, hwnd, parentHwnd }))
    if (scrcpyNative) scrcpyNative.hwnd = hwnd
    return { running: true, pid: childProcess.pid, hwnd }
  } catch (err) {
    logNativeScrcpy('native-start failed', err.message || String(err))
    childProcess.kill()
    scrcpyNative = null
    return { running: false, error: err.message || String(err) }
  }
})

ipcMain.handle('scrcpy:native-resize', async (event, rect = {}) => {
  if (!scrcpyNative?.hwnd) {
    return { resized: false }
  }
  try {
    await resizeNativeWindow(scrcpyNative.hwnd, rect)
    return { resized: true }
  } catch (err) {
    return { resized: false, error: err.message || String(err) }
  }
})

ipcMain.handle('scrcpy:native-stop', () => {
  if (!scrcpyNative?.process || scrcpyNative.process.killed) {
    scrcpyNative = null
    return { stopped: false }
  }
  scrcpyNative.process.kill()
  scrcpyNative = null
  return { stopped: true }
})

ipcMain.handle('scrcpy:native-status', () => {
  const running = scrcpyNative?.process && scrcpyNative.process.pid && !scrcpyNative.process.killed
  return { running: !!running, pid: running ? scrcpyNative.process.pid : null, hwnd: running ? scrcpyNative.hwnd : null }
})

ipcMain.handle('scrcpy:stop', () => {
  if (!isChildProcessRunning(scrcpyProcess)) {
    scrcpyProcess = null
    return { stopped: false }
  }
  scrcpyProcess.kill()
  scrcpyProcess = null
  return { stopped: true }
})

ipcMain.handle('scrcpy:status', () => {
  const running = isChildProcessRunning(scrcpyProcess)
  return { running: !!running, pid: running ? scrcpyProcess.pid : null }
})

ipcMain.handle('device:screen-size', async (event, udid) => {
  return new Promise((resolve) => {
    execFile(adbBinaryPath(), ['-s', udid, 'shell', 'wm', 'size'], { windowsHide: true }, (error, stdout, stderr) => {
      if (error) {
        resolve({ ok: false, error: stderr || error.message })
        return
      }
      const match = String(stdout || '').match(/(\d+)x(\d+)/)
      if (!match) {
        resolve({ ok: false, error: `cannot parse screen size: ${stdout}` })
        return
      }
      resolve({ ok: true, width: Number(match[1]), height: Number(match[2]) })
    })
  })
})

app.whenReady().then(async () => {
  await pickBackendLaunchUrl()

  const existingBackendReady = await waitForHttp(`${backendBaseUrl}/api/health`, 'backend server', 1, false)
  if (!existingBackendReady) {
    startBackend()
    const backendReady = await waitForHttp(`${backendBaseUrl}/api/health`, 'backend server')
    if (!backendReady) {
      console.error('Backend server did not start in time')
    }
  }

  if (isDev) {
    console.log('Waiting for Vite dev server...')
    const viteReady = await waitForHttp(viteDevUrl, 'Vite dev server')
    if (!viteReady) {
      console.error('Vite dev server did not start in time')
      app.quit()
      return
    }
  }

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    console.log('Stopping backend...')
    backendProcess.kill()
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  if (backendProcess) backendProcess.kill()
  if (scrcpyProcess) scrcpyProcess.kill()
  if (scrcpyNative?.process) scrcpyNative.process.kill()
})
