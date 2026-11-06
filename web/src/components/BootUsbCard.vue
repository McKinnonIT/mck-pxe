<script setup lang="ts">
import { CircleAlert, Download, LoaderCircle, Usb } from 'lucide-vue-next'
import { onMounted, onUnmounted, ref } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, get } from '@/lib/api'
import { bytes, dateTime } from '@/lib/format'

interface IsoStatus {
  available: boolean
  missing: string[]
  building: boolean
  error: string
  server: string
  built: { server: string; size_bytes: number; built_at: string } | null
  stale: boolean
}

const iso = ref<IsoStatus | null>(null)
const error = ref('')
let timer: number | undefined

async function load() {
  iso.value = await get('/iso')
  window.clearInterval(timer)
  if (iso.value?.building) timer = window.setInterval(load, 2000)
}

async function build() {
  error.value = ''
  try {
    iso.value = await api('POST', '/iso/build')
    timer = window.setInterval(load, 2000)
  } catch (e: any) {
    error.value = e.message
  }
}

// The stick's offline account: signs in at machines when the server can't be reached
const account = ref<{ username: string; updated_at: string } | null>(null)
const accountForm = ref({ username: '', password: '' })
const accountError = ref('')
const editingAccount = ref(false)
const loadAccount = async () => (account.value = await get('/settings/usb-account'))

async function saveAccount() {
  accountError.value = ''
  try {
    account.value = await api('PUT', '/settings/usb-account', accountForm.value)
    accountForm.value = { username: '', password: '' }
    editingAccount.value = false
    await load()
  } catch (e: any) {
    accountError.value = e.message
  }
}

async function removeAccount() {
  if (!confirm('Remove the offline account? Sticks you build after this need the server to sign in.')) return
  await api('DELETE', '/settings/usb-account')
  account.value = null
  await load()
}

onMounted(() => {
  load()
  loadAccount()
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-2"><Usb class="size-5" /> Boot USB</CardTitle>
      <CardDescription>
        Boots the imaging environment from a USB stick instead of the network. The machine only needs ordinary DHCP and to
        reach {{ iso?.server ?? 'this server' }}, so it's a good way to test connectivity, captures and deployments before
        PXE is set up. Works on BIOS and UEFI machines, with Secure Boot on.
      </CardDescription>
    </CardHeader>
    <CardContent v-if="iso" class="space-y-4 text-sm">
      <div v-if="iso.built" class="bg-muted rounded-md px-3 py-2">
        <div class="font-medium">mck-pxe-boot.iso · {{ bytes(iso.built.size_bytes) }}</div>
        <div class="text-muted-foreground text-xs">
          Built {{ dateTime(iso.built.built_at) }} · connects to {{ iso.built.server }}
        </div>
      </div>
      <p v-if="iso.stale" class="flex items-start gap-2">
        <CircleAlert class="text-warning mt-0.5 size-4 shrink-0" />
        Out of date: the imaging environment, server address or offline account has changed since this was built. Build it again.
      </p>
      <div v-if="!iso.available" class="text-muted-foreground">
        Can't build yet. Missing:
        <ul class="mt-1 list-disc pl-5">
          <li v-for="m in iso.missing" :key="m" class="font-mono text-xs">{{ m }}</li>
        </ul>
      </div>
      <ErrorText :error="error || iso.error" />
      <div class="flex flex-wrap gap-2">
        <Button :disabled="!iso.available || iso.building" @click="build">
          <LoaderCircle v-if="iso.building" class="animate-spin" />
          {{ iso.building ? 'Building…' : iso.built ? 'Rebuild' : 'Build ISO' }}
        </Button>
        <Button v-if="iso.built && !iso.building" as="a" href="/api/iso/download" download variant="outline">
          <Download /> Download
        </Button>
      </div>
      <div class="space-y-3 rounded-md border p-4">
        <div>
          <div class="font-medium">Offline account</div>
          <p class="text-muted-foreground text-xs">
            Everyone signs in at the machine with their own account, which the server checks. This extra account is built into
            the stick for when the server can't be reached. It can capture and deploy using images on the stick, but can't
            start anything on the server. Only its password hash goes on the stick. Rebuild the ISO after changing it.
          </p>
        </div>
        <div v-if="account && !editingAccount" class="flex flex-wrap items-center gap-2">
          <span>Username <span class="font-mono">{{ account.username }}</span>, set {{ dateTime(account.updated_at) }}</span>
          <Button size="sm" variant="outline" @click="editingAccount = true">Change</Button>
          <Button size="sm" variant="outline" @click="removeAccount">Remove</Button>
        </div>
        <form v-else class="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" @submit.prevent="saveAccount">
          <div class="space-y-1.5">
            <Label for="usb-user">Username</Label>
            <Input id="usb-user" v-model="accountForm.username" autocapitalize="none" placeholder="usb" />
          </div>
          <div class="space-y-1.5">
            <Label for="usb-pass">Password</Label>
            <Input id="usb-pass" v-model="accountForm.password" type="password" autocomplete="new-password" />
          </div>
          <div class="flex gap-2">
            <Button type="submit" :disabled="!accountForm.username || !accountForm.password">Save</Button>
            <Button v-if="account" type="button" variant="outline" @click="editingAccount = false">Cancel</Button>
          </div>
        </form>
        <p v-if="!account && !editingAccount" class="text-muted-foreground text-xs">
          None set: sticks need the server to sign in.
        </p>
        <ErrorText :error="accountError" />
      </div>
      <p class="text-muted-foreground text-xs">
        Write it to a USB stick with balenaEtcher, Rufus (DD image mode) or <code>dd</code>, then boot from the stick.
        The stick is hidden from the disk list, so a deployment can't wipe it.
      </p>
      <p class="text-muted-foreground text-xs">
        <span class="text-foreground font-medium">Images on the stick:</span> sign in at the machine to
        capture to or deploy from the stick, with no server needed. When the server is reachable, the console can also
        copy a server image to the stick, including drivers for that machine's model, or upload a stick image to the
        library. Use a stick of 32 GB or more; the first save adds a storage partition to its free space.
      </p>
    </CardContent>
  </Card>
</template>
