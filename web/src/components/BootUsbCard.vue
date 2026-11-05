<script setup lang="ts">
import { CircleAlert, Download, LoaderCircle, Usb } from 'lucide-vue-next'
import { onMounted, onUnmounted, ref } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

onMounted(load)
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
        Out of date: the imaging environment or server address has changed since this was built. Build it again.
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
      <p class="text-muted-foreground text-xs">
        Write it to a USB stick with balenaEtcher, Rufus (DD image mode) or <code>dd</code>, then boot from the stick.
        The stick is hidden from the disk list, so a deployment can't wipe it.
      </p>
      <p class="text-muted-foreground text-xs">
        <span class="text-foreground font-medium">Images on the stick:</span> press M on the machine's console to
        capture to or deploy from the stick, with no server needed. When the server is reachable, the console can also
        copy a server image to the stick, including drivers for that machine's model, or upload a stick image to the
        library. Use a stick of 32 GB or more; the first save adds a storage partition to its free space.
      </p>
    </CardContent>
  </Card>
</template>
