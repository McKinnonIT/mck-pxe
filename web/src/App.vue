<script setup lang="ts">
import { HardDrive, LayoutDashboard, ListChecks, LogOut, Monitor, Puzzle, Settings, UserRound, Users } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { me, signOut } from '@/lib/auth'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/machines', label: 'Machines', icon: Monitor },
  { to: '/images', label: 'Images', icon: HardDrive },
  { to: '/drivers', label: 'Drivers', icon: Puzzle },
  { to: '/tasks', label: 'Tasks', icon: ListChecks },
  { to: '/users', label: 'Users', icon: Users },
  { to: '/settings', label: 'Settings', icon: Settings },
]
const route = useRoute()
const router = useRouter()

async function leave() {
  await signOut()
  router.push('/login')
}
</script>

<template>
  <main v-if="route.meta.public" class="px-4 py-6">
    <RouterView />
  </main>
  <div v-else-if="me" class="min-h-screen md:flex">
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
      <div class="mt-auto flex items-center gap-1 px-2 py-2 md:border-t md:py-3">
        <RouterLink
          to="/account"
          class="text-muted-foreground hover:bg-accent hover:text-foreground flex min-w-0 flex-1 items-center gap-2 rounded-md px-3 py-2 text-sm"
          active-class="!bg-accent !text-foreground"
          title="Your account"
        >
          <UserRound class="size-4 shrink-0" />
          <span class="truncate">{{ me.name }}</span>
        </RouterLink>
        <button
          class="text-muted-foreground hover:bg-accent hover:text-foreground rounded-md p-2"
          title="Sign out"
          aria-label="Sign out"
          @click="leave"
        >
          <LogOut class="size-4" />
        </button>
      </div>
    </aside>
    <main class="min-w-0 flex-1 px-4 py-6 md:px-8">
      <RouterView />
    </main>
  </div>
</template>
