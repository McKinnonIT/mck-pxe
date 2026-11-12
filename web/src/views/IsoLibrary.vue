<script setup lang="ts">
import { Trash2, Upload } from 'lucide-vue-next'
import { ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, get, upload, usePoll } from '@/lib/api'
import { ago, bytes } from '@/lib/format'
import { showToast, toastError, uploadWithToast } from '@/lib/toast'
import type { BootIso } from '@/lib/types'

const isos = ref<BootIso[]>([])
usePoll(async () => (isos.value = await get('/isos')), 5000)

const showUpload = ref(false)
const file = ref<File | null>(null)
const name = ref('')

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
  if (file.value && !name.value) name.value = file.value.name.replace(/\.iso$/i, '')
}

function send() {
  if (!file.value) return
  const f = file.value
  const q = new URLSearchParams({ name: name.value, filename: f.name })
  showUpload.value = false
  file.value = null
  name.value = ''
  uploadWithToast<BootIso>(q.get('name') || f.name, (p) => upload(`/isos/upload?${q}`, f, p), (i) => `/isos/${i.id}`)
}

async function saveArgs(i: BootIso, extra_args: string) {
  if (extra_args === i.extra_args) return
  try {
    Object.assign(i, await api('PATCH', `/isos/${i.id}`, { extra_args }))
    showToast({ title: 'Saved', message: `Kernel arguments for ${i.name}`, variant: 'success' })
  } catch (e) {
    toastError("Couldn't save", e)
  }
}

async function remove(i: BootIso) {
  if (!confirm(`Delete ${i.name}? Its files are removed from the server.`)) return
  try {
    await api('DELETE', `/isos/${i.id}`)
    isos.value = isos.value.filter((x) => x.id !== i.id)
  } catch (e) {
    toastError("Couldn't delete", e)
  }
}
</script>

<template>
  <PageHeader
    title="ISO library"
    description="Linux installers, live systems and tools, booted over the network from the PXE menu's ISO library entry. Machines need Secure Boot off."
  >
    <Button @click="showUpload = !showUpload"><Upload /> Upload ISO</Button>
  </PageHeader>

  <Card v-if="showUpload" class="mb-6">
    <CardHeader>
      <CardTitle>Upload an ISO</CardTitle>
      <CardDescription>
        The ISO as you'd write it to a USB stick. Ubuntu, Mint, Pop!_OS, Fedora, Debian, Arch, Proxmox, GParted and
        other Debian-live systems are set up automatically. Windows ISOs go on the Images page instead.
      </CardDescription>
    </CardHeader>
    <CardContent class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2">
        <Label for="file">ISO file</Label>
        <Input id="file" type="file" accept=".iso" @change="pick" />
      </div>
      <div class="space-y-2">
        <Label for="iname">Name in the PXE menu</Label>
        <Input id="iname" v-model="name" />
      </div>
      <div class="sm:col-span-2">
        <Button :disabled="!file" @click="send">Upload</Button>
      </div>
    </CardContent>
  </Card>

  <Card>
    <CardContent>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Boots as</TableHead>
            <TableHead>Size</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Extra kernel arguments</TableHead>
            <TableHead>Added</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="i in isos" :key="i.id">
            <TableCell>
              <div class="font-medium">{{ i.name }}</div>
              <div class="text-muted-foreground text-xs">{{ i.filename }}</div>
            </TableCell>
            <TableCell>
              <Badge v-if="i.label" :variant="i.family === 'generic' ? 'outline' : 'secondary'">{{ i.label }}</Badge>
              <div v-if="i.needs_ram_for_iso" class="text-muted-foreground mt-1 text-xs">
                Loads the whole ISO into RAM: the machine needs more than twice the ISO's size in memory
              </div>
            </TableCell>
            <TableCell class="tabular-nums">{{ bytes(i.size_bytes) }}</TableCell>
            <TableCell>
              <StatusBadge :status="i.status" />
              <div v-if="i.error" class="text-destructive mt-1 max-w-64 text-xs">{{ i.error }}</div>
            </TableCell>
            <TableCell>
              <Input
                v-if="i.family && i.family !== 'generic'"
                :model-value="i.extra_args"
                placeholder="e.g. nomodeset"
                class="h-8 min-w-48 font-mono text-xs"
                :aria-label="`Extra kernel arguments for ${i.name}`"
                @change="saveArgs(i, ($event.target as HTMLInputElement).value.trim())"
              />
            </TableCell>
            <TableCell class="text-muted-foreground text-xs">{{ ago(i.created_at) }}<br />{{ i.created_by }}</TableCell>
            <TableCell>
              <Button variant="ghost" size="icon" :aria-label="`Delete ${i.name}`" @click="remove(i)"><Trash2 /></Button>
            </TableCell>
          </TableRow>
          <TableRow v-if="!isos.length">
            <TableCell :colspan="7" class="text-muted-foreground py-8 text-center">No ISOs yet</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardContent>
  </Card>
</template>
