const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  isDev: () => ipcRenderer.invoke('is-dev'),
  openExternal: (url) => ipcRenderer.send('open-external', url),
  isElectron: true,
  platform: process.platform,
  getScreenStreamConfig: () => ({
    preferH264: true,
    maxFps: 30,
    maxSize: 1280,
  }),
  scrcpyStart: (udid, options) => ipcRenderer.invoke('scrcpy:start', udid, options),
  scrcpyStop: () => ipcRenderer.invoke('scrcpy:stop'),
  scrcpyStatus: () => ipcRenderer.invoke('scrcpy:status'),
  getDeviceScreenSize: (udid) => ipcRenderer.invoke('device:screen-size', udid),
  scrcpyNativeStart: (udid, options) => ipcRenderer.invoke('scrcpy:native-start', udid, options),
  scrcpyNativeResize: (rect) => ipcRenderer.invoke('scrcpy:native-resize', rect),
  scrcpyNativeStop: () => ipcRenderer.invoke('scrcpy:native-stop'),
  scrcpyNativeStatus: () => ipcRenderer.invoke('scrcpy:native-status'),
  onScrcpyExited: (callback) => {
    ipcRenderer.on('scrcpy:exited', () => callback())
  },
  removeScrcpyExitedListener: () => {
    ipcRenderer.removeAllListeners('scrcpy:exited')
  },
  onScrcpyNativeExited: (callback) => {
    ipcRenderer.on('scrcpy:native-exited', () => callback())
  },
  removeScrcpyNativeExitedListener: () => {
    ipcRenderer.removeAllListeners('scrcpy:native-exited')
  },
})
