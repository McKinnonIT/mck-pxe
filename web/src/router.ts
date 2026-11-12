import { createRouter, createWebHistory } from 'vue-router'
import { setSignedOutHandler } from '@/lib/api'
import { loadMe, me } from '@/lib/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/Dashboard.vue'), meta: { title: 'Dashboard' } },
    { path: '/machines', component: () => import('./views/Hosts.vue'), meta: { title: 'Machines' } },
    { path: '/machines/:id', component: () => import('./views/HostDetail.vue'), meta: { title: 'Machine' } },
    { path: '/images', component: () => import('./views/Images.vue'), meta: { title: 'Images' } },
    { path: '/images/:id', component: () => import('./views/ImageDetail.vue'), meta: { title: 'Image' } },
    { path: '/drivers', component: () => import('./views/Drivers.vue'), meta: { title: 'Drivers' } },
    { path: '/drivers/:id', component: () => import('./views/DriverPack.vue'), meta: { title: 'Driver pack' } },
    { path: '/isos', component: () => import('./views/IsoLibrary.vue'), meta: { title: 'ISO library' } },
    { path: '/tasks', component: () => import('./views/Tasks.vue'), meta: { title: 'Tasks' } },
    { path: '/tasks/:id', component: () => import('./views/TaskDetail.vue'), meta: { title: 'Task' } },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: 'Settings' } },
    { path: '/users', component: () => import('./views/Users.vue'), meta: { title: 'Users' } },
    { path: '/account', component: () => import('./views/Account.vue'), meta: { title: 'Your account' } },
    { path: '/login', component: () => import('./views/Login.vue'), meta: { title: 'Sign in', public: true } },
  ],
})

// Everything except the sign-in page needs a signed-in admin
router.beforeEach(async (to) => {
  if (me.value === undefined) await loadMe().catch(() => (me.value = null))
  if (to.meta.public) return me.value && to.path === '/login' ? '/' : true
  if (!me.value) return { path: '/login', query: to.fullPath === '/' ? {} : { next: to.fullPath } }
  return true
})

// A session that expires mid-use sends you back to the sign-in page
setSignedOutHandler(() => {
  me.value = null
  const current = router.currentRoute.value
  if (!current.meta.public) router.push({ path: '/login', query: { next: current.fullPath } })
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} · mck-pxe`
})
