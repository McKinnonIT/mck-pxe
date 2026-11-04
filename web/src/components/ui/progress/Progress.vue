<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{ modelValue?: number; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div
    role="progressbar"
    :aria-valuenow="modelValue ?? 0"
    aria-valuemin="0"
    aria-valuemax="100"
    :class="cn('bg-primary/15 relative h-2 w-full overflow-hidden rounded-full', props.class)"
  >
    <div class="bg-primary h-full transition-all" :style="{ width: `${Math.min(modelValue ?? 0, 100)}%` }" />
  </div>
</template>
