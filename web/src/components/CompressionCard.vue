<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'
import { computed, onUnmounted, ref, watch } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Progress } from '@/components/ui/progress'
import { api, get } from '@/lib/api'
import { bytes } from '@/lib/format'
import type { Image } from '@/lib/types'

const LEVELS: Record<number, string> = { 9: 'Balanced', 15: 'Small', 19: 'Smallest' }

const props = defineProps<{ image: Image }>()
const emit = defineEmits<{ update: [image: Image] }>()

const c = computed(() => props.image.compression!)
const busy = computed(() => c.value.state === 'queued' || c.value.state === 'running')
const choices = computed(() => Object.keys(LEVELS).map(Number).filter((l) => l > c.value.level))
const level = ref<number>(19)
const error = ref('')

watch(choices, (list) => { if (list.length && !list.includes(level.value)) level.value = list[list.length - 1] }, { immediate: true })

function levelName(l: number) {
  return LEVELS[l] ? `${LEVELS[l]} (zstd level ${l})` : l === 3 ? 'Fast (zstd level 3, as captured)' : `zstd level ${l}`
}

async function start() {
  error.value = ''
  try {
    emit('update', await api('POST', `/images/${props.image.id}/compress`, { level: level.value }))
  } catch (e: any) {
    error.value = e.message
  }
}

// Follow progress while it runs
let timer: number | undefined
watch(busy, (running) => {
  window.clearInterval(timer)
  if (running) timer = window.setInterval(async () => emit('update', await get(`/images/${props.image.id}`)), 2000)
}, { immediate: true })
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>Compression</CardTitle>
      <CardDescription>
        Machines capture at a fast level to keep up with the network. Compressing harder here makes the image smaller and
        quicker to send, and deploys unpack it just as fast. It runs on the server in the background, and the image can be
        deployed meanwhile.
      </CardDescription>
    </CardHeader>
    <CardContent class="space-y-4 text-sm">
      <div>
        <span class="text-muted-foreground">Now:</span> {{ levelName(c.level) }} · {{ bytes(image.size_bytes) }}
        <span v-if="c.saved_bytes && !busy" class="text-success">· saved {{ bytes(c.saved_bytes) }} last time</span>
      </div>

      <div v-if="busy" class="space-y-2">
        <div class="flex items-center gap-2">
          <LoaderCircle class="size-4 animate-spin" />
          {{ c.state === 'queued' ? 'Waiting for another image to finish…' : `Compressing to ${levelName(c.target!)}…` }}
          <span class="text-muted-foreground ml-auto tabular-nums">{{ Math.round(c.progress) }}%</span>
        </div>
        <Progress :model-value="c.progress" />
      </div>

      <template v-else-if="image.status === 'ready' && choices.length">
        <div class="flex flex-wrap items-center gap-2">
          <NativeSelect v-model.number="level" class="w-auto">
            <option v-for="l in choices" :key="l" :value="l">{{ levelName(l) }}</option>
          </NativeSelect>
          <Button @click="start">Compress</Button>
        </div>
        <p class="text-muted-foreground text-xs">
          Higher levels save more but take longer: Smallest can take an hour or more for a large image. Files that wouldn't
          get smaller are left as they are.
        </p>
      </template>
      <p v-else-if="!choices.length" class="text-muted-foreground">Already at the highest level.</p>

      <ErrorText :error="error || (c.state === 'error' ? `Last attempt failed: ${c.error}` : '')" />
    </CardContent>
  </Card>
</template>
