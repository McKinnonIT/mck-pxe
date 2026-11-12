<script setup lang="ts">
import { CircleAlert, CircleCheck, LoaderCircle, X } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { closeToast, toast } from '@/lib/toast'

const icons = { neutral: LoaderCircle, success: CircleCheck, error: CircleAlert }
const rings = {
  neutral: 'border-muted bg-muted/60 text-muted-foreground',
  success: 'border-success/10 bg-success/15 text-success',
  error: 'border-destructive/10 bg-destructive/15 text-destructive',
}

// Auto-close, paused while hovered or focused (the draining bar pauses with it)
const paused = ref(false)
let timer: number | undefined
let left = 0
let startedAt = 0
function arm(ms: number) {
  window.clearTimeout(timer)
  left = ms
  startedAt = Date.now()
  timer = window.setTimeout(closeToast, ms)
}
watch(
  () => [toast.id, toast.open, toast.persist] as const,
  ([, open, persist]) => {
    window.clearTimeout(timer)
    paused.value = false
    if (open && !persist) arm(toast.duration ?? 4000)
  },
)
function pause() {
  if (!toast.open || toast.persist || paused.value) return
  paused.value = true
  window.clearTimeout(timer)
  left -= Date.now() - startedAt
}
function resume() {
  if (!paused.value) return
  paused.value = false
  arm(left)
}
</script>

<template>
  <div class="fixed right-0 bottom-0 z-50 w-full p-4 md:w-[390px] md:p-6" aria-live="polite" aria-atomic="true">
    <Transition
      enter-from-class="translate-x-full opacity-0"
      leave-to-class="opacity-0"
      enter-active-class="transition duration-150 ease-out"
      leave-active-class="transition duration-100 ease-in"
    >
      <div
        v-if="toast.open"
        :key="toast.id"
        role="status"
        class="bg-card text-card-foreground relative flex items-center gap-4 overflow-hidden rounded-lg border p-3 pb-4 shadow-xl"
        @mouseenter="pause"
        @mouseleave="resume"
        @focusin="pause"
        @focusout="resume"
      >
        <div :class="['flex size-10 shrink-0 items-center justify-center rounded-full border-[6px]', rings[toast.variant]]">
          <component :is="icons[toast.variant]" :class="['size-4', toast.variant === 'neutral' && 'animate-spin']" />
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold">{{ toast.title }}</p>
          <p v-if="toast.message" class="text-muted-foreground text-sm break-words">{{ toast.message }}</p>
        </div>
        <button class="text-muted-foreground hover:text-foreground self-start p-1" aria-label="Close notification" @click="closeToast">
          <X class="size-4" />
        </button>

        <div class="bg-muted absolute inset-x-0 bottom-0 h-1">
          <div
            v-if="toast.persist"
            role="progressbar"
            :aria-label="toast.title"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="toast.progress === undefined ? undefined : Math.round(toast.progress)"
            class="toast-progress h-full transition-[width] duration-500 ease-out"
            :style="{ width: `${Math.min(Math.max(toast.progress ?? 100, 0), 100)}%` }"
          />
          <div
            v-else
            aria-hidden="true"
            class="toast-countdown h-full"
            :style="{ animationDuration: `${toast.duration ?? 4000}ms`, animationPlayState: paused ? 'paused' : 'running' }"
          />
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* The shelf-plus strip, in this app's colours */
.toast-progress,
.toast-countdown {
  background: linear-gradient(90deg, var(--primary), var(--muted-foreground), var(--primary));
  background-size: 200% 100%;
}
.toast-progress {
  animation: toast-shimmer 2s linear infinite;
}
.toast-countdown {
  transform-origin: left;
  animation-name: toast-countdown;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes toast-shimmer {
  to {
    background-position: -200% 0;
  }
}
@keyframes toast-countdown {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .toast-progress {
    animation-duration: 8s;
  }
}
</style>
