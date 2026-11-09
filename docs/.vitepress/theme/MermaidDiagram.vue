<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useData } from 'vitepress'

const props = defineProps<{ source: string }>()
const { isDark } = useData()
const svg = ref('')
const error = ref('')
let mounted = false
let generation = 0

async function renderDiagram() {
  const currentGeneration = ++generation
  svg.value = ''
  error.value = ''
  try {
    // Keep the diagram renderer out of VitePress server-side rendering.
    const mermaid = (await import('mermaid')).default
    if (!mounted || currentGeneration !== generation) return
    mermaid.initialize({
      startOnLoad: false,
      theme: isDark.value ? 'dark' : 'default',
      securityLevel: 'strict',
    })
    // Unique ids prevent one diagram from overwriting another after a reload.
    const id = 'maw-mermaid-' + Math.random().toString(36).slice(2)
    const result = await mermaid.render(id, props.source)
    if (!mounted || currentGeneration !== generation) return
    // Mermaid's strict security level sanitizes SVG before insertion.
    svg.value = result.svg
  } catch {
    if (mounted && currentGeneration === generation) {
      error.value = 'Не удалось отобразить диаграмму Mermaid; исходный код показан ниже.'
    }
  }
}

watch([() => props.source, isDark], () => {
  if (mounted) void renderDiagram()
})

onMounted(() => {
  mounted = true
  void renderDiagram()
})

onUnmounted(() => {
  mounted = false
  generation++
})
</script>

<template>
  <div class="maw-mermaid">
    <div v-if="svg" class="maw-mermaid__svg" v-html="svg" />
    <pre v-else><code>{{ source }}</code></pre>
    <p v-if="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.maw-mermaid {
  margin: 1rem 0;
  overflow-x: auto;
}
.maw-mermaid__svg {
  text-align: center;
}
.maw-mermaid :deep(svg) {
  max-width: 100%;
  height: auto;
}
</style>
