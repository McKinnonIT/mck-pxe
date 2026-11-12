<script setup lang="ts">
import { ArrowLeft, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, get } from '@/lib/api'
import { showToast } from '@/lib/toast'
import { bytes } from '@/lib/format'
import type { DriverPack } from '@/lib/types'

const route = useRoute()
const router = useRouter()
const pack = ref<DriverPack | null>(null)
const form = ref({ name: '', manufacturer: '', model_match: '', enabled: true })
const filter = ref('')
const error = ref('')

onMounted(async () => {
  pack.value = await get(`/driver-packs/${route.params.id}`)
  const p = pack.value!
  form.value = { name: p.name, manufacturer: p.manufacturer, model_match: p.model_match, enabled: p.enabled }
})

const shown = computed(() => {
  const f = filter.value.toLowerCase()
  return (pack.value?.drivers ?? []).filter((d) =>
    [d.inf_path, d.class_name, d.provider].some((v) => v.toLowerCase().includes(f)),
  )
})

async function save() {
  error.value = ''
  try {
    await api('PATCH', `/driver-packs/${pack.value!.id}`, form.value)
    showToast({ title: 'Saved', variant: 'success' })
  } catch (e: any) {
    error.value = e.message
  }
}

async function remove() {
  if (!confirm(`Delete ${pack.value?.name}?`)) return
  await api('DELETE', `/driver-packs/${pack.value!.id}`)
  router.push('/drivers')
}
</script>

<template>
  <template v-if="pack">
    <PageHeader :title="pack.name" :description="`${pack.driver_count} drivers · ${bytes(pack.size_bytes)} · ${pack.filename}`">
      <template #back>
        <RouterLink to="/drivers" class="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm">
          <ArrowLeft class="size-4" /> Drivers
        </RouterLink>
      </template>
      <StatusBadge :status="pack.status" />
      <Button variant="outline" size="sm" @click="remove"><Trash2 /> Delete</Button>
    </PageHeader>
    <p v-if="pack.error" class="border-destructive/40 bg-destructive/10 text-destructive mb-6 rounded-md border p-3 text-sm">
      {{ pack.error }}
    </p>

    <div class="grid gap-6 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Matching</CardTitle>
          <CardDescription>
            With a model match, every driver in this pack goes to matching machines. Without one, machines only get the
            drivers whose hardware IDs they have.
          </CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="space-y-2"><Label for="n">Name</Label><Input id="n" v-model="form.name" /></div>
          <div class="space-y-2"><Label for="m">Manufacturer</Label><Input id="m" v-model="form.manufacturer" /></div>
          <div class="space-y-2">
            <Label for="mm">Model match (comma separated)</Label>
            <Input id="mm" v-model="form.model_match" placeholder="Leave empty for hardware ID matching" />
          </div>
          <Label class="font-normal"><input v-model="form.enabled" type="checkbox" class="size-4" /> Enabled</Label>
          <ErrorText :error="error" />
          <Button @click="save">Save</Button>
        </CardContent>
      </Card>

      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle>Drivers</CardTitle>
          <CardDescription>64-bit Windows drivers found in this pack.</CardDescription>
        </CardHeader>
        <CardContent class="space-y-3">
          <Input v-model="filter" placeholder="Filter by path, class or provider…" />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>INF</TableHead>
                <TableHead>Class</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Devices</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="d in shown" :key="d.id">
                <TableCell class="max-w-72 truncate font-mono text-xs" :title="d.inf_path">{{ d.inf_path }}</TableCell>
                <TableCell>{{ d.class_name }}</TableCell>
                <TableCell>{{ d.provider }}</TableCell>
                <TableCell class="text-xs">{{ d.version }}</TableCell>
                <TableCell class="tabular-nums">{{ d.hardware_id_count }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  </template>
</template>
