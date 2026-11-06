<script setup lang="ts">
import { CircleCheck, CircleX } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import BootUsbCard from '@/components/BootUsbCard.vue'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { api, get, upload } from '@/lib/api'

interface Settings {
  server_ip: string
  bcd_present: boolean
  bootenv: Record<string, boolean>
}
const s = ref<Settings | null>(null)
const error = ref('')
const load = async () => (s.value = await get('/settings'))
onMounted(load)

// What machines boot when nothing is queued for them
const menu = ref<{ default: 'imaging' | 'local'; timeout: number } | null>(null)
const menuError = ref('')
const menuSaved = ref(false)
onMounted(async () => (menu.value = await get('/settings/boot-menu')))

async function saveMenu() {
  menuError.value = ''
  menuSaved.value = false
  try {
    menu.value = await api('PUT', '/settings/boot-menu', menu.value)
    menuSaved.value = true
  } catch (e: any) {
    menuError.value = e.message
  }
}

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
  <PageHeader title="Settings" description="Server address and imaging environment come from the server's settings file; the rest is set here." />
  <div v-if="s" class="grid gap-6 lg:grid-cols-2">
    <Card>
      <CardHeader>
        <CardTitle>Server</CardTitle>
      </CardHeader>
      <CardContent>
        <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt class="text-muted-foreground">Server IP</dt><dd class="font-mono">{{ s.server_ip }}</dd>
        </dl>
      </CardContent>
    </Card>

    <Card v-if="menu">
      <CardHeader>
        <CardTitle>PXE boot menu</CardTitle>
        <CardDescription>
          What a machine starts when it PXE boots with nothing queued for it. Machines with a queued deploy or capture
          always go straight into the imaging environment.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="saveMenu">
          <div class="space-y-2">
            <Label for="boot-default">Default entry</Label>
            <NativeSelect id="boot-default" v-model="menu.default" @change="menuSaved = false">
              <option value="imaging">mck-pxe imaging environment (first entry)</option>
              <option value="local">Boot from local disk (last entry)</option>
            </NativeSelect>
          </div>
          <div class="space-y-2">
            <Label for="boot-timeout">Countdown (seconds)</Label>
            <Input id="boot-timeout" v-model.number="menu.timeout" type="number" min="0" max="300" @input="menuSaved = false" />
          </div>
          <p v-if="menu.default === 'imaging'" class="text-muted-foreground text-xs sm:col-span-2">
            Machines that try the network before their disk will start mck-pxe every time they boot, until someone picks
            the local disk. Choose the local disk if that's how your machines are set up.
          </p>
          <div class="flex items-center gap-3 sm:col-span-2">
            <Button type="submit">Save</Button>
            <span v-if="menuSaved" class="text-success text-sm">Saved. Applies from the next PXE boot.</span>
            <ErrorText :error="menuError" />
          </div>
        </form>
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
