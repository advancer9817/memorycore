import { createRouter, createWebHistory } from 'vue-router';
import Dashboard from '@/views/Dashboard.vue';
import Memories from '@/views/Memories.vue';
import GraphView from '@/views/GraphView.vue';

const routes = [
  { path: '/', component: Dashboard },
  { path: '/memories', component: Memories },
  { path: '/graph', component: GraphView },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
