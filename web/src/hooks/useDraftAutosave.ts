import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReviewApiError, type DraftPatchInput, type DraftPatchResponse } from '../editingApi'
import {
  createAutosaveMachine,
  reduceAutosave,
  type AutosaveEvent,
  type AutosaveFieldDefinition,
  type AutosaveFieldState,
  type AutosaveMachineState,
} from './draftAutosaveMachine'

export type {
  AutosaveFieldDefinition,
  AutosaveFieldState,
  AutosaveStatus,
} from './draftAutosaveMachine'

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
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

export default function useDraftAutosave({
  version,
  fields: definitions,
  enabled,
  onSave,
  delay = 800,
}: Options) {
  const definitionSignature = JSON.stringify(definitions)
  const [machine, setMachine] = useState<AutosaveMachineState>(() => (
    createAutosaveMachine(version, definitions)
  ))
  const machineRef = useRef(machine)
  const enabledRef = useRef(enabled)
  const onSaveRef = useRef(onSave)
  const mountedRef = useRef(true)
  const processingRef = useRef(false)
  const queueRef = useRef<string[]>([])
  const debounceTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const savedTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  enabledRef.current = enabled
  onSaveRef.current = onSave

  const send = useCallback((event: AutosaveEvent) => {
    const next = reduceAutosave(machineRef.current, event)
    machineRef.current = next
    if (mountedRef.current) setMachine(next)
    return next
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
    const field = machineRef.current.fields[key]
    if (!field || field.value === field.baseline) {
      if (field) send({ type: 'changed', key, value: field.value })
      void processQueueRef.current()
      return
    }

    const startedMachine = send({ type: 'save-started', key })
    const started = startedMachine.fields[key]
    const inFlight = started?.inFlight
    if (!started || !inFlight) {
      void processQueueRef.current()
      return
    }

    processingRef.current = true
    try {
      const result = await onSaveRef.current({
        base_version: startedMachine.version,
        path: started.path,
        old_value_hash: await hash(inFlight.baseline),
        value: inFlight.snapshot,
      })
      if (!mountedRef.current) return
      const next = send({
        type: 'save-succeeded',
        key,
        snapshot: inFlight.snapshot,
        version: result.version,
      })
      const nextField = next.fields[key]
      if (nextField?.queued) {
        if (!queueRef.current.includes(key)) queueRef.current.push(key)
      } else {
        const previousTimer = savedTimersRef.current.get(key)
        if (previousTimer) clearTimeout(previousTimer)
        savedTimersRef.current.set(key, setTimeout(() => {
          send({ type: 'saved-expired', key })
        }, 1200))
      }
    } catch (error) {
      if (!mountedRef.current) return
      send({
        type: 'save-failed',
        key,
        conflict: error instanceof ReviewApiError && error.code === 'CONFLICT',
      })
    } finally {
      processingRef.current = false
      if (mountedRef.current) void processQueueRef.current()
    }
  }

  const setValue = useCallback((key: string, value: string) => {
    if (!enabledRef.current) return
    clearDebounce(key)
    const next = send({ type: 'changed', key, value })
    const field = next.fields[key]
    if (field && field.value !== field.baseline) {
      debounceTimersRef.current.set(key, setTimeout(() => enqueue(key), delay))
    }
  }, [clearDebounce, delay, enqueue, send])

  const flush = useCallback((key: string) => {
    const field = machineRef.current.fields[key]
    if (field && field.value !== field.baseline && field.status !== 'conflict') enqueue(key)
  }, [enqueue])

  const retry = useCallback((key: string) => {
    const field = machineRef.current.fields[key]
    if (!field || field.value === field.baseline) return
    send({ type: 'retry', key })
    enqueue(key)
  }, [enqueue, send])

  useEffect(() => {
    send({ type: 'definitions-synced', version, fields: definitions })
  }, [definitionSignature, send, version])

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
    () => Object.values(machine.fields).some((field) => (
      ['dirty', 'saving', 'failed', 'conflict'].includes(field.status)
    )),
    [machine.fields],
  )
  const hasConflict = useMemo(
    () => Object.values(machine.fields).some((field) => field.status === 'conflict'),
    [machine.fields],
  )

  return {
    fields: machine.fields as Record<string, AutosaveFieldState>,
    setValue,
    flush,
    retry,
    hasPending,
    hasConflict,
  }
}
