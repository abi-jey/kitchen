import type { Node } from './components/CanvasGraph'

const MOCK_NODES: Node[] = [
  { id: 'master', label: 'master', x: 400, y: 180, color: '#d9534f' },
  { id: 'worker-1', label: 'worker-1', x: 200, y: 360, color: '#5bc0de' },
  { id: 'worker-2', label: 'worker-2', x: 600, y: 360, color: '#5bc0de' },
]

export async function fetchNodes(): Promise<Node[]> {
  try {
    const res = await fetch('/nodes')
    if (!res.ok) throw new Error('nodes fetch failed')
    const data = await res.json()
    // map API output to UI nodes if shape differs
    return data.map((n: any, i: number) => ({
      id: n.name ?? `node-${i}`,
      label: n.name ?? `node-${i}`,
      x: 200 + i * 120,
      y: 200 + (i % 2) * 100,
      color: '#5bc0de',
    }))
  } catch (e) {
    // Fallback to quick mock data so UI works offline
    return MOCK_NODES
  }
}
