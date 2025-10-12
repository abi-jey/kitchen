import React, { useRef, useEffect, useState, useCallback } from 'react'

export type Node = {
  id: string
  label: string
  x: number
  y: number
  radius?: number
  color?: string
}

export type Edge = {
  from: string
  to: string
}

const DEFAULT_NODE_RADIUS = 28

const mockNodes: Node[] = [
  { id: 'master', label: 'master', x: 400, y: 180, color: '#d9534f' },
  { id: 'worker-1', label: 'worker-1', x: 200, y: 360, color: '#5bc0de' },
  { id: 'worker-2', label: 'worker-2', x: 600, y: 360, color: '#5bc0de' },
  { id: 'db', label: 'db', x: 800, y: 120, color: '#5cb85c' },
  { id: 'ingress', label: 'ingress', x: 80, y: 80, color: '#f0ad4e' },
  { id: 'storage', label: 'storage', x: 1000, y: 420, color: '#6f42c1' },
]

const mockEdges: Edge[] = [
  { from: 'master', to: 'worker-1' },
  { from: 'master', to: 'worker-2' },
  { from: 'master', to: 'db' },
  { from: 'ingress', to: 'master' },
  { from: 'worker-2', to: 'storage' },
]

export type CanvasGraphProps = {
  nodes?: Node[]
  edges?: Edge[]
  initialScale?: number
  enableDrag?: boolean
  enableZoom?: boolean
  onNodeSelect?: (node: Node | null) => void
  onNodeMove?: (node: Node) => void
}

