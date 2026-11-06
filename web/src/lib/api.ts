import { onMounted, onUnmounted } from 'vue'

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message)
  }
}

/** Called when a request comes back 401 (signed out, or the session expired). */
let onSignedOut: () => void = () => {}
export function setSignedOutHandler(fn: () => void) {
  onSignedOut = fn
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/') && path !== '/me') onSignedOut()
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const get = <T = any>(path: string) => api<T>('GET', path)

/** Stream a (possibly multi-GB) file as the raw request body, with progress. */
export function upload<T = any>(path: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `/api${path}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((e.loaded / e.total) * 100)
    xhr.onload = () => {
      let data: any = null
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else {
        if (xhr.status === 401) onSignedOut()
        reject(new ApiError(data?.detail ?? `Upload failed (${xhr.status})`, xhr.status))
      }
    }
    xhr.onerror = () => reject(new ApiError('Upload failed (network error)'))
    xhr.send(file)
  })
}

/** Run fn now and every `ms` while the component is mounted and the tab is visible. */
export function usePoll(fn: () => unknown, ms = 3000) {
  let timer: number | undefined
  const tick = () => {
    if (!document.hidden) fn()
  }
  onMounted(() => {
    fn()
    timer = window.setInterval(tick, ms)
  })
  onUnmounted(() => window.clearInterval(timer))
}
