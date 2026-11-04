<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'

const props = defineProps<{ status: string }>()
const variant = computed(() => {
  switch (props.status) {
    case 'ready':
    case 'done':
    case 'online':
      return 'success'
    case 'error':
    case 'failed':
      return 'destructive'
    case 'running':
    case 'processing':
    case 'capturing':
    case 'uploading':
    case 'queued':
      return 'warning'
    default:
      return 'secondary'
  }
})
</script>

<template>
  <Badge :variant="variant">{{ status }}</Badge>
</template>
