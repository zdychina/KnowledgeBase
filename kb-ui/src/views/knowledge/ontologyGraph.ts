// kb-ui/src/views/knowledge/ontologyGraph.ts
// 本体图谱的图数据构造：把 active 本体 + 待审候选转成节点/边。
// 本体的边是人写的（relation_types.allowed_pairs），不是算出来的——这里只做展开，不做任何重算。
import type { ActiveOntology, OntologyCandidate, OntologyNodeType, OntologyRelationType } from '@/types'

export interface OntoGraphNode {
  id: string            // = 类型名（allowed_pairs 里 head/tail 引用的就是类型名）
  name: string
  layer: string         // concept / instance / property
  isStrong: boolean
  isCandidate: boolean  // true=待审候选（橙色虚线）
  definition: string
  examples: string[]
}

export interface OntoGraphEdge {
  id: string            // 关系名 + head->tail，保证多对 head/tail 不撞 id
  source: string        // head 类型名
  target: string        // tail 类型名
  relationName: string
  isDirected: boolean
  isCandidate: boolean
  inverseName: string
  definition: string
}

export interface OntoGraphData {
  nodes: OntoGraphNode[]
  edges: OntoGraphEdge[]
}

export function parseExamples(raw: unknown): string[] {
  let ex: unknown = raw
  if (typeof ex === 'string') {
    try { ex = JSON.parse(ex) } catch { ex = [] }
  }
  return Array.isArray(ex) ? ex.map(String).slice(0, 8) : []
}

export function buildOntologyGraph(
  active: Pick<ActiveOntology, 'node_types' | 'relation_types'>,
  candidates: OntologyCandidate[] = [],
  showCandidates = false,
): OntoGraphData {
  const nodes: OntoGraphNode[] = []
  const nodeIds = new Set<string>()

  // 1) active 节点类型 → 节点
  for (const n of active.node_types) {
    nodes.push({
      id: n.name,
      name: n.name,
      layer: n.layer || 'concept',
      isStrong: !!n.is_strong,
      isCandidate: false,
      definition: n.definition || '',
      examples: parseExamples(n.examples_json),
    })
    nodeIds.add(n.name)
  }

  // 2) active 关系类型 → 边（一个关系多对 head/tail = 多条同名边）
  const edges: OntoGraphEdge[] = []
  for (const r of active.relation_types) {
    const pairs = Array.isArray(r.allowed_pairs_json) ? r.allowed_pairs_json : []
    for (const p of pairs) {
      if (!p?.head || !p?.tail) continue
      edges.push({
        id: `${r.name}:${p.head}->${p.tail}`,
        source: p.head,
        target: p.tail,
        relationName: r.name,
        isDirected: r.is_directed !== false,
        isCandidate: false,
        inverseName: r.inverse_name || '',
        definition: r.definition || '',
      })
    }
  }

  if (!showCandidates) return { nodes, edges }

  // 3) 候选叠加：node_type 候选先进（橙虚线节点），relation_type 候选后进（橙虚线边）
  const proposed = candidates.filter(c => c.status === 'proposed')
  for (const c of proposed) {
    if (c.kind !== 'node_type') continue
    if (nodeIds.has(c.proposed_name)) continue // 已是 active 节点，不重复
    nodes.push({
      id: c.proposed_name,
      name: c.proposed_name,
      layer: c.layer || 'concept',
      isStrong: false,
      isCandidate: true,
      definition: '',
      examples: [],
    })
    nodeIds.add(c.proposed_name)
  }
  for (const c of proposed) {
    if (c.kind !== 'relation_type') continue
    const head = c.payload_json?.head_type as string | undefined
    const tail = c.payload_json?.tail_type as string | undefined
    if (!head || !tail) continue
    if (!nodeIds.has(head) || !nodeIds.has(tail)) continue // 端点类型不在图里，跳过
    edges.push({
      id: `cand:${c.id}`,
      source: head,
      target: tail,
      relationName: c.proposed_name,
      isDirected: true,
      isCandidate: true,
      inverseName: '',
      definition: '',
    })
  }

  return { nodes, edges }
}

// ── 本地可编辑模型 + 增删纯函数（编辑器用）──
// 约定：所有函数都返回"新模型"（浅拷贝顶层 + 拷贝被改的数组），不修改入参，
// 便于单测断言与 Vue 重新渲染。校验（重名/端点存在性）放在调用方（View）里做，这里只做变换。

export interface EditableOntology {
  node_types: OntologyNodeType[]
  relation_types: OntologyRelationType[]
}

export function cloneModel(m: EditableOntology): EditableOntology {
  return {
    node_types: m.node_types.map(n => ({ ...n })),
    relation_types: m.relation_types.map(r => ({
      ...r,
      allowed_pairs_json: (r.allowed_pairs_json || []).map(p => ({ ...p })),
    })),
  }
}

export interface NewNodeInput {
  name: string
  layer: string
  isStrong: boolean
  definition?: string
}

/** 新建节点类型。id 留空字符串（后端 add_node_type 会生成正式 id，保存时忽略本地 id）。 */
export function addNode(model: EditableOntology, input: NewNodeInput): EditableOntology {
  const next = cloneModel(model)
  next.node_types.push({
    id: '',
    name: input.name,
    layer: input.layer || 'concept',
    is_strong: !!input.isStrong,
    definition: input.definition || null,
    examples_json: [],
  })
  return next
}

/** 删除节点类型，并连带删除所有边类型里以它为 head 或 tail 的 pair。 */
export function removeNode(model: EditableOntology, name: string): EditableOntology {
  const next = cloneModel(model)
  next.node_types = next.node_types.filter(n => n.name !== name)
  next.relation_types = next.relation_types.map(r => ({
    ...r,
    allowed_pairs_json: (r.allowed_pairs_json || []).filter(
      p => p.head !== name && p.tail !== name,
    ),
  }))
  return next
}

export interface NewRelationTypeInput {
  name: string
  isDirected: boolean
  inverseName?: string
  definition?: string
}

/** 新建关系类型（空 allowed_pairs，建完后可通过 addEdge 往里加边）。 */
export function addRelationType(model: EditableOntology, input: NewRelationTypeInput): EditableOntology {
  const next = cloneModel(model)
  next.relation_types.push({
    id: '',
    name: input.name,
    layer: 'concept',
    is_directed: !!input.isDirected,
    inverse_name: input.inverseName || null,
    allowed_pairs_json: [],
    definition: input.definition || null,
  })
  return next
}

/** 给某个已存在的关系类型加一条边（head→tail 的 pair）。已存在同 pair 则原样返回。 */
export function addEdge(
  model: EditableOntology, relationName: string, head: string, tail: string,
): EditableOntology {
  const next = cloneModel(model)
  const rel = next.relation_types.find(r => r.name === relationName)
  if (!rel) return next
  const pairs = rel.allowed_pairs_json || (rel.allowed_pairs_json = [])
  if (pairs.some(p => p.head === head && p.tail === tail)) return next
  pairs.push({ head, tail })
  return next
}

/** 删除一条边（关系类型 relationName 下 head→tail 的 pair）。参数与 addEdge 对称。 */
export function removeEdge(
  model: EditableOntology, relationName: string, head: string, tail: string,
): EditableOntology {
  const next = cloneModel(model)
  const rel = next.relation_types.find(r => r.name === relationName)
  if (!rel) return next
  rel.allowed_pairs_json = (rel.allowed_pairs_json || []).filter(
    p => !(p.head === head && p.tail === tail),
  )
  return next
}
