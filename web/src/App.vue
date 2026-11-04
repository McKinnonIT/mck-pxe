<script setup lang="ts">
import { HardDrive, LayoutDashboard, ListChecks, Monitor, Puzzle, Settings } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { get } from '@/lib/api'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/machines', label: 'Machines', icon: Monitor },
  { to: '/images', label: 'Images', icon: HardDrive },
  { to: '/drivers', label: 'Drivers', icon: Puzzle },
  { to: '/tasks', label: 'Tasks', icon: ListChecks },
  { to: '/settings', label: 'Settings', icon: Settings },
]
const me = ref<{ email: string; name: string } | null>(null)
const authError = ref('')
onMounted(async () => {
  try {
    me.value = await get('/me')
  } catch (e: any) {
    authError.value = e.message
  }
})
</script>

<template>
  <div class="min-h-screen md:flex">
    <aside class="bg-muted/40 border-b md:sticky md:top-0 md:flex md:h-screen md:w-56 md:flex-col md:border-r md:border-b-0">
      <div class="flex items-center gap-2 px-4 py-4 font-semibold">
        <img src="/favicon.svg" alt="" class="size-6 dark:invert" />
        mck-pxe
      </div>
      <nav class="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
        <RouterLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="text-muted-foreground hover:bg-accent hover:text-foreground flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm"
          :exact-active-class="item.to === '/' ? '!bg-accent !text-foreground font-medium' : ''"
          :active-class="item.to === '/' ? '' : '!bg-accent !text-foreground font-medium'"
        >
          <component :is="item.icon" class="size-4" />
          {{ item.label }}
        </RouterLink>
      </nav>
      <div v-if="me" class="text-muted-foreground mt-auto hidden truncate px-4 py-4 text-xs md:block">{{ me.email }}</div>
    </aside>
    <main class="min-w-0 flex-1 px-4 py-6 md:px-8">
      <div v-if="authError" class="border-destructive/40 bg-destructive/10 text-destructive mb-4 rounded-md border p-3 text-sm">
        {{ authError }}
      </div>
      <RouterView />
    </main>
  </div>
</template>
