export type LoadingStateProps = {
  label?: string
}

export default function LoadingState({ label = '加载中…' }: LoadingStateProps) {
  return (
    <div className="loading-state" role="status">
      <span className="loading-state__indicator" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}
