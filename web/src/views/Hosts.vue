<script setup lang="ts">
import { computed, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { get, usePoll } from '@/lib/api'
import { ago } from '@/lib/format'
import type { Host } from '@/lib/types'

const hosts = ref<Host[]>([])
const filter = ref('')
usePoll(async () => (hosts.value = await get('/hosts')), 4000)

const shown = computed(() => {
  const f = filter.value.toLowerCase()
  return hosts.value.filter((h) =>
    [h.name, h.mac, h.ip, h.manufacturer, h.model, h.serial].some((v) => v?.toLowerCase().includes(f)),
  )
})
</script>

<template>
  <PageHeader title="Machines" description="Machines appear here the first time they PXE boot into mck-pxe.">
    <Input v-model="filter" placeholder="Search name, MAC, model, serial…" class="w-72" />
  </PageHeader>
  <Card>
    <CardContent>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>MAC / IP</TableHead>
            <TableHead>Boot</TableHead>
            <TableHead class="w-48">Status</TableHead>
            <TableHead>Last seen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="h in shown" :key="h.id" class="cursor-pointer" @click="$router.push(`/machines/${h.id}`)">
            <TableCell class="font-medium">{{ h.name }}</TableCell>
            <TableCell>
              <div>{{ h.model }}</div>
              <div class="text-muted-foreground text-xs">{{ h.manufacturer }} · {{ h.serial }}</div>
            </TableCell>
            <TableCell class="font-mono text-xs">{{ h.mac }}<br />{{ h.ip }}</TableCell>
            <TableCell>
              <Badge variant="outline" class="uppercase">{{ h.boot_mode }}</Badge>
              <Badge v-if="h.secure_boot" variant="outline" class="ml-1">SB</Badge>
            </TableCell>
            <TableCell>
              <div v-if="h.task?.status === 'running'" class="space-y-1">
                <Progress :model-value="h.task.progress" />
                <div class="text-muted-foreground text-xs capitalize">{{ h.task.type }} {{ Math.round(h.task.progress) }}%</div>
              </div>
              <StatusBadge v-else-if="h.task" :status="`${h.task.type} queued`" />
              <StatusBadge v-else :status="h.online ? 'online' : 'offline'" />
            </TableCell>
            <TableCell class="text-muted-foreground text-xs">{{ ago(h.last_seen) }}</TableCell>
          </TableRow>
          <TableRow v-if="!shown.length">
            <TableCell :colspan="6" class="text-muted-foreground py-8 text-center">
              No machines yet. PXE boot a machine on the imaging network and choose “mck-pxe imaging environment”.
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardContent>
  </Card>
</template>
