<script setup lang="ts">
import { Upload } from 'lucide-vue-next'
import { ref } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { get, upload, usePoll } from '@/lib/api'
import { bytes } from '@/lib/format'
import type { DriverPack } from '@/lib/types'

interface ModelSeen {
  manufacturer: string
  model: string
  hosts: number
  packs: { id: number; name: string }[]
}

const packs = ref<DriverPack[]>([])
const models = ref<ModelSeen[]>([])
usePoll(async () => {
  ;[packs.value, models.value] = await Promise.all([get('/driver-packs'), get('/models')])
}, 5000)

const showUpload = ref(false)
const file = ref<File | null>(null)
const form = ref({ name: '', manufacturer: '', model_match: '' })
const pct = ref<number | null>(null)
const error = ref('')

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
  if (file.value && !form.value.name) form.value.name = file.value.name.replace(/\.[^.]+$/, '')
}

function forModel(m: ModelSeen) {
  showUpload.value = true
  form.value = { name: `${m.model} drivers`, manufacturer: m.manufacturer, model_match: m.model }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function send() {
  if (!file.value) return
  error.value = ''
  pct.value = 0
  const q = new URLSearchParams({ ...form.value, filename: file.value.name })
  try {
    await upload(`/driver-packs/upload?${q}`, file.value, (p) => (pct.value = p))
    showUpload.value = false
    file.value = null
    form.value = { name: '', manufacturer: '', model_match: '' }
    packs.value = await get('/driver-packs')
  } catch (e: any) {
    error.value = e.message
  } finally {
    pct.value = null
  }
}
</script>

<template>
  <PageHeader
    title="Drivers"
    description="Drivers are injected into Windows automatically when an image is deployed."
  >
    <Button @click="showUpload = !showUpload"><Upload /> Upload driver pack</Button>
  </PageHeader>

  <Card class="mb-6">
    <details :open="!packs.length" class="group">
      <summary class="flex cursor-pointer list-none items-center justify-between px-6 py-4 font-semibold">
        How to add drivers
        <span class="text-muted-foreground text-sm font-normal group-open:hidden">Show</span>
        <span class="text-muted-foreground hidden text-sm font-normal group-open:inline">Hide</span>
      </summary>
      <CardContent class="space-y-4 text-sm">
        <p class="text-muted-foreground">
          Drivers are added to Windows images when they are deployed: both WIM images and disk images.
          They aren't used for Linux or other images.
        </p>
        <ol class="list-decimal space-y-3 pl-5">
          <li>
            <span class="font-medium">PXE boot one of the machines.</span>
            Its model appears under <em>Models seen</em> exactly as Windows reports it.
            Click <em>Add pack</em> next to it to fill in the upload form for you.
          </li>
          <li>
            <span class="font-medium">Get the drivers for that model (Windows 11, 64-bit).</span>
            <ul class="text-muted-foreground mt-1 list-disc space-y-1 pl-5">
              <li><span class="text-foreground">Dell:</span> the model's driver pack (.cab) from Dell's “Driver Packs for Enterprise Client OS Deployment” page.</li>
              <li><span class="text-foreground">HP:</span> the model's driver pack (.exe) from HP's “Client Management Solutions – Driver Packs” list.</li>
              <li><span class="text-foreground">Lenovo:</span> the model's “SCCM driver pack” (.exe) from Lenovo's support site.</li>
              <li>
                <span class="text-foreground">Acer and others without a driver pack:</span> on a working machine of that model
                with all its drivers installed, open PowerShell as administrator and run
                <code class="bg-muted rounded px-1 py-0.5 font-mono text-xs">pnputil /export-driver * C:\Drivers</code>.
                Zip the <code class="bg-muted rounded px-1 py-0.5 font-mono text-xs">C:\Drivers</code> folder and upload the zip.
              </li>
            </ul>
            <p class="text-muted-foreground mt-1">
              Any zip of folders containing .inf files works. Setup programs that only install drivers when run
              (most single-driver downloads) don't contain .inf files; use one of the options above instead.
            </p>
          </li>
          <li>
            <span class="font-medium">Upload it.</span>
            For a pack built for particular models, set <em>Model match</em> to the model name shown under
            <em>Models seen</em>. Part of the name is enough, and you can list several separated by commas.
            Every driver in the pack goes to those models.
            Leave <em>Model match</em> empty for a general library (for example, a set of network or Wi-Fi drivers):
            each machine then only gets the drivers that fit its hardware.
          </li>
          <li>
            <span class="font-medium">Check it.</span>
            Wait for the pack's status to show <em>Ready</em> with a driver count.
            Then open one of the machines on the <RouterLink to="/machines" class="underline">Machines</RouterLink> page:
            <em>Drivers this machine would get</em> lists what it will receive.
          </li>
          <li>
            <span class="font-medium">Deploy.</span>
            Leave <em>Driver injection</em> on <em>Automatic</em> when you queue the deploy.
            The drivers install the first time Windows starts.
          </li>
        </ol>
        <div class="text-muted-foreground border-l-2 pl-3">
          <p>
            <span class="text-foreground font-medium">Disk controller drivers can't be added this way.</span>
            Windows needs its disk driver before it can start, so the image must already have it.
            mck-pxe warns you when a machine's disk mode (for example Intel RST or VMD) doesn't match the image.
          </p>
          <p class="mt-2">
            <span class="text-foreground font-medium">Disk images:</span>
            for images going to other models, run Sysprep on the source machine before capturing it.
            Without Sysprep, Windows still installs drivers for hardware it hasn't seen before, but may miss some.
          </p>
        </div>
      </CardContent>
    </details>
  </Card>

  <Card v-if="showUpload" class="mb-6">
    <CardHeader>
      <CardTitle>Upload a driver pack</CardTitle>
      <CardDescription>
        A vendor pack (Dell, HP or Lenovo .cab, .exe or .zip) or any zip of driver folders containing .inf files.
        Fill in “Model match” for a pack built for specific models: every driver in it goes to those machines.
        Leave it empty for a general library: each machine only gets the drivers that match its hardware.
      </CardDescription>
    </CardHeader>
    <CardContent class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2 sm:col-span-2">
        <Label for="file">File</Label>
        <Input id="file" type="file" @change="pick" />
      </div>
      <div class="space-y-2">
        <Label for="pname">Name</Label>
        <Input id="pname" v-model="form.name" />
      </div>
      <div class="space-y-2">
        <Label for="mfr">Manufacturer (optional)</Label>
        <Input id="mfr" v-model="form.manufacturer" placeholder="LENOVO" />
      </div>
      <div class="space-y-2 sm:col-span-2">
        <Label for="match">Model match (optional, comma separated)</Label>
        <Input id="match" v-model="form.model_match" placeholder="21K5, ThinkPad E14 Gen 6" />
      </div>
      <div class="space-y-2 sm:col-span-2">
        <Progress v-if="pct !== null" :model-value="pct" />
        <ErrorText :error="error" />
        <Button :disabled="!file || pct !== null" @click="send">
          {{ pct !== null ? `Uploading ${pct.toFixed(0)}%` : 'Upload' }}
        </Button>
      </div>
    </CardContent>
  </Card>

  <div class="grid gap-6 xl:grid-cols-3">
    <Card class="xl:col-span-2">
      <CardHeader><CardTitle>Driver packs</CardTitle></CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Applies to</TableHead>
              <TableHead>Drivers</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="p in packs" :key="p.id" class="cursor-pointer" @click="$router.push(`/drivers/${p.id}`)">
              <TableCell>
                <div class="font-medium" :class="{ 'text-muted-foreground line-through': !p.enabled }">{{ p.name }}</div>
                <div class="text-muted-foreground text-xs">{{ p.filename }} · {{ bytes(p.size_bytes) }}</div>
              </TableCell>
              <TableCell>
                <template v-if="p.model_match">{{ p.manufacturer }} {{ p.model_match }}</template>
                <Badge v-else variant="secondary">Any machine, by hardware ID</Badge>
              </TableCell>
              <TableCell class="tabular-nums">{{ p.driver_count }}</TableCell>
              <TableCell><StatusBadge :status="p.status" /></TableCell>
            </TableRow>
            <TableRow v-if="!packs.length">
              <TableCell :colspan="4" class="text-muted-foreground py-8 text-center">No driver packs yet</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Models seen</CardTitle>
        <CardDescription>Every model that has PXE booted, and whether a pack is assigned to it.</CardDescription>
      </CardHeader>
      <CardContent class="space-y-2">
        <div v-for="m in models" :key="m.manufacturer + m.model" class="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
          <div class="min-w-0">
            <div class="truncate text-sm font-medium">{{ m.model || 'Unknown model' }}</div>
            <div class="text-muted-foreground text-xs">{{ m.manufacturer }} · {{ m.hosts }} machine{{ m.hosts === 1 ? '' : 's' }}</div>
          </div>
          <Badge v-if="m.packs.length" variant="success" :title="m.packs.map((p) => p.name).join(', ')">
            {{ m.packs.length }} pack{{ m.packs.length === 1 ? '' : 's' }}
          </Badge>
          <Button v-else size="sm" variant="outline" @click="forModel(m)">Add pack</Button>
        </div>
        <p v-if="!models.length" class="text-muted-foreground text-sm">No machines yet</p>
      </CardContent>
    </Card>
  </div>
</template>
