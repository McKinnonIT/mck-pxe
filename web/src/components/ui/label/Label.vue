<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <label :class="cn('flex items-center gap-2 text-sm leading-none font-medium select-none', props.class)"><slot /></label>
</template>
