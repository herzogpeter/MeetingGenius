import { useMemo } from 'react'
import { Rnd } from 'react-rnd'
import type { MindmapAction, MindmapNode, MindmapPoint, MindmapState } from '../contracts'

const NODE_W = 240
const NODE_H = 62

type NodeRect = { x: number; y: number; w: number; h: number }

function fallbackPos(depth: number, index: number): MindmapPoint {
  const x = 40 + depth * 320
  const y = 40 + index * 86
  return { x, y }
}

function rectForPos(pos: MindmapPoint): NodeRect {
  return { x: pos.x, y: pos.y, w: NODE_W, h: NODE_H }
}

function overlapArea(a: NodeRect, b: NodeRect): number {
  const xOverlap = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x))
  const yOverlap = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y))
  return xOverlap * yOverlap
}

function findOverlapTarget(
  nodes: MindmapNode[],
  positions: Record<string, MindmapPoint>,
  dropRect: NodeRect,
  excludeId: string
): string | null {
  let bestId: string | null = null
  let bestArea = 0
  for (const node of nodes) {
    if (node.node_id === excludeId) continue
    const pos = positions[node.node_id]
    if (!pos) continue
    const area = overlapArea(dropRect, rectForPos(pos))
    if (area > bestArea) {
      bestArea = area
      bestId = node.node_id
    }
  }
  return bestArea > 0 ? bestId : null
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
                  const nextPos = { x: data.x, y: data.y }
                  props.sendClientMindmapAction({
                    type: 'set_node_pos',
                    node_id: node.node_id,
                    pos: nextPos,
                  })
                  if (node.node_id === props.mindmapState.root_id) return
                  const targetId = findOverlapTarget(nodes, positions, rectForPos(nextPos), node.node_id)
                  if (!targetId || targetId === node.parent_id) return
                  props.sendClientMindmapAction({
                    type: 'reparent_node',
                    node_id: node.node_id,
                    new_parent_id: targetId,
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
                    <button
                      className="mgIconButton"
                      title="Delete subtree"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation()
                        const label =
                          node.node_id === props.mindmapState.root_id
                            ? 'Delete entire mindmap?'
                            : 'Delete this node and all children?'
                        if (!window.confirm(label)) return
                        props.sendClientMindmapAction({ type: 'delete_subtree', node_id: node.node_id })
                      }}
                    >
                      Delete
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
