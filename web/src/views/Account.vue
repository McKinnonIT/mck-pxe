<script setup lang="ts">
import { ref } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { me } from '@/lib/auth'

const form = ref({ current: '', new: '', confirm: '' })
const error = ref('')
const done = ref(false)

async function save() {
  error.value = ''
  done.value = false
  if (form.value.new !== form.value.confirm) {
    error.value = "The new passwords don't match"
    return
  }
  try {
    await api('POST', '/me/password', { current: form.value.current, new: form.value.new })
    form.value = { current: '', new: '', confirm: '' }
    done.value = true
  } catch (e: any) {
    error.value = e.message
  }
}
</script>

<template>
  <PageHeader title="Your account" :description="me ? `Signed in as ${me.username}` : ''" />
  <Card class="max-w-md">
    <CardHeader>
      <CardTitle>Change password</CardTitle>
      <CardDescription>You stay signed in here; you're signed out everywhere else.</CardDescription>
    </CardHeader>
    <CardContent>
      <form class="space-y-4" @submit.prevent="save">
        <div class="space-y-2">
          <Label for="current">Current password</Label>
          <Input id="current" v-model="form.current" type="password" autocomplete="current-password" />
        </div>
        <div class="space-y-2">
          <Label for="new">New password</Label>
          <Input id="new" v-model="form.new" type="password" autocomplete="new-password" />
          <p class="text-muted-foreground text-xs">At least 8 characters.</p>
        </div>
        <div class="space-y-2">
          <Label for="confirm">New password again</Label>
          <Input id="confirm" v-model="form.confirm" type="password" autocomplete="new-password" />
        </div>
        <ErrorText :error="error" />
        <p v-if="done" class="text-success text-sm">Password changed.</p>
        <Button type="submit" :disabled="!form.current || !form.new">Change password</Button>
      </form>
    </CardContent>
  </Card>
</template>
