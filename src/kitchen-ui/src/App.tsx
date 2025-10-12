import React from 'react'
import CanvasGraph, { type Node } from './components/CanvasGraph'
import { fetchNodes } from './api'
import { useEffect, useState } from 'react'

const App: React.FC = () => {
  const [nodes, setNodes] = useState<Node[] | undefined>(undefined)
  const [selected, setSelected] = useState<Node | null>(null)

  useEffect(() => {
    let mounted = true
    fetchNodes().then((n) => {
      if (mounted) setNodes(n as Node[])
    })
    return () => {
      mounted = false
    }
  }, [])

  return (
    <div className="app-root">
      <header className="app-header">
        <h1>Kitchen — Node Manager UI</h1>
      </header>
      <main className="app-main">
        <section className="viz-panel">
          <CanvasGraph
            nodes={nodes}
            onNodeSelect={(n) => setSelected(n)}
            onNodeMove={(n) => {
              setNodes((prev) => (prev ? prev.map((p) => (p.id === n.id ? n : p)) : prev))
            }}
          />
        </section>
        <aside className="side-panel">
          <div className="panel-section">
            <h2>Quick Info</h2>
            <p>Nodes: <strong>{nodes ? nodes.length : 'loading...'}</strong></p>
            <p>Clusters: <strong>mock: 1</strong></p>
          </div>
          <div className="panel-section">
            <h3>Controls</h3>
            <p>Drag or click nodes, hover to see tooltips, use mouse wheel to zoom.</p>
          </div>
          <div className="panel-section">
            <h3>Selected</h3>
            {selected ? (
              <div>
                <p><strong>{selected.label}</strong></p>
                <p>Pos: {Math.round(selected.x)},{Math.round(selected.y)}</p>
              </div>
            ) : (
              <p>No node selected</p>
            )}
          </div>
        </aside>
      </main>
      <footer className="app-footer">Kitchen UI — Experimental</footer>
    </div>
  )
}

export default App
