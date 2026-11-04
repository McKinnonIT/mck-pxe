<script setup lang="ts">
import { ArrowLeft } from 'lucide-vue-next'
import { nextTick, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { api, get, usePoll } from '@/lib/api'
import { dateTime } from '@/lib/format'
import type { TaskSummary } from '@/lib/types'

const route = useRoute()
const task = ref<TaskSummary | null>(null)
const logEl = ref<HTMLElement | null>(null)

usePoll(async () => {
  const before = task.value?.log?.length
  task.value = await get(`/tasks/${route.params.id}`)
  if (task.value?.log?.length !== before) {
    await nextTick()
    logEl.value?.scrollTo({ top: logEl.value.scrollHeight })
  }
}, 2000)

async function cancel() {
  if (!confirm('Cancel this task? A deployment stopped part-way leaves the disk unbootable.')) return
  task.value = await api('POST', `/tasks/${task.value!.id}/cancel`)
}
</script>

<template>
  <template v-if="task">
    <PageHeader :title="`Task #${task.id}: ${task.type} ${task.kind}`" :description="`${task.host?.name} · ${task.disk}`">
      <template #back>
        <RouterLink to="/tasks" class="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm">
          <ArrowLeft class="size-4" /> Tasks
        </RouterLink>
      </template>
      <StatusBadge :status="task.cancel_requested && task.status === 'running' ? 'cancelling' : task.status" />
      <Button v-if="['queued', 'running'].includes(task.status)" variant="destructive" size="sm" @click="cancel">Cancel</Button>
    </PageHeader>

    <div class="grid gap-6 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <CardHeader><CardTitle>Progress</CardTitle></CardHeader>
        <CardContent class="space-y-3">
          <Progress :model-value="task.progress" />
          <div class="flex justify-between text-sm">
            <span>{{ task.message || 'Waiting for the machine to PXE boot…' }}</span>
            <span class="tabular-nums">{{ Math.round(task.progress) }}%</span>
          </div>
          <pre ref="logEl" class="bg-muted max-h-96 overflow-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap">{{ task.log || 'No log yet' }}</pre>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Details</CardTitle></CardHeader>
        <CardContent>
          <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt class="text-muted-foreground">Machine</dt>
            <dd><RouterLink v-if="task.host" :to="`/machines/${task.host.id}`" class="underline">{{ task.host.name }}</RouterLink></dd>
            <dt class="text-muted-foreground">Image</dt>
            <dd><RouterLink v-if="task.image" :to="`/images/${task.image.id}`" class="underline">{{ task.image.name }}</RouterLink></dd>
            <dt class="text-muted-foreground">Disk</dt><dd class="font-mono">{{ task.disk }}</dd>
            <template v-if="task.params.wim_index">
              <dt class="text-muted-foreground">Edition</dt><dd>{{ task.params.wim_index }}</dd>
            </template>
            <template v-if="task.params.drivers">
              <dt class="text-muted-foreground">Drivers</dt>
              <dd>
                {{ task.params.drivers }}
                <span v-if="task.params.driver_plan" class="text-muted-foreground">
                  ({{ task.params.driver_plan.map((p: any) => `${p.name}: ${p.count}`).join(', ') || 'none matched' }})
                </span>
              </dd>
            </template>
            <dt class="text-muted-foreground">Afterwards</dt><dd>{{ task.params.after }}</dd>
            <dt class="text-muted-foreground">Created</dt><dd>{{ dateTime(task.created_at) }}<br />{{ task.created_by }}</dd>
            <dt class="text-muted-foreground">Started</dt><dd>{{ dateTime(task.started_at) }}</dd>
            <dt class="text-muted-foreground">Finished</dt><dd>{{ dateTime(task.finished_at) }}</dd>
          </dl>
        </CardContent>
      </Card>
    </div>
  </template>
</template>
