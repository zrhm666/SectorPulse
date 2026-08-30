export type AutosaveStatus = 'clean' | 'dirty' | 'saving' | 'saved' | 'failed' | 'conflict'

export type AutosaveFieldDefinition = {
  key: string
  path: string
  value: string
}

export type AutosaveFieldState = {
  value: string
  baseline: string
  path: string
  status: AutosaveStatus
  queued: boolean
  inFlight?: {
    snapshot: string
    baseline: string
  }
}

export type AutosaveMachineState = {
  version: number
  fields: Record<string, AutosaveFieldState>
}

export type AutosaveEvent =
  | { type: 'changed'; key: string; value: string }
  | { type: 'save-started'; key: string }
  | { type: 'save-succeeded'; key: string; snapshot: string; version: number }
  | { type: 'save-failed'; key: string; conflict: boolean }
  | { type: 'retry'; key: string }
  | { type: 'saved-expired'; key: string }
  | { type: 'definitions-synced'; version: number; fields: AutosaveFieldDefinition[] }

export function createAutosaveMachine(
  version: number,
  definitions: AutosaveFieldDefinition[],
): AutosaveMachineState {
  return {
    version,
    fields: Object.fromEntries(definitions.map((field) => [field.key, {
      value: field.value,
      baseline: field.value,
      path: field.path,
      status: 'clean' as const,
      queued: false,
    }])),
  }
}

function updateField(
  state: AutosaveMachineState,
  key: string,
  update: (field: AutosaveFieldState) => AutosaveFieldState,
): AutosaveMachineState {
  const field = state.fields[key]
  if (!field) return state
  return { ...state, fields: { ...state.fields, [key]: update(field) } }
}

export function reduceAutosave(
  state: AutosaveMachineState,
  event: AutosaveEvent,
): AutosaveMachineState {
  switch (event.type) {
    case 'changed':
      return updateField(state, event.key, (field) => ({
        ...field,
        value: event.value,
        status: field.inFlight
          ? 'saving'
          : event.value === field.baseline ? 'clean' : 'dirty',
        queued: Boolean(field.inFlight && event.value !== field.inFlight.snapshot),
      }))
    case 'save-started':
      return updateField(state, event.key, (field) => {
        if (field.value === field.baseline || field.inFlight) return field
        return {
          ...field,
          status: 'saving',
          queued: false,
          inFlight: { snapshot: field.value, baseline: field.baseline },
        }
      })
    case 'save-succeeded':
      return updateField(
        { ...state, version: Math.max(state.version, event.version) },
        event.key,
        (field) => {
          if (field.inFlight?.snapshot !== event.snapshot) return field
          const hasNewerValue = field.value !== event.snapshot
          return {
            ...field,
            baseline: event.snapshot,
            status: hasNewerValue ? 'dirty' : 'saved',
            queued: hasNewerValue,
            inFlight: undefined,
          }
        },
      )
    case 'save-failed':
      return updateField(state, event.key, (field) => ({
        ...field,
        status: event.conflict ? 'conflict' : 'failed',
        queued: false,
        inFlight: undefined,
      }))
    case 'retry':
      return updateField(state, event.key, (field) => ({
        ...field,
        status: field.value === field.baseline ? 'clean' : 'dirty',
        queued: false,
      }))
    case 'saved-expired':
      return updateField(state, event.key, (field) => (
        field.status === 'saved' ? { ...field, status: 'clean' } : field
      ))
    case 'definitions-synced': {
      const nextFields = Object.fromEntries(event.fields.map((definition) => {
        const previous = state.fields[definition.key]
        const preserveLocal = previous
          && ['dirty', 'saving', 'failed', 'conflict'].includes(previous.status)
        return [definition.key, preserveLocal ? {
          ...previous,
          path: definition.path,
        } : {
          value: definition.value,
          baseline: definition.value,
          path: definition.path,
          status: 'clean' as const,
          queued: false,
        }]
      }))
      return {
        version: Math.max(state.version, event.version),
        fields: nextFields,
      }
    }
    default:
      return state
  }
}
