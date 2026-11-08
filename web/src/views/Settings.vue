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

// Recompressing new disk images on the server
const compression = ref<{ auto_level: number | null; levels: Record<string, string> } | null>(null)
const compressionSaved = ref(false)
onMounted(async () => (compression.value = await get('/settings/compression')))

async function saveCompression() {
  compressionSaved.value = false
  compression.value = await api('PUT', '/settings/compression', { auto_level: compression.value!.auto_level })
  compressionSaved.value = true
}

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

    <Card v-if="compression">
      <CardHeader>
        <CardTitle>Image compression</CardTitle>
        <CardDescription>
          Machines capture disk images at a fast compression level so captures run at network speed. The server can then
          compress them harder in the background: smaller images, sent faster, and deploys unpack them just as quickly.
          WIM images are already compressed and aren't changed.
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="space-y-2">
          <Label for="auto-compress">After a disk image is captured</Label>
          <NativeSelect id="auto-compress" v-model="compression.auto_level" class="max-w-md" @change="saveCompression">
            <option :value="null">Leave it as captured (fast, zstd level 3)</option>
            <option v-for="(name, level) in compression.levels" :key="level" :value="Number(level)">
              Compress to {{ name }} (zstd level {{ level }})
            </option>
          </NativeSelect>
        </div>
        <p class="text-muted-foreground text-xs">
          Higher levels save more space but keep the server busy for longer (Smallest can take an hour or more per image).
          One image is compressed at a time. To compress an image you already have, open it on the Images page.
          <span v-if="compressionSaved" class="text-success">Saved.</span>
        </p>
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
