import { useMemo } from 'react'
import { Rnd } from 'react-rnd'
import type { MindmapAction, MindmapNode, MindmapPoint, MindmapState } from '../contracts'

const NODE_W = 240
const NODE_H = 62

function fallbackPos(depth: number, index: number): MindmapPoint {
  const x = 40 + depth * 320
  const y = 40 + index * 86
  return { x, y }
}

function computeDepth(state: MindmapState, nodeId: string): number {
  let depth = 0
  let cur = state.nodes[nodeId]
  const guard = 50
  let steps = 0
  while (cur?.parent_id && steps < guard) {
    depth += 1
    cur = state.nodes[cur.parent_id]
    steps += 1
  }
  return depth
}

function visibleSubtree(state: MindmapState): { nodes: MindmapNode[]; edges: Array<{ from: string; to: string }> } {
  const rootId = state.root_id
  if (!state.nodes[rootId]) return { nodes: [], edges: [] }

  const childrenByParent: Record<string, string[]> = {}
  for (const node of Object.values(state.nodes)) {
    if (!node.parent_id) continue
    if (!childrenByParent[node.parent_id]) childrenByParent[node.parent_id] = []
    childrenByParent[node.parent_id].push(node.node_id)
  }
  for (const parentId of Object.keys(childrenByParent)) {
    childrenByParent[parentId].sort()
  }

  const visibleIds = new Set<string>()
  const edges: Array<{ from: string; to: string }> = []
  const queue: string[] = [rootId]

  while (queue.length) {
    const currentId = queue.shift()!
    const node = state.nodes[currentId]
    if (!node) continue
    visibleIds.add(currentId)

    const children = childrenByParent[currentId] ?? []
    if (node.collapsed) continue
    for (const childId of children) {
      edges.push({ from: currentId, to: childId })
      queue.push(childId)
    }
  }

  const nodes = Object.values(state.nodes).filter((n) => visibleIds.has(n.node_id))
  return { nodes, edges }
}

export function Mindmap(props: {
  mindmapState: MindmapState
  sendClientMindmapAction: (action: MindmapAction) => void
}) {
  const { nodes, edges } = useMemo(() => visibleSubtree(props.mindmapState), [props.mindmapState])

  const positions = useMemo(() => {
    const map: Record<string, MindmapPoint> = {}
    const sorted = nodes.slice().sort((a, b) => a.node_id.localeCompare(b.node_id))
    for (let i = 0; i < sorted.length; i++) {
      const n = sorted[i]
      const pos = props.mindmapState.layout[n.node_id]
      map[n.node_id] = pos ?? fallbackPos(computeDepth(props.mindmapState, n.node_id), i)
    }
    return map
  }, [nodes, props.mindmapState])

  return (
    <div className="mgMindmap">
      <div className="mgPanelTitle">Mindmap</div>

      <div className="mgMindmapCanvas">
        <div className="mgMindmapInner">
          <svg className="mgMindmapEdges" width="2000" height="1400">
            {edges.map((e) => {
              const a = positions[e.from]
              const b = positions[e.to]
              if (!a || !b) return null
              const x1 = a.x + NODE_W / 2
              const y1 = a.y + NODE_H / 2
              const x2 = b.x + NODE_W / 2
              const y2 = b.y + NODE_H / 2
              return (
                <line
                  key={`${e.from}->${e.to}`}
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="rgba(15,23,42,0.22)"
                  strokeWidth={2}
                />
              )
            })}
          </svg>

          {nodes.map((node) => {
            const pos = positions[node.node_id]
            if (!pos) return null
            return (
              <Rnd
                key={node.node_id}
                bounds="parent"
                enableResizing={false}
                size={{ width: NODE_W, height: NODE_H }}
                position={{ x: pos.x, y: pos.y }}
                onDragStop={(_, data) => {
                  props.sendClientMindmapAction({
                    type: 'set_node_pos',
                    node_id: node.node_id,
                    pos: { x: data.x, y: data.y },
                  })
                }}
              >
                <div className={`mgMindmapNode ${node.collapsed ? 'mgMindmapNode--collapsed' : ''}`}>
                  <div className="mgMindmapNodeText" title={node.text}>
                    {node.text}
                  </div>
                  <div className="mgMindmapNodeActions">
                    <button
                      className="mgIconButton"
                      title={node.collapsed ? 'Expand' : 'Collapse'}
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation()
                        props.sendClientMindmapAction({
                          type: 'set_collapsed',
                          node_id: node.node_id,
                          collapsed: !node.collapsed,
                        })
                      }}
                    >
                      {node.collapsed ? 'Expand' : 'Collapse'}
                    </button>
                    <button
                      className="mgIconButton"
                      title="Rename"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation()
                        const next = window.prompt('Rename node', node.text)
                        if (!next) return
                        const trimmed = next.trim()
                        if (!trimmed || trimmed === node.text) return
                        props.sendClientMindmapAction({ type: 'rename_node', node_id: node.node_id, text: trimmed })
                      }}
                    >
                      Rename
                    </button>
                  </div>
                </div>
              </Rnd>
            )
          })}
        </div>
      </div>
    </div>
  )
}

