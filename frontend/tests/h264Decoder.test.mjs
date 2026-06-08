import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { after, test } from 'node:test'
import ts from '../node_modules/typescript/lib/typescript.js'

const root = resolve(import.meta.dirname, '..')
const tempDir = mkdtempSync(join(tmpdir(), 'h264-decoder-test-'))

after(() => {
  rmSync(tempDir, { recursive: true, force: true })
})

function compileModule(sourcePath, outputName, transform = (code) => code) {
  const source = readFileSync(resolve(root, sourcePath), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText
  writeFileSync(join(tempDir, outputName), transform(output))
}

compileModule('src/h264MseDecoder.ts', 'h264MseDecoder.mjs')
compileModule('src/h264Decoder.ts', 'h264Decoder.mjs', (code) =>
  code.replace("from './h264MseDecoder'", "from './h264MseDecoder.mjs'"),
)

const decoderModuleUrl = pathToFileURL(join(tempDir, 'h264Decoder.mjs')).href

function mockCanvas() {
  return {
    getContext() {
      return {
        drawImage() {},
      }
    },
  }
}

function installWebCodecsSupport() {
  globalThis.VideoDecoder = class {
    state = 'unconfigured'

    configure() {
      this.state = 'configured'
    }

    decode() {}

    close() {
      this.state = 'closed'
    }
  }
  globalThis.EncodedVideoChunk = class {}
}

function removeWebCodecsSupport() {
  globalThis.VideoDecoder = undefined
  globalThis.EncodedVideoChunk = undefined
}

function installMseSupport() {
  globalThis.MediaSource = class {}
  globalThis.MediaSource.isTypeSupported = () => true
}

test('prefers WebCodecs when both WebCodecs and MSE are available', async () => {
  installWebCodecsSupport()
  installMseSupport()

  const { createH264Decoder } = await import(decoderModuleUrl)
  const { mode } = createH264Decoder(mockCanvas(), () => {}, 30)

  assert.equal(mode, 'webcodecs')
})

test('falls back to MSE when WebCodecs is unavailable', async () => {
  removeWebCodecsSupport()
  installMseSupport()

  const { createH264Decoder } = await import(decoderModuleUrl)
  const { mode } = createH264Decoder(mockCanvas(), () => {}, 30)

  assert.equal(mode, 'mse')
})
