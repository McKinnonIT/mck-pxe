<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import TaskTable from '@/components/TaskTable.vue'
import { Card, CardContent } from '@/components/ui/card'
import { get, usePoll } from '@/lib/api'
import type { TaskSummary } from '@/lib/types'

const tasks = ref<TaskSummary[]>([])
usePoll(async () => (tasks.value = await get('/tasks?limit=200')), 3000)
</script>

<template>
  <PageHeader title="Tasks" description="Captures and deployments, newest first." />
  <Card>
    <CardContent><TaskTable :tasks="tasks" /></CardContent>
  </Card>
</template>
