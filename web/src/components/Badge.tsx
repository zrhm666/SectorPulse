// web/src/components/Badge.tsx
export default function Badge({
  text,
  tone = 'gray',
}: {
  text: string
  tone?: 'gray' | 'blue' | 'green' | 'red' | 'orange'
}) {
  const colors: Record<string, string> = {
    gray: '#6b7280',
    blue: '#1a73e8',
    green: '#0f9d58',
    red: '#d93025',
    orange: '#f9a825',
  }
  return (
    <span
      className="badge"
      style={{
        background: colors[tone] + '22',
        color: colors[tone],
        border: `1px solid ${colors[tone]}55`,
      }}
    >
      {text}
    </span>
  )
}