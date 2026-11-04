<script setup lang="ts">
import StatusBadge from '@/components/StatusBadge.vue'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ago } from '@/lib/format'
import type { TaskSummary } from '@/lib/types'

defineProps<{ tasks: TaskSummary[]; hideHost?: boolean }>()
</script>

<template>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Task</TableHead>
        <TableHead v-if="!hideHost">Machine</TableHead>
        <TableHead>Image</TableHead>
        <TableHead class="w-56">Progress</TableHead>
        <TableHead>Started by</TableHead>
        <TableHead>When</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow v-for="t in tasks" :key="t.id" class="cursor-pointer" @click="$router.push(`/tasks/${t.id}`)">
        <TableCell>
          <div class="font-medium capitalize">{{ t.type }} · {{ t.kind }}</div>
          <div class="text-muted-foreground text-xs">#{{ t.id }} {{ t.disk }}</div>
        </TableCell>
        <TableCell v-if="!hideHost">{{ t.host?.name }}</TableCell>
        <TableCell>{{ t.image?.name ?? '—' }}</TableCell>
        <TableCell>
          <div v-if="t.status === 'running'" class="space-y-1">
            <Progress :model-value="t.progress" />
            <div class="text-muted-foreground truncate text-xs">{{ t.message }}</div>
          </div>
          <div v-else class="flex items-center gap-2">
            <StatusBadge :status="t.status" />
            <span v-if="t.status === 'failed'" class="text-muted-foreground max-w-48 truncate text-xs" :title="t.message">
              {{ t.message }}
            </span>
          </div>
        </TableCell>
        <TableCell class="text-muted-foreground text-xs">{{ t.created_by }}</TableCell>
        <TableCell class="text-muted-foreground text-xs">{{ ago(t.created_at) }}</TableCell>
      </TableRow>
      <TableRow v-if="!tasks.length">
        <TableCell :colspan="6" class="text-muted-foreground py-8 text-center">No tasks</TableCell>
      </TableRow>
    </TableBody>
  </Table>
</template>
