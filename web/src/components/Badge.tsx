import StatusBadge, { type StatusTone } from './ui/StatusBadge'

type BadgeTone = 'gray' | 'blue' | 'green' | 'red' | 'orange'

const TONE_MAP: Record<BadgeTone, StatusTone> = {
  gray: 'neutral',
  blue: 'info',
  green: 'success',
  red: 'danger',
  orange: 'warning',
}

export default function Badge({
  text,
  tone = 'gray',
}: {
  text: string
  tone?: BadgeTone
}) {
  return <StatusBadge status={text} tone={TONE_MAP[tone]} />
}
