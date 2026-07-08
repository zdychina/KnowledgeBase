<!-- kb-ui/src/components/charts/OntologyDiGraph.vue -->
<template>
  <div ref="chartRef" :style="{ width: '100%', height }" />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { OntoGraphNode, OntoGraphEdge } from '@/views/knowledge/ontologyGraph'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  nodes: OntoGraphNode[]
  edges: OntoGraphEdge[]
  height?: string
}>(), { height: '600px' })

const emit = defineEmits<{
  (e: 'node-click', id: string): void
  (e: 'edge-click', id: string): void
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// layer → 颜色（concept 蓝 / instance 绿 / property 紫）
const LAYER_COLOR: Record<string, string> = {
  concept: '#0891b2', instance: '#10b981', property: '#8b5cf6',
}
const CANDIDATE_COLOR = '#f59e0b'

function colorOf(layer: string): string {
  return LAYER_COLOR[layer] || LAYER_COLOR.concept
}

function render() {
  if (!chart) return

  const nodes = props.nodes.map(n => ({
    id: n.id,
    name: n.name,
    // 小圆点：名字不再塞进图形内，所以图形可以小一些
    symbolSize: n.isStrong ? 18 : 13,
    symbol: 'circle',
    itemStyle: n.isCandidate
      ? { color: '#fff7ed', borderColor: CANDIDATE_COLOR, borderWidth: 2, borderType: 'dashed' as const }
      : { color: colorOf(n.layer), borderColor: colorOf(n.layer), borderWidth: 1 },
    label: {
      show: true,
      // 名字标签移到圆点下方、不裁切，长中文名完整显示
      position: 'bottom' as const,
      distance: 6,
      fontSize: 12,
      color: n.isCandidate ? CANDIDATE_COLOR : 'var(--kb-text-primary)',
      fontWeight: (n.isStrong ? 700 : 400) as const,
      overflow: 'none' as const,
    },
  }))

  const edges = props.edges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    symbol: e.isDirected ? ['none', 'arrow'] as [string, string] : ['none', 'none'] as [string, string],
    symbolSize: 8,
    label: { show: true, formatter: e.relationName, fontSize: 10, color: e.isCandidate ? CANDIDATE_COLOR : '#64748b' },
    lineStyle: e.isCandidate
      ? { color: CANDIDATE_COLOR, width: 1.5, type: 'dashed' as const, curveness: 0.15 }
      : { color: '#94a3b8', width: 1.5, curveness: 0.15 },
  }))

  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter(p: any) {
        if (p.dataType === 'edge') return `${p.data.source} → ${p.data.target}`
        return p.name
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      edgeSymbolSize: 8,
      force: { repulsion: 320, gravity: 0.06, edgeLength: [120, 240], friction: 0.6 },
      emphasis: { focus: 'adjacency' },
      data: nodes,
      links: edges,
    }],
  }, true)
}

function onChartClick(params: any) {
  if (params.dataType === 'node') emit('node-click', params.data.id as string)
  else if (params.dataType === 'edge') emit('edge-click', params.data.id as string)
}

function onResize() { chart?.resize() }

onMounted(() => {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  chart.on('click', onChartClick)
  render()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(() => [props.nodes, props.edges], render, { deep: true })
</script>
