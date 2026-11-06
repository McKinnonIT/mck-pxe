<script setup lang="ts">
import { UserPlus } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import ErrorText from '@/components/ErrorText.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, get } from '@/lib/api'
import { me } from '@/lib/auth'
import { dateTime } from '@/lib/format'

interface User {
  id: number
  username: string
  name: string
  role: 'admin' | 'technician'
  enabled: boolean
  created_at: string
  last_login: string | null
}

const users = ref<User[]>([])
const error = ref('')
const load = async () => (users.value = await get('/users'))
onMounted(load)

const showAdd = ref(false)
const form = ref({ username: '', name: '', role: 'technician', password: '' })
const addError = ref('')

async function add() {
  addError.value = ''
  try {
    await api('POST', '/users', form.value)
    form.value = { username: '', name: '', role: 'technician', password: '' }
    showAdd.value = false
    await load()
  } catch (e: any) {
    addError.value = e.message
  }
}

async function change(u: User, data: Partial<User> & { password?: string }) {
  error.value = ''
  try {
    await api('PATCH', `/users/${u.id}`, data)
  } catch (e: any) {
    error.value = e.message
  }
  await load()
}

function resetPassword(u: User) {
  const password = prompt(`New password for ${u.username} (at least 8 characters). They'll be signed out everywhere.`)
  if (password) change(u, { password })
}

async function remove(u: User) {
  if (!confirm(`Delete the account ${u.username}?`)) return
  error.value = ''
  try {
    await api('DELETE', `/users/${u.id}`)
  } catch (e: any) {
    error.value = e.message
  }
  await load()
}
</script>

<template>
  <PageHeader title="Users" description="Accounts for the admin console and for signing in at machines.">
    <Button @click="showAdd = !showAdd"><UserPlus /> Add user</Button>
  </PageHeader>

  <Card v-if="showAdd" class="mb-6">
    <CardHeader>
      <CardTitle>Add a user</CardTitle>
      <CardDescription>
        Admins can use this console and sign in at machines. Technicians can only sign in at machines, to deploy and capture.
      </CardDescription>
    </CardHeader>
    <CardContent>
      <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="add">
        <div class="space-y-2">
          <Label for="username">Username</Label>
          <Input id="username" v-model="form.username" autocapitalize="none" placeholder="jsmith" />
        </div>
        <div class="space-y-2">
          <Label for="name">Name</Label>
          <Input id="name" v-model="form.name" placeholder="Jo Smith" />
        </div>
        <div class="space-y-2">
          <Label for="role">Role</Label>
          <NativeSelect id="role" v-model="form.role">
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
          </NativeSelect>
        </div>
        <div class="space-y-2">
          <Label for="password">Password</Label>
          <Input id="password" v-model="form.password" type="password" autocomplete="new-password" />
          <p class="text-muted-foreground text-xs">At least 8 characters. Give it to them; they can change it later.</p>
        </div>
        <div class="space-y-2 sm:col-span-2">
          <ErrorText :error="addError" />
          <Button type="submit" :disabled="!form.username || !form.password">Add user</Button>
        </div>
      </form>
    </CardContent>
  </Card>

  <Card>
    <CardContent class="pt-6">
      <ErrorText :error="error" class="mb-4" />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>User</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Last sign-in</TableHead>
            <TableHead class="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="u in users" :key="u.id">
            <TableCell>
              <div class="font-medium" :class="{ 'text-muted-foreground line-through': !u.enabled }">{{ u.username }}</div>
              <div class="text-muted-foreground text-xs">{{ u.name }}</div>
            </TableCell>
            <TableCell>
              <div class="flex items-center gap-2">
                <NativeSelect
                  :model-value="u.role"
                  :disabled="u.id === me?.id"
                  class="h-8 w-36"
                  @update:model-value="(v: any) => change(u, { role: v })"
                >
                  <option value="technician">Technician</option>
                  <option value="admin">Admin</option>
                </NativeSelect>
                <Badge v-if="!u.enabled" variant="destructive">Disabled</Badge>
                <Badge v-if="u.id === me?.id" variant="secondary">You</Badge>
              </div>
            </TableCell>
            <TableCell class="text-muted-foreground text-sm">{{ u.last_login ? dateTime(u.last_login) : 'Never' }}</TableCell>
            <TableCell>
              <div v-if="u.id !== me?.id" class="flex justify-end gap-2">
                <Button size="sm" variant="outline" @click="resetPassword(u)">Reset password</Button>
                <Button size="sm" variant="outline" @click="change(u, { enabled: !u.enabled })">
                  {{ u.enabled ? 'Disable' : 'Enable' }}
                </Button>
                <Button size="sm" variant="outline" @click="remove(u)">Delete</Button>
              </div>
              <div v-else class="flex justify-end">
                <RouterLink to="/account" class="text-sm underline">Change password</RouterLink>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </CardContent>
  </Card>
</template>
