<script setup lang="ts">
import { ArrowLeft, Trash2 } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskTable from '@/components/TaskTable.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import { api, get, usePoll } from '@/lib/api'
import { showToast } from '@/lib/toast'
import { ago, bytes } from '@/lib/format'
import { storageLabel, storageMismatch } from '@/lib/storage'
import type { Host, Image } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string
const host = ref<Host | null>(null)
const images = ref<Image[]>([])
const drivers = ref<{ pack: { id: number; name: string }; reason: string; drivers: any[] }[]>([])
const edit = ref({ name: '', notes: '' })

async function load() {
  const first = !host.value
  host.value = await get(`/hosts/${id}`)
  if (first) {
    edit.value = { name: host.value!.name, notes: host.value!.notes }
    form.value.disk = host.value!.disks.find((d) => !d.removable)?.path ?? host.value!.disks[0]?.path ?? ''
  }
}
usePoll(load, 4000)
get('/images').then((all: Image[]) => (images.value = all.filter((i) => i.status === 'ready')))
get(`/hosts/${id}/drivers`).then((d) => (drivers.value = d))

const busy = computed(() => host.value?.tasks?.some((t) => ['queued', 'running'].includes(t.status)))

// ------------------------------------------------------------------ new task form
const action = ref<'deploy' | 'capture'>('deploy')
const form = ref({
  image_id: null as number | null,
  wim_index: null as number | null,
  disk: '',
  drivers: 'auto',
  after: 'reboot',
  name: '',
  kind: 'block',
  allow_storage_mismatch: false,
})
const error = ref('')
const selected = computed(() => images.value.find((i) => i.id === form.value.image_id))
watch(selected, (img) => (form.value.wim_index = img?.meta.indexes?.[0]?.index ?? null))
const mismatch = computed(() =>
  action.value === 'deploy'
    ? storageMismatch(selected.value, host.value?.disks.find((d) => d.path === form.value.disk))
    : null,
)
watch(mismatch, () => (form.value.allow_storage_mismatch = false))
// BitLocker recovery keys are only entered at the machine, so a capture of a locked disk can't be queued here
const captureLocked = computed(
  () => action.value === 'capture' && !!host.value?.disks.find((d) => d.path === form.value.disk)?.bitlocker,
)
watch(action, (a) => (form.value.after = a === 'deploy' ? 'reboot' : 'wait'))

async function submit() {
  error.value = ''
  if (action.value === 'deploy') {
    const disk = host.value?.disks.find((d) => d.path === form.value.disk)
    if (!confirm(`Erase ${form.value.disk} (${bytes(disk?.size)}) on ${host.value?.name} and deploy ${selected.value?.name}?`))
      return
  }
  try {
    await api('POST', '/tasks', { host_id: host.value!.id, type: action.value, ...form.value })
    await load()
  } catch (e: any) {
    error.value = e.message
  }
}

async function save() {
  await api('PATCH', `/hosts/${id}`, edit.value)
  showToast({ title: 'Saved', variant: 'success' })
  await load()
}

async function remove() {
  if (!confirm(`Forget ${host.value?.name}? It will re-register next time it PXE boots.`)) return
  try {
    await api('DELETE', `/hosts/${id}`)
    router.push('/machines')
  } catch (e: any) {
    error.value = e.message
  }
}
</script>

