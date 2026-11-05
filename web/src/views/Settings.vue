<script setup lang="ts">
import { CircleCheck, CircleX } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import BootUsbCard from '@/components/BootUsbCard.vue'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api, get, upload } from '@/lib/api'

interface Settings {
  server_ip: string
  default_boot: string
  pin_required: boolean
  bcd_present: boolean
  bootenv: Record<string, boolean>
}
const s = ref<Settings | null>(null)
const error = ref('')
const load = async () => (s.value = await get('/settings'))
onMounted(load)

async function uploadBcd(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  error.value = ''
  try {
    await upload('/settings/bcd', file, () => {})
    await load()
  } catch (err: any) {
    error.value = err.message
  }
}

async function removeBcd() {
  if (!confirm('Remove the BCD template? WIM deployments will stop working until you upload another.')) return
  await api('DELETE', '/settings/bcd')
  await load()
}
</script>

<template>
  <PageHeader title="Settings" description="Server values come from the .env file on the server." />
  <div v-if="s" class="grid gap-6 lg:grid-cols-2">
    <Card>
      <CardHeader>
        <CardTitle>Server</CardTitle>
      </CardHeader>
      <CardContent>
        <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt class="text-muted-foreground">Server IP</dt><dd class="font-mono">{{ s.server_ip }}</dd>
          <dt class="text-muted-foreground">Default boot</dt>
          <dd>{{ s.default_boot === 'imaging' ? 'mck-pxe imaging environment' : 'Local disk (after 5 s)' }}</dd>
          <dt class="text-muted-foreground">Console PIN</dt><dd>{{ s.pin_required ? 'Required' : 'Not set (anyone can deploy from a machine)' }}</dd>
        </dl>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Imaging environment</CardTitle>
        <CardDescription>Built with scripts/build-bootenv.sh</CardDescription>
      </CardHeader>
      <CardContent class="space-y-2 text-sm">
        <div v-for="(ok, name) in s.bootenv" :key="name" class="flex items-center gap-2">
          <CircleCheck v-if="ok" class="text-success size-4" />
          <CircleX v-else class="text-destructive size-4" />
          <span class="font-mono">{{ name }}</span>
        </div>
      </CardContent>
    </Card>

    <BootUsbCard class="lg:col-span-2" />

    <Card class="lg:col-span-2">
      <CardHeader>
        <CardTitle>Windows boot template (BCD)</CardTitle>
        <CardDescription>
          Needed to deploy WIM images. Linux can't run bcdboot, so mck-pxe copies a generic boot configuration that finds
          Windows on whatever disk it's deployed to. Make one on any Windows PC with tools/make-generic-bcd.ps1, then upload it here.
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="flex items-center gap-2 text-sm">
          <CircleCheck v-if="s.bcd_present" class="text-success size-4" />
          <CircleX v-else class="text-destructive size-4" />
          {{ s.bcd_present ? 'Template uploaded' : 'No template yet' }}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Input type="file" class="max-w-sm" @change="uploadBcd" />
          <Button v-if="s.bcd_present" variant="outline" @click="removeBcd">Remove</Button>
        </div>
        <ErrorText :error="error" />
      </CardContent>
    </Card>
  </div>
</template>
