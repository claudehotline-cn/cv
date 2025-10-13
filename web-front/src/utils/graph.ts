export type GraphNode = { id: string; name: string; type: string; params?: Record<string, any>; position?: { x: number, y: number } }
export type GraphEdge = { source: string; target: string }
export type GraphJson = { nodes: GraphNode[]; edges: GraphEdge[] }

export type GraphValidateResult = {
  ok: boolean
  errors: string[]
  nodeErrors: Record<string, string[]>
}

const allowedNext: Record<string, string[]> = {
  source: ['preprocess', 'model', 'nms', 'overlay', 'sink'],
  preprocess: ['preprocess', 'model', 'nms', 'overlay', 'sink'],
  model: ['nms', 'overlay', 'sink'],
  nms: ['overlay', 'sink'],
  overlay: ['sink'],
  sink: []
}

function pushNodeErr(map: Record<string, string[]>, id: string, msg: string) {
  (map[id] = map[id] || []).push(msg)
}

export function validateGraph(g: GraphJson): GraphValidateResult {
  const errors: string[] = []
  const nodeErrors: Record<string, string[]> = {}
  if (!g || !Array.isArray(g.nodes) || g.nodes.length === 0) errors.push('Empty graph / no nodes')
  const idSet = new Set(g.nodes?.map(n => n.id))
  const sources = g.nodes?.filter(n => n.type === 'source') || []
  const sinks = g.nodes?.filter(n => n.type === 'sink') || []
  if (sources.length === 0) errors.push('Missing source node')
  if (sinks.length === 0) errors.push('Missing sink node')
  for (const e of (g.edges || [])) {
    if (!idSet.has(e.source) || !idSet.has(e.target)) errors.push(`Invalid edge: ${e.source} -> ${e.target}`)
  }
  // Degree checks and allowed transitions
  const indeg: Record<string, number> = {}
  const outdeg: Record<string, number> = {}
  g.nodes?.forEach(n => { indeg[n.id] = 0; outdeg[n.id] = 0 })
  for (const e of (g.edges || [])) { indeg[e.target]++; outdeg[e.source]++ }
  for (const n of (g.nodes || [])) {
    const t = n.type
    if (t === 'source') {
      if (indeg[n.id] > 0) pushNodeErr(nodeErrors, n.id, 'Source must not have incoming edges')
      if (outdeg[n.id] === 0) pushNodeErr(nodeErrors, n.id, 'Source should have outgoing edge')
    } else if (t === 'sink') {
      if (outdeg[n.id] > 0) pushNodeErr(nodeErrors, n.id, 'Sink must not have outgoing edges')
      if (indeg[n.id] === 0) pushNodeErr(nodeErrors, n.id, 'Sink should have incoming edge')
    } else {
      if (indeg[n.id] === 0) pushNodeErr(nodeErrors, n.id, 'Node should have incoming edge')
      if (outdeg[n.id] === 0) pushNodeErr(nodeErrors, n.id, 'Node should have outgoing edge')
    }
  }
  // Allowed next types
  const typeById = new Map(g.nodes.map(n => [n.id, n.type]))
  for (const e of (g.edges || [])) {
    const from = typeById.get(e.source) || ''
    const to = typeById.get(e.target) || ''
    const allow = allowedNext[from] || []
    if (!allow.includes(to)) {
      pushNodeErr(nodeErrors, e.source, `Edge to disallowed type: ${from} -> ${to}`)
    }
  }
  // Cycle check (Kahn)
  const indeg2: Record<string, number> = {}
  g.nodes?.forEach(n => indeg2[n.id] = 0)
  g.edges?.forEach(e => indeg2[e.target] = (indeg2[e.target] || 0) + 1)
  const q: string[] = Object.keys(indeg2).filter(id => indeg2[id] === 0)
  let visited = 0
  const adj = new Map<string, string[]>()
  g.edges?.forEach(e => { const arr = adj.get(e.source) || []; arr.push(e.target); adj.set(e.source, arr) })
  while (q.length) { const u = q.shift()!; visited++; for (const v of (adj.get(u) || [])) { indeg2[v]--; if (indeg2[v] === 0) q.push(v) } }
  if (visited !== (g.nodes?.length || 0)) errors.push('Cycle detected / invalid topology')

  // Params validation
  for (const n of (g.nodes || [])) {
    if (n.type === 'source') {
      const uri = n.params?.uri
      if (!uri || !/^(rtsp|rtmp|http|https):\/\//i.test(uri)) pushNodeErr(nodeErrors, n.id, 'Invalid or missing source.uri')
    }
    if (n.type === 'model') {
      if (!n.params?.modelUri) pushNodeErr(nodeErrors, n.id, 'Missing model.modelUri')
    }
    if (n.type === 'nms') {
      const iou = Number(n.params?.iou); const conf = Number(n.params?.conf)
      if (isNaN(iou) || iou < 0 || iou > 1) pushNodeErr(nodeErrors, n.id, 'nms.iou must be 0..1')
      if (isNaN(conf) || conf < 0 || conf > 1) pushNodeErr(nodeErrors, n.id, 'nms.conf must be 0..1')
    }
    if (n.type === 'overlay') {
      const t = Number(n.params?.thickness)
      if (!isFinite(t) || t < 0 || t > 6) pushNodeErr(nodeErrors, n.id, 'overlay.thickness must be 0..6')
    }
  }
  const ok = errors.length === 0 && Object.keys(nodeErrors).length === 0
  return { ok, errors, nodeErrors }
}

export function toDagSpec(g: GraphJson, name = 'pipeline-from-ui') {
  // 基于拓扑排序的节点线性展开，同时保留类型与参数；源使用 source_ref 表达
  const indeg: Record<string, number> = {}
  g.nodes?.forEach(n => indeg[n.id] = 0)
  g.edges?.forEach(e => indeg[e.target] = (indeg[e.target] || 0) + 1)
  const q: string[] = Object.keys(indeg).filter(id => indeg[id] === 0)
  const adj = new Map<string, string[]>()
  g.edges?.forEach(e => { const arr = adj.get(e.source) || []; arr.push(e.target); adj.set(e.source, arr) })
  const order: string[] = []
  while (q.length) {
    const u = q.shift()!
    order.push(u)
    for (const v of (adj.get(u) || [])) { if (--indeg[v] === 0) q.push(v) }
  }
  const id2node = new Map(g.nodes.map(n => [n.id, n]))
  const nodes = order.map(id => id2node.get(id)!).filter(Boolean)
  const source = nodes.find(n => n.type === 'source')
  return {
    name,
    source_ref: source?.params?.uri || '',
    nodes: nodes.filter(n => n.type !== 'source').map(n => ({ name: n.name, type: n.type, params: n.params || {} }))
  }
}

export function toLinearSpec(g: GraphJson, name = 'pipeline-from-ui') {
  // 忽略 edges 的简单顺序（按 nodes 顺序），源节点提取为 source_ref
  const source = g.nodes.find(n => n.type === 'source')
  const rest = g.nodes.filter(n => n.type !== 'source')
  return {
    name,
    source_ref: source?.params?.uri || '',
    nodes: rest.map(n => ({ name: n.name, type: n.type, params: n.params || {} }))
  }
}
