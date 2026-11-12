import { reactive } from 'vue'
import { get } from './api'

/**
 * One toast at a time, bottom right (the shelf-plus pattern). A new toast replaces the last.
 * - `persist` toasts track a job and stay up until replaced: the strip along the bottom
 *   fills to `progress` (0–100), or shimmers full width while progress is unknown.
 * - Other toasts close after `duration` ms; the strip drains over that time.
 */
export interface Toast {
  open: boolean
  id: number
  title: string
  message?: string
  variant: 'neutral' | 'success' | 'error'
  persist?: boolean
  progress?: number
  duration?: number
}

export const toast = reactive<Toast>({ open: false, id: 0, title: '', variant: 'neutral' })

export function showToast(t: Omit<Toast, 'open' | 'id'>) {
  Object.assign(toast, { message: undefined, persist: false, progress: undefined, duration: undefined }, t, {
    open: true,
    id: toast.id + 1,
  })
}

/** Move the bar of the job toast on screen without restarting it. Ignored once it's replaced. */
export function setToastProgress(id: number, progress?: number, message?: string) {
  if (toast.open && toast.id === id) Object.assign(toast, { progress }, message !== undefined ? { message } : {})
}

export function closeToast() {
  toast.open = false
}

export const toastError = (title: string, e: any) =>
  showToast({ title, message: e?.message ?? String(e), variant: 'error', duration: 8000 })

/** Stream an upload, then follow the server's processing of it, all in one toast. */
export async function uploadWithToast<T extends { id: number }>(
  name: string,
  send: (onProgress: (pct: number) => void) => Promise<T>,
  statusPath: (item: T) => string,
): Promise<T | null> {
  showToast({ title: `Uploading ${name}`, message: '0%', variant: 'neutral', persist: true, progress: 0 })
  const id = toast.id
  let item: T
  try {
    item = await send((pct) => setToastProgress(id, pct, `${pct.toFixed(0)}%`))
  } catch (e) {
    toastError(`Upload of ${name} failed`, e)
    return null
  }
  setToastProgress(id, undefined, 'Uploaded. Processing on the server…')
  if (toast.id === id) toast.title = `Processing ${name}`
  // ponytail: polls every 3 s for as long as the tab is open; server push if this ever matters
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000))
    let cur: { status: string; error?: string }
    try {
      cur = await get(statusPath(item))
    } catch {
      continue
    }
    if (cur.status === 'ready') {
      showToast({ title: `${name} is ready`, variant: 'success', duration: 5000 })
      return item
    }
    if (cur.status === 'error') {
      toastError(`${name} failed to process`, { message: cur.error || 'Unknown error' })
      return item
    }
  }
}
