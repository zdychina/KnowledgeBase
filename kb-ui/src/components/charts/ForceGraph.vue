<template>
  <div ref="chartRef" :style="{ width: '100%', height }" />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart as EchartsGraph } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([EchartsGraph, TooltipComponent, CanvasRenderer])

export interface GraphNode {
  id: string
  name: string
  category?: number
  symbolSize?: number
  value?: number
}

export interface GraphEdge {
  source: string
  target: string
  relationType: string
  weight?: number
}

const props = withDefaults(defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  categories?: { name: string }[]
  height?: string
}>(), {
  height: '520px',
})

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const palette = ['#0891b2', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6']

function render() {
  if (!chart) return

  const nodes = props.nodes.map(n => ({
    id: n.id,
    name: n.name || n.id.slice(0, 8),
    category: n.category ?? 0,
    symbolSize: n.symbolSize ?? 20 + (n.value ? Math.min(n.value * 2, 30) : 0),
    itemStyle: { color: palette[n.category ?? 0] },
    label: { show: true, fontSize: 11, color: '#334155' },
  }))

  const edges = props.edges.map(e => ({
    source: e.source,
    target: e.target,
    value: e.weight,
    lineStyle: {
      width: Math.max(1, Math.min((e.weight ?? 1) * 2, 6)),
      color: '#94a3b8',
      curveness: 0.15,
    },
  }))

  chart.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#0f172a', fontSize: 12 },
      formatter(params: any) {
        if (params.dataType === 'edge') {
          return `${params.data.source.slice(0, 8)} → ${params.data.target.slice(0, 8)}`
        }
        return params.name
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      force: {
        repulsion: 180,
        gravity: 0.08,
        edgeLength: [80, 200],
        friction: 0.6,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 4 },
      },
      categories: props.categories?.map((c, i) => ({
        name: c.name,
        itemStyle: { color: palette[i % palette.length] },
      })),
      data: nodes,
      links: edges,
      label: { show: true, position: 'right', fontSize: 11, color: '#334155' },
    }],
  }, true)
}

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value)
    render()
  }
})

onUnmounted(() => {
  chart?.dispose()
  chart = null
})

watch(() => [props.nodes, props.edges], render, { deep: true })

if (typeof window !== 'undefined') {
  window.addEventListener('resize', () => chart?.resize())
}
</script>