const CanvasGraph: React.FC<CanvasGraphProps> = ({
  nodes: nodesProp,
  edges: edgesProp,
  initialScale = 1,
  enableDrag = true,
  enableZoom = true,
  onNodeSelect,
  onNodeMove,
}: CanvasGraphProps) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const overlayRef = useRef<HTMLDivElement | null>(null)
  const [nodes, setNodes] = useState<Node[]>(nodesProp ?? mockNodes)
  const [edges] = useState<Edge[]>(edgesProp ?? mockEdges)
  const [scale, setScale] = useState(initialScale)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [draggingNode, setDraggingNode] = useState<string | null>(null)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [hoverNode, setHoverNode] = useState<Node | null>(null)
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)

  const getNodeById = useCallback(
    (id: string) => nodes.find((n: Node) => n.id === id),
    [nodes]
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    // Clear
    ctx.clearRect(0, 0, rect.width, rect.height)

    // Apply transform for pan/zoom
    ctx.save()
    ctx.scale(scale, scale)
    ctx.translate(offset.x / scale, offset.y / scale)

    // Draw edges
    ctx.lineWidth = 2 / Math.max(0.2, scale)
    ctx.strokeStyle = '#888'
    edges.forEach((e: Edge) => {
      const a = getNodeById(e.from)
      const b = getNodeById(e.to)
      if (!a || !b) return
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      ctx.stroke()
    })

    // Draw nodes
    nodes.forEach((n: Node) => {
      const r = n.radius ?? DEFAULT_NODE_RADIUS
      ctx.beginPath()
      ctx.fillStyle = n.color ?? '#0366d6'
      ctx.strokeStyle = '#222'
      ctx.lineWidth = 2 / Math.max(0.2, scale)
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()

      // Label
      ctx.fillStyle = '#fff'
      ctx.font = `${12 / Math.max(0.5, scale)}px sans-serif`
      ctx.textAlign = 'center'
      ctx.fillText(n.label, n.x, n.y + 4)
    })

    // Draw selection ring if any
    if (selectedNode) {
      ctx.save()
      ctx.scale(scale, scale)
      ctx.translate(offset.x / scale, offset.y / scale)
      ctx.beginPath()
      ctx.lineWidth = 4 / Math.max(0.2, scale)
      ctx.strokeStyle = 'rgba(255,255,255,0.9)'
      ctx.arc(selectedNode.x, selectedNode.y, (selectedNode.radius ?? DEFAULT_NODE_RADIUS) + 6, 0, Math.PI * 2)
      ctx.stroke()
      ctx.restore()
    }

    ctx.restore()
  }, [nodes, edges, scale, offset, getNodeById])

  // Helpers to transform screen coords to world coords (pre-scale/offset)
  const screenToWorld = useCallback(
    (sx: number, sy: number) => {
      const canvas = canvasRef.current
      if (!canvas) return { x: sx, y: sy }
      const rect = canvas.getBoundingClientRect()
      const x = (sx - rect.left) / scale - offset.x / scale
      const y = (sy - rect.top) / scale - offset.y / scale
      return { x, y }
    },
    [scale, offset]
  )

  const worldToScreen = useCallback(
    (wx: number, wy: number) => {
      const canvas = canvasRef.current
      if (!canvas) return { x: wx, y: wy }
      const rect = canvas.getBoundingClientRect()
      const x = (wx + offset.x / scale) * scale + rect.left
      const y = (wy + offset.y / scale) * scale + rect.top
      return { x, y }
    },
    [scale, offset]
  )

  const findNodeAt = useCallback(
    (x: number, y: number) => {
      // find topmost node under the given world coordinate
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i]
        const r = n.radius ?? DEFAULT_NODE_RADIUS
        const dx = x - n.x
        const dy = y - n.y
        if (dx * dx + dy * dy <= r * r) return n
      }
      return null
    },
    [nodes]
  )

  // Mouse handlers
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

  let panning = false
    let panStart: { x: number; y: number } | null = null

    const onWheel = (ev: WheelEvent) => {
      if (!enableZoom) return
      ev.preventDefault()
      const delta = -ev.deltaY
      const zoomFactor = delta > 0 ? 1.08 : 0.92
      const rect = canvas.getBoundingClientRect()
      const cx = ev.clientX
      const cy = ev.clientY
      const before = screenToWorld(cx, cy)
      setScale((s: number) => {
        const next = Math.max(0.2, Math.min(4, s * zoomFactor))
        // adjust offset so zoom focuses on cursor
        setOffset((off: { x: number; y: number }) => {
          const afterX = (cx - rect.left) / next - before.x
          const afterY = (cy - rect.top) / next - before.y
          return { x: -(afterX * next), y: -(afterY * next) }
        })
        return next
      })
    }

    const onPointerDown = (ev: PointerEvent) => {
      const p = screenToWorld(ev.clientX, ev.clientY)
      const node = findNodeAt(p.x, p.y)
      if (node && enableDrag) {
        setDraggingNode(node.id)
        setDragStart({ x: p.x - node.x, y: p.y - node.y })
      } else {
        panning = true
        panStart = { x: ev.clientX, y: ev.clientY }
      }
      // capture pointer to track leaving canvas
      ;(ev.target as Element).setPointerCapture(ev.pointerId)
    }

    const onPointerMove = (ev: PointerEvent) => {
      const p = screenToWorld(ev.clientX, ev.clientY)
      if (draggingNode && dragStart) {
        setNodes((prev: Node[]) => {
          const next = prev.map((n: Node) =>
            n.id === draggingNode ? { ...n, x: p.x - dragStart.x, y: p.y - dragStart.y } : n
          )
          const moved = next.find((n: Node) => n.id === draggingNode)
          if (moved && onNodeMove) onNodeMove(moved)
          return next
        })
      } else if (panning && panStart) {
        const dx = ev.clientX - panStart.x
        const dy = ev.clientY - panStart.y
  setOffset((off: { x: number; y: number }) => ({ x: off.x + dx, y: off.y + dy }))
        panStart = { x: ev.clientX, y: ev.clientY }
      }

  // Hover detection
      const hover = findNodeAt(p.x, p.y)
      setHoverNode(hover)
      // Position overlay tooltip
      if (overlayRef.current) {
        if (hover) {
          overlayRef.current.style.display = 'block'
          overlayRef.current.style.left = `${ev.clientX + 12}px`
          overlayRef.current.style.top = `${ev.clientY + 12}px`
          overlayRef.current.textContent = `${hover.label} — (${Math.round(hover.x)}, ${Math.round(hover.y)})`
        } else {
          overlayRef.current.style.display = 'none'
        }
      }
    }

    const onPointerUp = (ev: PointerEvent) => {
      const p = screenToWorld(ev.clientX, ev.clientY)
      panning = false
      panStart = null
      if (draggingNode) {
        // if we released after a drag, clear drag state
        setDraggingNode(null)
        setDragStart(null)
      } else {
        // interpret as click/tap — select node if present
        const node = findNodeAt(p.x, p.y)
        setSelectedNode(node)
        if (onNodeSelect) onNodeSelect(node)
      }
      try {
        ;(ev.target as Element).releasePointerCapture(ev.pointerId)
      } catch {}
    }

  canvas.addEventListener('wheel', onWheel, { passive: false })
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointercancel', onPointerUp)

    return () => {
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointercancel', onPointerUp)
    }
  }, [
    draggingNode,
    dragStart,
    screenToWorld,
    findNodeAt,
    enableDrag,
    enableZoom,
    onNodeMove,
  ])

  return (
    <div className="canvas-wrap">
      <canvas ref={canvasRef} className="topology-canvas" />
      <div ref={overlayRef} className="tooltip-overlay" />
    </div>
  )
}

export default CanvasGraph
