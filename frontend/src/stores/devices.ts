import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchDevices,
  getDeviceScreenWebSocketUrl,
  connectDevice as apiConnectDevice,
  disconnectDevice as apiDisconnectDevice,
  type DeviceInfo,
} from '../api'

export const useDeviceStore = defineStore('devices', () => {
  const devices = ref<DeviceInfo[]>([])
  const activeDevice = ref<DeviceInfo | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const refreshTimer = ref<number | null>(null)
  const lastFetchTime = ref<number>(0)
  const cacheValidMs = 3000 // Cache valid for 3 seconds

  const onlineDevices = computed(() =>
    devices.value.filter(d => d.status === 'online')
  )

  const androidDevices = computed(() =>
    devices.value.filter(d => d.platform === 'android')
  )

  const iosDevices = computed(() =>
    devices.value.filter(d => d.platform === 'ios')
  )

  const harmonyDevices = computed(() =>
    devices.value.filter(d => d.platform === 'harmony')
  )

  function devicesEqual(a: DeviceInfo[], b: DeviceInfo[]): boolean {
    if (a.length !== b.length) return false
    const key = (d: DeviceInfo) =>
      `${d.udid}|${d.status}|${d.model || ''}|${d.product || ''}|${d.platform || ''}`
    const aKeys = [...a].map(key).sort()
    const bKeys = [...b].map(key).sort()
    return aKeys.every((k, i) => k === bKeys[i])
  }

  async function loadDevices(showLoading = true, forceRefresh = false) {
    // Check cache
    const now = Date.now()
    if (!forceRefresh && now - lastFetchTime.value < cacheValidMs && devices.value.length > 0) {
      return devices.value
    }

    if (showLoading) loading.value = true
    error.value = null
    try {
      const newDevices = await fetchDevices()
      lastFetchTime.value = now
      if (!devicesEqual(devices.value, newDevices)) {
        devices.value = newDevices
        // Keep the selected device synchronized with the latest poll result.
        const selected = activeDevice.value
          ? devices.value.find(d => d.udid === activeDevice.value?.udid)
          : null
        if (selected) {
          activeDevice.value = selected
        } else {
          const firstOnline = devices.value.find(d => d.status === 'online')
          activeDevice.value = firstOnline ?? null
        }
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取设备列表失败'
    } finally {
      if (showLoading) loading.value = false
    }
  }

  function setActiveDevice(device: DeviceInfo | null) {
    activeDevice.value = device
  }

  // Optimistic update for device connection
  async function connectToDevice(address: string) {
    // Optimistically add device
    const tempDevice: DeviceInfo = {
      udid: address,
      status: 'online',
      platform: 'android',
      model: 'Connecting...',
    }
    devices.value = [...devices.value, tempDevice]

    try {
      const result = await apiConnectDevice(address)
      if (result.success) {
        // Refresh to get actual device info
        await loadDevices(false, true)
        return result
      } else {
        // Remove optimistic device on failure
        devices.value = devices.value.filter(d => d.udid !== address)
        return result
      }
    } catch (e) {
      // Remove optimistic device on error
      devices.value = devices.value.filter(d => d.udid !== address)
      throw e
    }
  }

  // Optimistic update for device disconnection
  async function disconnectFromDevice(address: string) {
    const previousDevices = [...devices.value]
    // Optimistically remove device
    devices.value = devices.value.filter(d => d.udid !== address)
    if (activeDevice.value?.udid === address) {
      activeDevice.value = null
    }

    try {
      await apiDisconnectDevice(address)
    } catch (e) {
      // Restore on error
      devices.value = previousDevices
      throw e
    }
  }

  function getScreenWsUrl(device: DeviceInfo, options: { maxFps?: number; maxSize?: number } = {}) {
    return getDeviceScreenWebSocketUrl(device.udid, {
      platform: device.platform,
      provider: 'scrcpy-ffmpeg-mjpeg',
      maxFps: options.maxFps ?? 15,
      maxSize: options.maxSize ?? 960,
    })
  }

  function startAutoRefresh(intervalMs = 5000) {
    stopAutoRefresh()
    refreshTimer.value = window.setInterval(() => loadDevices(false), intervalMs)
  }

  function stopAutoRefresh() {
    if (refreshTimer.value) {
      clearInterval(refreshTimer.value)
      refreshTimer.value = null
    }
  }

  // Invalidate cache to force refresh
  function invalidateCache() {
    lastFetchTime.value = 0
  }

  return {
    devices,
    activeDevice,
    loading,
    error,
    onlineDevices,
    androidDevices,
    iosDevices,
    harmonyDevices,
    loadDevices,
    setActiveDevice,
    connectToDevice,
    disconnectFromDevice,
    getScreenWsUrl,
    startAutoRefresh,
    stopAutoRefresh,
    invalidateCache,
  }
})
