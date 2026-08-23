import { useLayoutEffect, useRef } from 'react'

export default function ConfirmDialog(props: { open: boolean; title: string; description: string; confirmLabel: string; tone?: 'default' | 'danger'; onConfirm: () => void; onCancel: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const previousFocus = useRef<HTMLElement | null>(null)

  useLayoutEffect(() => {
    if (props.open) {
      previousFocus.current = document.activeElement as HTMLElement
      cancelRef.current?.focus()
    } else {
      previousFocus.current?.focus()
    }
  }, [props.open])

  if (!props.open) return null
  return <dialog className="confirm-dialog" open aria-labelledby="confirm-title" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); props.onCancel() } }}>
    <h2 id="confirm-title">{props.title}</h2>
    <p>{props.description}</p>
    <div className="confirm-dialog__actions"><button ref={cancelRef} className="button button-secondary" type="button" onClick={props.onCancel}>取消</button><button className={`button ${props.tone === 'danger' ? 'button-danger' : 'button-primary'}`} type="button" onClick={props.onConfirm}>{props.confirmLabel}</button></div>
  </dialog>
}
