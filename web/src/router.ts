import { createRouter, createWebHistory } from 'vue-router'

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
    { path: '/tasks', component: () => import('./views/Tasks.vue'), meta: { title: 'Tasks' } },
    { path: '/tasks/:id', component: () => import('./views/TaskDetail.vue'), meta: { title: 'Task' } },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { title: 'Settings' } },
  ],
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} · mck-pxe`
})
