<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import TaskTable from '@/components/TaskTable.vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { get, usePoll } from '@/lib/api'
import { bytes } from '@/lib/format'
import type { TaskSummary } from '@/lib/types'

interface Overview {
  hosts: number
  online: number
  images: number
  image_bytes: number
  driver_packs: number
  active_tasks: TaskSummary[]
  recent_tasks: TaskSummary[]
}
const data = ref<Overview | null>(null)
usePoll(async () => (data.value = await get('/overview')), 3000)
</script>

<template>
  <PageHeader title="Dashboard" description="Network imaging for Windows and Linux machines" />
  <div v-if="data" class="space-y-6">
    <div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Card v-for="s in [
        { label: 'Machines online', value: `${data.online} / ${data.hosts}`, to: '/machines' },
        { label: 'Images', value: data.images, to: '/images' },
        { label: 'Image storage', value: bytes(data.image_bytes), to: '/images' },
        { label: 'Driver packs', value: data.driver_packs, to: '/drivers' },
      ]" :key="s.label" class="cursor-pointer gap-2 py-4" @click="$router.push(s.to)">
        <CardContent class="px-4">
          <div class="text-muted-foreground text-sm">{{ s.label }}</div>
          <div class="mt-1 text-2xl font-semibold tabular-nums">{{ s.value }}</div>
        </CardContent>
      </Card>
    </div>
    <Card>
      <CardHeader><CardTitle>Active tasks</CardTitle></CardHeader>
      <CardContent><TaskTable :tasks="data.active_tasks" /></CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>Recent tasks</CardTitle></CardHeader>
      <CardContent><TaskTable :tasks="data.recent_tasks" /></CardContent>
    </Card>
  </div>
</template>
