import assert from 'node:assert/strict'
import { once } from 'node:events'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer as createHttpServer } from 'node:http'
import path from 'node:path'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer, resolveConfig } from 'vite'

const webRoot = fileURLToPath(new URL('../', import.meta.url))
const temporaryRoot = path.join(webRoot, '.tmp')
const probe = 'sectorpulse-public-probe'
let fixture
let backend
let vite
let baseURL

before(async () => {
  await mkdir(temporaryRoot, { recursive: true })
  fixture = await mkdtemp(path.join(temporaryRoot, 'vite-runtime-'))
  await writeFile(path.join(fixture, '.env'), `NON_SECRET_TOOLCHAIN_PROBE=${probe}\n`)
  await writeFile(path.join(fixture, 'index.html'), '<div id="root"></div><script type="module" src="/entry.tsx"></script>')
  await writeFile(path.join(fixture, 'entry.tsx'), 'export default function App() { return <div>toolchain-fixture</div> }')

  backend = createHttpServer((request, response) => {
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ path: request.url, source: 'local-fixture' }))
  })
  backend.listen(0, '127.0.0.1')
  await once(backend, 'listening')
  const configFile = path.join(webRoot, 'vite.config.ts')
  const configured = await resolveConfig({ configFile, root: fixture, envDir: fixture }, 'serve')
  const target = `http://127.0.0.1:${backend.address().port}`
  // Keep the project's proxy route selection; only replace the external target.
  const proxy = Object.fromEntries(Object.entries(configured.server.proxy ?? {}).map(([route, options]) => [
    route, typeof options === 'string' ? target : { ...options, target },
  ]))
  vite = await createServer({
    configFile, root: fixture, envDir: fixture, logLevel: 'silent',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { host: '127.0.0.1', port: 0, strictPort: true, proxy, fs: { allow: [fixture] } },
  })
  await vite.listen()
  baseURL = `http://127.0.0.1:${vite.httpServer.address().port}`
}, { timeout: 20_000 })

after(async () => {
  if (backend?.listening) {
    backend.closeAllConnections()
    await new Promise((resolve, reject) => backend.close((error) => error ? reject(error) : resolve()))
  }
  vite?.httpServer?.closeAllConnections()
  await vite?.close()
  if (fixture) {
    assert.equal(path.dirname(path.resolve(fixture)), path.resolve(temporaryRoot))
    await rm(fixture, { recursive: true, force: true })
  }
}, { timeout: 10_000 })

test('the project React plugin serves compiled TSX in development', async () => {
  const response = await fetch(`${baseURL}/entry.tsx`)
  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-type'), /javascript/)
  const code = await response.text()
  assert.match(code, /toolchain-fixture/)
  assert.doesNotMatch(code, /return <div>/)
})

test('the configured API proxy preserves paths and query parameters', async () => {
  const response = await fetch(`${baseURL}/api/health?probe=1`)
  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), { path: '/api/health?probe=1', source: 'local-fixture' })
})

test('the development server refuses a synthetic environment file', async () => {
  const response = await fetch(`${baseURL}/.env?raw`)
  assert.equal(response.status, 403)
  assert.equal((await response.text()).includes(probe), false)
})

test('Windows alternate data stream paths cannot expose the synthetic environment file', {
  skip: process.platform !== 'win32',
}, async () => {
  const response = await fetch(`${baseURL}/.env::$DATA?raw`)
  assert.equal(response.status, 403)
  assert.equal((await response.text()).includes(probe), false)
})
