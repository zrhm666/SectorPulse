import { spawn } from 'node:child_process'
import { once } from 'node:events'

const host = '127.0.0.1'
const port = 4173
const baseURL = `http://${host}:${port}`

function spawnNode(modulePath, args) {
  return spawn(process.execPath, [modulePath, ...args], {
    cwd: process.cwd(),
    stdio: 'inherit',
    windowsHide: true,
  })
}

async function waitForPreview(processHandle) {
  const deadline = Date.now() + 30_000

  while (Date.now() < deadline) {
    if (processHandle.exitCode !== null) {
      throw new Error(`Vite preview exited before becoming ready (code ${processHandle.exitCode})`)
    }
    try {
      const response = await fetch(baseURL)
      if (response.ok) return
    } catch {
      // The preview process is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }

  throw new Error(`Vite preview did not become ready at ${baseURL}`)
}

async function terminate(processHandle) {
  if (processHandle.exitCode !== null) return
  processHandle.kill()
  await Promise.race([
    once(processHandle, 'exit'),
    new Promise((_, reject) => setTimeout(() => reject(new Error('Vite preview did not exit')), 5_000)),
  ])
}

const preview = spawnNode('node_modules/vite/bin/vite.js', [
  'preview', '--host', host, '--port', String(port), '--strictPort',
])

let exitCode = 1
try {
  await waitForPreview(preview)
  const playwright = spawnNode('node_modules/@playwright/test/cli.js', ['test', ...process.argv.slice(2)])
  const [code] = await once(playwright, 'exit')
  exitCode = typeof code === 'number' ? code : 1
} finally {
  await terminate(preview)
}

process.exitCode = exitCode
