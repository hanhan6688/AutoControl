import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchPCAgentModelConfig,
  updatePCAgentModelConfig,
  fetchPCAgentModelPresets,
  testPCAgentModel,
  type PCAgentModelConfig,
  type PCAgentModelConfigUpdate,
  type PCAgentProviderPreset,
} from '../api'

export function usePcAgentModel() {
  const modelConfig = ref<PCAgentModelConfig>({
    enabled: false,
    provider: '',
    base_url: '',
    model: '',
    api_key_masked: '',
    timeout_seconds: 30,
    temperature: 0.7,
    max_tokens: 4096,
    configured: false,
    presets: [],
  })
  const modelPresets = ref<PCAgentProviderPreset[]>([])
  const modelBusy = ref(false)
  const modelTesting = ref(false)

  const modelForm = ref<PCAgentModelConfigUpdate>({
    enabled: true,
    provider: '',
    base_url: '',
    model: '',
    api_key: '',
    timeout_seconds: 30,
    temperature: 0.7,
    max_tokens: 4096,
  })

  const currentModelLabel = computed(() => {
    const config = modelConfig.value
    if (!config.provider) return '未配置'
    const preset = modelPresets.value.find(p => p.id === config.provider)
    return preset ? preset.name : config.provider
  })

  const apiKeyPlaceholder = computed(() => {
    const preset = modelPresets.value.find(p => p.id === modelForm.value.provider)
    return preset?.api_key_label || 'API Key'
  })

  async function loadModelConfig() {
    modelBusy.value = true
    try {
      modelConfig.value = await fetchPCAgentModelConfig()
      modelPresets.value = modelConfig.value.presets ?? []
      modelForm.value = {
        enabled: modelConfig.value.enabled,
        provider: modelConfig.value.provider,
        base_url: modelConfig.value.base_url,
        model: modelConfig.value.model,
        api_key: '',
        timeout_seconds: modelConfig.value.timeout_seconds,
        temperature: modelConfig.value.temperature,
        max_tokens: modelConfig.value.max_tokens,
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '加载模型配置失败')
    } finally {
      modelBusy.value = false
    }
  }

  function applyPreset(preset: PCAgentProviderPreset) {
    modelForm.value.provider = preset.id
    modelForm.value.base_url = preset.base_url
    modelForm.value.model = preset.default_model
  }

  async function saveModelConfig() {
    modelBusy.value = true
    try {
      modelConfig.value = await updatePCAgentModelConfig(modelForm.value)
      ElMessage.success('模型配置已保存')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '保存模型配置失败')
    } finally {
      modelBusy.value = false
    }
  }

  async function testModelConfig() {
    modelTesting.value = true
    try {
      const result = await testPCAgentModel(undefined, modelForm.value)
      if (result.ok) {
        ElMessage.success('模型连接测试成功')
      } else {
        ElMessage.error(result.error || '模型连接测试失败')
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '测试失败')
    } finally {
      modelTesting.value = false
    }
  }

  return {
    modelConfig,
    modelPresets,
    modelForm,
    modelBusy,
    modelTesting,
    currentModelLabel,
    apiKeyPlaceholder,
    loadModelConfig,
    applyPreset,
    saveModelConfig,
    testModelConfig,
    currentProvider: () => modelForm.value.provider,
    currentModel: () => modelForm.value.model || null,
  }
}