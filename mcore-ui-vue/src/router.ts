import { createRouter, createWebHistory } from 'vue-router';
import Dashboard from '@/views/Dashboard.vue';
import Memories from '@/views/Memories.vue';
import MemoryDetail from '@/views/MemoryDetail.vue';
import Governance from '@/views/Governance.vue';
import Profile from '@/views/Profile.vue';
import Apps from '@/views/Apps.vue';
import GraphView from '@/views/GraphView.vue';
import Settings from '@/views/Settings.vue';

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/memories', name: 'memories', component: Memories },
  { path: '/memory/:id', name: 'memory-detail', component: MemoryDetail },
  { path: '/governance', name: 'governance', component: Governance },
  { path: '/profile', name: 'profile', component: Profile },
  { path: '/apps', name: 'apps', component: Apps },
  { path: '/graph', name: 'graph', component: GraphView },
  { path: '/settings', name: 'settings', component: Settings },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
