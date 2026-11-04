<script setup lang="ts">
defineProps<{ error?: string | null }>()
</script>

<template>
  <p v-if="error" class="text-destructive text-sm">{{ error }}</p>
</template>
