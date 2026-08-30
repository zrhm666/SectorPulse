import { describe, expect, it } from 'vitest'
import {
  createAutosaveMachine,
  reduceAutosave,
  type AutosaveFieldDefinition,
} from './draftAutosaveMachine'

const definitions: AutosaveFieldDefinition[] = [
  { key: 'introduction', path: 'introduction', value: '旧导语' },
]

describe('draft autosave machine', () => {
  it('uses the synchronously changed value when a save starts in the same turn', () => {
    const changed = reduceAutosave(
      createAutosaveMachine(1, definitions),
      { type: 'changed', key: 'introduction', value: '最新值' },
    )

    const saving = reduceAutosave(changed, { type: 'save-started', key: 'introduction' })

    expect(saving.fields.introduction.inFlight?.snapshot).toBe('最新值')
    expect(saving.fields.introduction.status).toBe('saving')
  })

  it('keeps newer text queued and rebases it on the returned server version', () => {
    const initial = createAutosaveMachine(1, definitions)
    const dirty = reduceAutosave(initial, {
      type: 'changed', key: 'introduction', value: '第一版',
    })
    const saving = reduceAutosave(dirty, { type: 'save-started', key: 'introduction' })
    const queued = reduceAutosave(saving, {
      type: 'changed', key: 'introduction', value: '第二版',
    })

    const succeeded = reduceAutosave(queued, {
      type: 'save-succeeded',
      key: 'introduction',
      snapshot: '第一版',
      version: 2,
    })

    expect(succeeded.version).toBe(2)
    expect(succeeded.fields.introduction).toMatchObject({
      value: '第二版',
      baseline: '第一版',
      status: 'dirty',
      queued: true,
    })
  })

  it('retains local text when a save fails', () => {
    const dirty = reduceAutosave(
      createAutosaveMachine(1, definitions),
      { type: 'changed', key: 'introduction', value: '不能丢失' },
    )
    const saving = reduceAutosave(dirty, { type: 'save-started', key: 'introduction' })
    const failed = reduceAutosave(saving, {
      type: 'save-failed', key: 'introduction', conflict: true,
    })

    expect(failed.fields.introduction).toMatchObject({
      value: '不能丢失', status: 'conflict', queued: false,
    })
  })
})
