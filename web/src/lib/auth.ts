import { ref } from 'vue'
import { api, ApiError } from '@/lib/api'

export interface Me {
  id: number
  username: string
  name: string
  role: 'admin' | 'technician'
}

/** The signed-in admin, or null. undefined until first checked. */
export const me = ref<Me | null | undefined>(undefined)

export async function loadMe(): Promise<Me | null> {
  try {
    me.value = await api<Me>('GET', '/me')
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e
    me.value = null
  }
  return me.value
}

export async function signIn(username: string, password: string) {
  me.value = await api<Me>('POST', '/auth/login', { username, password })
}

export async function signOut() {
  await api('POST', '/auth/logout').catch(() => {})
  me.value = null
}