<template>
  <template v-if="host">
    <PageHeader :title="host.name" :description="`${host.manufacturer} ${host.model}`">
      <template #back>
        <RouterLink to="/machines" class="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm">
          <ArrowLeft class="size-4" /> Machines
        </RouterLink>
      </template>
      <StatusBadge :status="host.online ? 'online' : 'offline'" />
      <Button variant="outline" size="sm" @click="remove"><Trash2 /> Forget</Button>
    </PageHeader>

    <div class="grid gap-6 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle>New task</CardTitle>
          <CardDescription>
            The machine picks this up straight away if it's sitting in mck-pxe, or the next time it PXE boots.
          </CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="bg-muted inline-flex rounded-md p-1">
            <button
              v-for="a in ['deploy', 'capture'] as const"
              :key="a"
              class="rounded px-4 py-1.5 text-sm capitalize"
              :class="action === a ? 'bg-background shadow-sm' : 'text-muted-foreground'"
              @click="action = a"
            >
              {{ a }}
            </button>
          </div>

          <div class="grid gap-4 sm:grid-cols-2">
            <template v-if="action === 'deploy'">
              <div class="space-y-2 sm:col-span-2">
                <Label for="image">Image</Label>
                <NativeSelect id="image" v-model="form.image_id">
                  <option :value="null" disabled>Choose an image…</option>
                  <option v-for="i in images" :key="i.id" :value="i.id">
                    {{ i.name }} ({{ i.kind === 'wim' ? 'WIM' : 'block' }}, {{ bytes(i.size_bytes) }})
                  </option>
                </NativeSelect>
              </div>
              <div v-if="selected?.kind === 'wim'" class="space-y-2">
                <Label for="index">Windows edition</Label>
                <NativeSelect id="index" v-model="form.wim_index">
                  <option v-for="ix in selected.meta.indexes" :key="ix.index" :value="ix.index">
                    {{ ix.index }}: {{ ix.name }}
                  </option>
                </NativeSelect>
              </div>
              <div v-if="selected?.os_family === 'windows'" class="space-y-2">
                <Label for="drivers">Driver injection</Label>
                <NativeSelect id="drivers" v-model="form.drivers">
                  <option value="auto">Automatic (matching drivers)</option>
                  <option value="none">None</option>
                </NativeSelect>
              </div>
            </template>
            <template v-else>
              <div class="space-y-2">
                <Label for="name">New image name</Label>
                <Input id="name" v-model="form.name" :placeholder="`${host.model} golden`" />
              </div>
              <div class="space-y-2">
                <Label for="kind">Capture type</Label>
                <NativeSelect id="kind" v-model="form.kind">
                  <option value="block">Whole disk, block level (fastest)</option>
                  <option value="wim">Windows WIM (hardware independent)</option>
                </NativeSelect>
              </div>
            </template>
            <div class="space-y-2">
              <Label for="disk">Disk</Label>
              <NativeSelect id="disk" v-model="form.disk">
                <option v-for="d in host.disks" :key="d.path" :value="d.path">
                  {{ d.path }} · {{ bytes(d.size) }} {{ d.model }}{{ d.storage ? ` · ${storageLabel(d)}` : '' }}{{ d.bitlocker ? ' · BitLocker' : '' }}
                </option>
              </NativeSelect>
            </div>
            <div class="space-y-2">
              <Label for="after">When finished</Label>
              <NativeSelect id="after" v-model="form.after">
                <option value="reboot">Reboot</option>
                <option value="poweroff">Power off</option>
                <option value="wait">Stay in mck-pxe</option>
              </NativeSelect>
            </div>
          </div>
          <div v-if="action === 'capture'" class="border-warning/50 bg-warning/10 space-y-1 rounded-md border p-3 text-sm">
            <p class="font-medium">Before capturing a Windows machine</p>
            <ul class="list-disc space-y-0.5 pl-5">
              <li>
                <b>Turn BitLocker off</b> and wait for the drive to finish decrypting (Settings → Privacy &amp; security →
                Device encryption, or <code>manage-bde -off C:</code>), or capture from the machine's own screen and enter
                the recovery key there. Suspending BitLocker isn't enough.
              </li>
              <li>Shut down fully, with Fast Startup and hibernation off.</li>
              <li v-if="form.kind === 'wim'">Sysprep the machine first.</li>
            </ul>
          </div>
          <div v-if="captureLocked" class="border-destructive/40 bg-destructive/10 space-y-1 rounded-md border p-3 text-sm">
            <p class="text-destructive font-medium">BitLocker is on for {{ form.disk }}</p>
            <p>
              This capture would fail here. Either turn BitLocker off in Windows first, or start the capture from the
              machine's own screen in mck-pxe and enter the drive's recovery key there. The key never leaves the machine,
              so it can't be entered from this page.
            </p>
          </div>
          <div v-if="mismatch" class="border-destructive/40 bg-destructive/10 space-y-2 rounded-md border p-3 text-sm">
            <p class="text-destructive font-medium">Storage mode mismatch</p>
            <p>{{ mismatch }}</p>
            <Label class="font-normal">
              <input v-model="form.allow_storage_mismatch" type="checkbox" class="size-4" /> Deploy anyway
            </Label>
          </div>
          <ErrorText :error="error" />
          <Button :disabled="busy || !host.disks.length || (!!mismatch && !form.allow_storage_mismatch) || captureLocked" @click="submit">
            {{ busy ? 'A task is already queued' : action === 'deploy' ? 'Queue deployment' : 'Queue capture' }}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Hardware</CardTitle></CardHeader>
        <CardContent class="space-y-3 text-sm">
          <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
            <dt class="text-muted-foreground">Serial</dt><dd>{{ host.serial || '—' }}</dd>
            <dt class="text-muted-foreground">SKU</dt><dd>{{ host.sku || '—' }}</dd>
            <dt class="text-muted-foreground">CPU</dt><dd>{{ host.cpu }}</dd>
            <dt class="text-muted-foreground">RAM</dt><dd>{{ (host.ram_mb / 1024).toFixed(1) }} GB</dd>
            <dt class="text-muted-foreground">MAC</dt><dd class="font-mono">{{ host.mac }}</dd>
            <dt class="text-muted-foreground">IP</dt><dd class="font-mono">{{ host.ip }}</dd>
            <dt class="text-muted-foreground">Boot</dt>
            <dd>{{ host.boot_mode.toUpperCase() }}, Secure Boot {{ host.secure_boot ? 'on' : 'off' }}</dd>
            <dt class="text-muted-foreground">Devices</dt><dd>{{ host.hardware_id_count }} hardware IDs</dd>
            <dt class="text-muted-foreground">Last seen</dt><dd>{{ ago(host.last_seen) }}</dd>
          </dl>
          <div class="space-y-1">
            <div v-for="d in host.disks" :key="d.path" class="bg-muted rounded-md px-3 py-2">
              <div class="font-mono text-xs">{{ d.path }}</div>
              <div>{{ bytes(d.size) }} {{ d.model }}</div>
              <div class="mt-1 flex flex-wrap gap-1">
                <Badge v-if="d.bitlocker" variant="warning">BitLocker</Badge>
                <Badge v-if="d.storage" :variant="d.boot_driver?.startsWith('iaStor') ? 'warning' : 'outline'">{{ storageLabel(d) }}</Badge>
                <Badge v-if="d.transport" variant="outline">{{ d.transport }}</Badge>
              </div>
              <div v-if="d.members?.length" class="text-muted-foreground mt-1 text-xs">Members: {{ d.members.join(', ') }}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle>Drivers this machine would get</CardTitle>
          <CardDescription>Used when deploying a Windows image with automatic driver injection.</CardDescription>
        </CardHeader>
        <CardContent>
          <div v-if="!drivers.length" class="text-muted-foreground text-sm">
            No matching drivers. Upload a driver pack for the {{ host.model }} on the
            <RouterLink to="/drivers" class="underline">Drivers</RouterLink> page.
          </div>
          <div v-for="p in drivers" :key="p.pack.id" class="mb-4">
            <div class="mb-1 flex items-center gap-2">
              <RouterLink :to="`/drivers/${p.pack.id}`" class="font-medium hover:underline">{{ p.pack.name }}</RouterLink>
              <Badge variant="secondary">{{ p.reason }}</Badge>
              <span class="text-muted-foreground text-xs">{{ p.drivers.length }} drivers</span>
            </div>
            <div class="flex flex-wrap gap-1">
              <Badge v-for="d in p.drivers.slice(0, 30)" :key="d.inf_path" variant="outline" :title="d.inf_path">
                {{ d.class_name || '?' }} · {{ d.provider }}
              </Badge>
              <span v-if="p.drivers.length > 30" class="text-muted-foreground text-xs">+{{ p.drivers.length - 30 }} more</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Details</CardTitle></CardHeader>
        <CardContent class="space-y-3">
          <div class="space-y-2">
            <Label for="hname">Name</Label>
            <Input id="hname" v-model="edit.name" />
          </div>
          <div class="space-y-2">
            <Label for="notes">Notes</Label>
            <Textarea id="notes" v-model="edit.notes" />
          </div>
          <Button variant="secondary" @click="save">Save</Button>
        </CardContent>
      </Card>

      <Card class="lg:col-span-3">
        <CardHeader><CardTitle>Task history</CardTitle></CardHeader>
        <CardContent><TaskTable :tasks="host.tasks ?? []" hide-host /></CardContent>
      </Card>
    </div>
  </template>
</template>
