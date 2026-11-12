<script setup lang="ts">
import { Upload } from 'lucide-vue-next'
import { ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { get, upload, usePoll } from '@/lib/api'
import { uploadWithToast } from '@/lib/toast'
import { ago, bytes } from '@/lib/format'
import type { Image } from '@/lib/types'

const images = ref<Image[]>([])
usePoll(async () => (images.value = await get('/images')), 5000)

const showUpload = ref(false)
const file = ref<File | null>(null)
const name = ref('')
const description = ref('')

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
  if (file.value && !name.value) name.value = file.value.name.replace(/\.(wim|esd|iso)$/i, '')
}

function send() {
  if (!file.value) return
  const f = file.value
  const q = new URLSearchParams({ name: name.value, description: description.value })
  showUpload.value = false
  file.value = null
  name.value = description.value = ''
  uploadWithToast<Image>(q.get('name') || f.name, (p) => upload(`/images/upload-wim?${q}`, f, p), (i) => `/images/${i.id}`)
}
</script>

<template>
  <PageHeader title="Images" description="Capture images from a PXE-booted machine, or upload a Windows ISO or WIM.">
    <Button @click="showUpload = !showUpload"><Upload /> Upload ISO or WIM</Button>
  </PageHeader>

  <Card v-if="showUpload" class="mb-6">
    <CardHeader>
      <CardTitle>Upload Windows</CardTitle>
      <CardDescription>
        Upload a Windows ISO as it is, such as one downloaded from Microsoft. You can also upload install.wim or install.esd, or a WIM you captured with DISM. Every edition inside can be deployed.
      </CardDescription>
    </CardHeader>
    <CardContent class="grid gap-4 sm:grid-cols-2">
      <div class="space-y-2 sm:col-span-2">
        <Label for="file">ISO, WIM or ESD file</Label>
        <Input id="file" type="file" accept=".wim,.esd,.iso" @change="pick" />
      </div>
      <div class="space-y-2">
        <Label for="iname">Name</Label>
        <Input id="iname" v-model="name" />
      </div>
      <div class="space-y-2">
        <Label for="idesc">Description</Label>
        <Input id="idesc" v-model="description" />
      </div>
      <div class="space-y-2 sm:col-span-2">
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
            <TableHead>Type</TableHead>
            <TableHead>Size</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="i in images" :key="i.id" class="cursor-pointer" @click="$router.push(`/images/${i.id}`)">
            <TableCell>
              <div class="font-medium">{{ i.name }}</div>
              <div class="text-muted-foreground text-xs">{{ i.description }}</div>
            </TableCell>
            <TableCell>
              <Badge variant="outline">{{ i.kind === 'wim' ? 'WIM' : 'Block' }}</Badge>
              <Badge variant="secondary" class="ml-1 capitalize">{{ i.os_family }}</Badge>
            </TableCell>
            <TableCell class="tabular-nums">{{ bytes(i.size_bytes) }}</TableCell>
            <TableCell>
              <StatusBadge :status="i.status" />
              <div v-if="i.compression?.state === 'running'" class="text-muted-foreground mt-1 text-xs tabular-nums">
                Compressing {{ Math.round(i.compression.progress) }}%
              </div>
              <div v-else-if="i.compression?.state === 'queued'" class="text-muted-foreground mt-1 text-xs">Waiting to compress</div>
            </TableCell>
            <TableCell class="text-muted-foreground text-xs">{{ i.source }}</TableCell>
            <TableCell class="text-muted-foreground text-xs">{{ ago(i.created_at) }}<br />{{ i.created_by }}</TableCell>
          </TableRow>
          <TableRow v-if="!images.length">
            <TableCell :colspan="6" class="text-muted-foreground py-8 text-center">No images yet</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardContent>
  </Card>
</template>
