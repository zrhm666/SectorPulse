import { spawn } from 'node:child_process'
import { once } from 'node:events'

const host = '127.0.0.1'
const port = 4173
const baseURL = `http://${host}:${port}`
const development = process.argv.includes('--dev')
const playwrightArgs = process.argv.slice(2).filter((arg) => arg !== '--dev')

function spawnNode(modulePath, args) {
  return spawn(process.execPath, [modulePath, ...args], {
    cwd: process.cwd(),
    stdio: 'inherit',
    windowsHide: true,
    env: { ...process.env, SECTOR_PULSE_E2E_DEV_MODE: development ? '1' : '0' },
  })
}

async function waitForServer(processHandle) {
  const deadline = Date.now() + 30_000

  while (Date.now() < deadline) {
    if (processHandle.exitCode !== null) {
      throw new Error(`Vite server exited before becoming ready (code ${processHandle.exitCode})`)
    }
    try {
      const response = await fetch(baseURL)
      if (response.ok) return
    } catch {
      // The Vite process is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }

  throw new Error(`Vite server did not become ready at ${baseURL}`)
}

async function terminate(processHandle) {
  if (processHandle.exitCode !== null) return
  processHandle.kill()
  await Promise.race([
    once(processHandle, 'exit'),
    new Promise((_, reject) => setTimeout(() => reject(new Error('Vite server did not exit')), 5_000)),
  ])
}

const server = spawnNode('node_modules/vite/bin/vite.js', [
  ...(development ? [] : ['preview']), '--host', host, '--port', String(port), '--strictPort',
])

let exitCode = 1
try {
  await waitForServer(server)
  const playwright = spawnNode('node_modules/@playwright/test/cli.js', ['test', ...playwrightArgs])
  const [code] = await once(playwright, 'exit')
  exitCode = typeof code === 'number' ? code : 1
} finally {
  await terminate(server)
}

process.exitCode = exitCode
