<script setup lang="ts">
import { ArrowLeft, Trash2 } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { api, get } from '@/lib/api'
import { bytes, dateTime } from '@/lib/format'
import { driverLabel, storageLabel } from '@/lib/storage'
import type { Image } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const image = ref<Image | null>(null)
const form = ref({ name: '', description: '', os_family: 'other', unattend: '' })
const error = ref('')
const saved = ref(false)

onMounted(async () => {
  image.value = await get(`/images/${route.params.id}`)
  const i = image.value!
  form.value = { name: i.name, description: i.description, os_family: i.os_family, unattend: i.unattend ?? '' }
})

async function save() {
  error.value = ''
  try {
    image.value = { ...image.value!, ...(await api('PATCH', `/images/${image.value!.id}`, form.value)) }
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } catch (e: any) {
    error.value = e.message
  }
}

async function remove() {
  if (!confirm(`Delete ${image.value?.name}? Its files are removed from the server.`)) return
  try {
    await api('DELETE', `/images/${image.value!.id}`)
    router.push('/images')
  } catch (e: any) {
    error.value = e.message
  }
}
</script>

<template>
  <template v-if="image">
    <PageHeader :title="image.name" :description="`${image.kind === 'wim' ? 'Windows WIM' : 'Block-level'} image · ${bytes(image.size_bytes)}`">
      <template #back>
        <RouterLink to="/images" class="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm">
          <ArrowLeft class="size-4" /> Images
        </RouterLink>
      </template>
      <StatusBadge :status="image.status" />
      <Button variant="outline" size="sm" @click="remove"><Trash2 /> Delete</Button>
    </PageHeader>
    <p v-if="image.error" class="border-destructive/40 bg-destructive/10 text-destructive mb-6 rounded-md border p-3 text-sm">
      {{ image.error }}
    </p>

    <div class="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Details</CardTitle></CardHeader>
        <CardContent class="space-y-4">
          <div class="space-y-2"><Label for="n">Name</Label><Input id="n" v-model="form.name" /></div>
          <div class="space-y-2"><Label for="d">Description</Label><Input id="d" v-model="form.description" /></div>
          <div class="space-y-2">
            <Label for="os">Operating system</Label>
            <NativeSelect id="os" v-model="form.os_family">
              <option value="windows">Windows (enables driver injection)</option>
              <option value="linux">Linux</option>
              <option value="other">Other</option>
            </NativeSelect>
          </div>
          <div v-if="form.os_family === 'windows'" class="space-y-2">
            <Label for="u">unattend.xml (optional)</Label>
            <Textarea id="u" v-model="form.unattend" class="h-48 font-mono text-xs" placeholder="&lt;?xml version=&quot;1.0&quot;?&gt;&#10;&lt;unattend xmlns=&quot;urn:schemas-microsoft-com:unattend&quot;&gt;…" />
            <p class="text-muted-foreground text-xs">Copied to C:\Windows\Panther\unattend.xml on every deployment.</p>
          </div>
          <ErrorText :error="error" />
          <Button @click="save">{{ saved ? 'Saved' : 'Save' }}</Button>
          <p class="text-muted-foreground text-xs">Created {{ dateTime(image.created_at) }} by {{ image.created_by }} from {{ image.source }}</p>
          <p v-if="image.os_family === 'windows'" class="text-sm">
            <span class="text-muted-foreground">Captured on storage:</span>
            {{ image.meta.storage?.storage ? `${storageLabel(image.meta.storage)} (Windows boots with ${driverLabel(image.meta.storage.boot_driver)})`
               : image.kind === 'wim' ? 'not recorded; a stock WIM has no Intel RST driver' : 'not recorded (captured before storage detection)' }}
          </p>
        </CardContent>
      </Card>

      <Card v-if="image.kind === 'wim'">
        <CardHeader>
          <CardTitle>Editions</CardTitle>
          <CardDescription>Pick one when deploying.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Name</TableHead><TableHead>Size</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow v-for="ix in image.meta.indexes" :key="ix.index">
                <TableCell>{{ ix.index }}</TableCell>
                <TableCell>{{ ix.name }}</TableCell>
                <TableCell class="tabular-nums">{{ bytes(ix.bytes) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card v-else>
        <CardHeader>
          <CardTitle>Partitions</CardTitle>
          <CardDescription>
            {{ image.meta.table?.toUpperCase() }} table. Needs a disk of at least {{ bytes(image.meta.required_bytes) }}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow><TableHead>#</TableHead><TableHead>Filesystem</TableHead><TableHead>Label</TableHead><TableHead>Size</TableHead><TableHead>Method</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="p in image.meta.partitions" :key="p.number">
                <TableCell>{{ p.number }}</TableCell>
                <TableCell>{{ p.fstype || '—' }}</TableCell>
                <TableCell>{{ p.label || '—' }}</TableCell>
                <TableCell class="tabular-nums">{{ bytes(p.size) }}</TableCell>
                <TableCell class="text-muted-foreground text-xs">{{ p.tool }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  </template>
</template>
