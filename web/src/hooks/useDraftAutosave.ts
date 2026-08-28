import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReviewApiError, type DraftPatchInput, type DraftPatchResponse } from '../editingApi'

export type AutosaveStatus = 'clean' | 'dirty' | 'saving' | 'saved' | 'failed' | 'conflict'

export type AutosaveFieldDefinition = {
  key: string
  path: string
  value: string
}

export type AutosaveFieldState = {
  value: string
  status: AutosaveStatus
  queued: boolean
}

type Options = {
  version: number
  fields: AutosaveFieldDefinition[]
  enabled: boolean
  onSave: (input: DraftPatchInput) => Promise<DraftPatchResponse>
  delay?: number
}

async function hash(value: string) {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

function initialState(fields: AutosaveFieldDefinition[]): Record<string, AutosaveFieldState> {
  return Object.fromEntries(fields.map((field) => [field.key, {
    value: field.value,
    status: 'clean' as const,
    queued: false,
  }]))
}

export default function useDraftAutosave({ version, fields: definitions, enabled, onSave, delay = 800 }: Options) {
  const definitionSignature = JSON.stringify(definitions)
  const [fields, setFields] = useState<Record<string, AutosaveFieldState>>(() => initialState(definitions))
  const fieldsRef = useRef(fields)
  const definitionsRef = useRef(new Map(definitions.map((field) => [field.key, field])))
  const baselinesRef = useRef(new Map(definitions.map((field) => [field.key, field.value])))
  const versionRef = useRef(version)
  const enabledRef = useRef(enabled)
  const onSaveRef = useRef(onSave)
  const mountedRef = useRef(true)
  const processingRef = useRef(false)
  const queueRef = useRef<string[]>([])
  const debounceTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const savedTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  enabledRef.current = enabled
  onSaveRef.current = onSave
  versionRef.current = Math.max(versionRef.current, version)

  const commit = useCallback((update: (current: Record<string, AutosaveFieldState>) => Record<string, AutosaveFieldState>) => {
    if (!mountedRef.current) return
    setFields((current) => {
      const next = update(current)
      fieldsRef.current = next
      return next
    })
  }, [])

  const clearDebounce = useCallback((key: string) => {
    const timer = debounceTimersRef.current.get(key)
    if (timer) clearTimeout(timer)
    debounceTimersRef.current.delete(key)
  }, [])

  const processQueueRef = useRef<() => Promise<void>>(async () => undefined)

  const enqueue = useCallback((key: string) => {
    if (!enabledRef.current) return
    clearDebounce(key)
    if (!queueRef.current.includes(key)) queueRef.current.push(key)
    void processQueueRef.current()
  }, [clearDebounce])

  processQueueRef.current = async () => {
    if (processingRef.current || !enabledRef.current) return
    const key = queueRef.current.shift()
    if (!key) return
    const state = fieldsRef.current[key]
    const definition = definitionsRef.current.get(key)
    const baseline = baselinesRef.current.get(key)
    if (!state || !definition || baseline === undefined || state.value === baseline) {
      if (state && state.status !== 'clean') {
        commit((current) => ({ ...current, [key]: { ...current[key], status: 'clean', queued: false } }))
      }
      void processQueueRef.current()
      return
    }

    processingRef.current = true
    const snapshot = state.value
    const baseVersion = versionRef.current
    commit((current) => ({ ...current, [key]: { ...current[key], status: 'saving', queued: false } }))
    try {
      const result = await onSaveRef.current({
        base_version: baseVersion,
        path: definition.path,
        old_value_hash: await hash(baseline),
        value: snapshot,
      })
      versionRef.current = Math.max(versionRef.current, result.version)
      baselinesRef.current.set(key, snapshot)
      if (!mountedRef.current) return
      const hasNewerValue = fieldsRef.current[key]?.value !== snapshot
      commit((current) => ({
        ...current,
        [key]: { ...current[key], status: hasNewerValue ? 'dirty' : 'saved', queued: hasNewerValue },
      }))
      if (hasNewerValue) {
        if (!queueRef.current.includes(key)) queueRef.current.push(key)
      } else {
        const previousTimer = savedTimersRef.current.get(key)
        if (previousTimer) clearTimeout(previousTimer)
        savedTimersRef.current.set(key, setTimeout(() => {
          if (fieldsRef.current[key]?.status === 'saved') {
            commit((current) => ({ ...current, [key]: { ...current[key], status: 'clean' } }))
          }
        }, 1200))
      }
    } catch (error) {
      if (!mountedRef.current) return
      const status: AutosaveStatus = error instanceof ReviewApiError && error.code === 'CONFLICT'
        ? 'conflict'
        : 'failed'
      commit((current) => ({ ...current, [key]: { ...current[key], status, queued: false } }))
    } finally {
      processingRef.current = false
      if (mountedRef.current) void processQueueRef.current()
    }
  }

  const setValue = useCallback((key: string, value: string) => {
    if (!enabledRef.current) return
    clearDebounce(key)
    const baseline = baselinesRef.current.get(key)
    const current = fieldsRef.current[key]
    const saving = current?.status === 'saving'
    commit((items) => ({
      ...items,
      [key]: {
        ...items[key],
        value,
        status: saving ? 'saving' : value === baseline ? 'clean' : 'dirty',
        queued: saving && value !== baseline,
      },
    }))
    if (value !== baseline) {
      debounceTimersRef.current.set(key, setTimeout(() => enqueue(key), delay))
    }
  }, [clearDebounce, commit, delay, enqueue])

  const flush = useCallback((key: string) => {
    const state = fieldsRef.current[key]
    const baseline = baselinesRef.current.get(key)
    if (state && state.value !== baseline && state.status !== 'conflict') enqueue(key)
  }, [enqueue])

  const retry = useCallback((key: string) => {
    const state = fieldsRef.current[key]
    if (!state || state.value === baselinesRef.current.get(key)) return
    commit((current) => ({ ...current, [key]: { ...current[key], status: 'dirty' } }))
    enqueue(key)
  }, [commit, enqueue])

  useEffect(() => {
    definitionsRef.current = new Map(definitions.map((field) => [field.key, field]))
    const nextBaselines = new Map(baselinesRef.current)
    definitions.forEach((definition) => nextBaselines.set(definition.key, definition.value))
    baselinesRef.current = nextBaselines
    commit((current) => {
      const next = { ...current }
      definitions.forEach((definition) => {
        const previous = current[definition.key]
        if (!previous || previous.status === 'clean' || previous.status === 'saved') {
          next[definition.key] = { value: definition.value, status: 'clean', queued: false }
        }
      })
      return next
    })
  }, [commit, definitionSignature, version])

  useEffect(() => {
    if (enabled) return
    debounceTimersRef.current.forEach(clearTimeout)
    debounceTimersRef.current.clear()
    queueRef.current = []
  }, [enabled])

  useEffect(() => () => {
    mountedRef.current = false
    debounceTimersRef.current.forEach(clearTimeout)
    savedTimersRef.current.forEach(clearTimeout)
  }, [])

  const hasPending = useMemo(
    () => Object.values(fields).some((field) => ['dirty', 'saving', 'failed', 'conflict'].includes(field.status)),
    [fields],
  )
  const hasConflict = useMemo(
    () => Object.values(fields).some((field) => field.status === 'conflict'),
    [fields],
  )

  return { fields, setValue, flush, retry, hasPending, hasConflict }
}
