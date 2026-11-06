<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ErrorText from '@/components/ErrorText.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { signIn } from '@/lib/auth'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await signIn(username.value, password.value)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    router.replace(next)
  } catch (e: any) {
    error.value = e.message
    password.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-[80vh] items-center justify-center">
    <Card class="w-full max-w-sm">
      <CardHeader>
        <div class="mb-2 flex items-center gap-2 font-semibold">
          <img src="/favicon.svg" alt="" class="size-6 dark:invert" />
          mck-pxe
        </div>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Use your mck-pxe admin account.</CardDescription>
      </CardHeader>
      <CardContent>
        <form class="space-y-4" @submit.prevent="submit">
          <div class="space-y-2">
            <Label for="username">Username</Label>
            <Input id="username" v-model="username" autocomplete="username" autocapitalize="none" autofocus />
          </div>
          <div class="space-y-2">
            <Label for="password">Password</Label>
            <Input id="password" v-model="password" type="password" autocomplete="current-password" />
          </div>
          <ErrorText :error="error" />
          <Button type="submit" class="w-full" :disabled="busy || !username || !password">
            {{ busy ? 'Signing in…' : 'Sign in' }}
          </Button>
        </form>
      </CardContent>
    </Card>
  </div>
</template>
