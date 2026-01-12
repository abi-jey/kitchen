// Dashboard view component - displays stats and node grid

import React, { useState } from 'react';
import { useDashboard } from '../hooks/useDashboard';
import { Header } from './Header';
import { StatsCards } from './StatsCards';
import { NodeGrid } from './NodeCard';
import { NodeDetailPanel } from './NodeDetailPanel';
import type { NodeWithConnectivity } from '../types';
import { AlertTriangle, Loader } from 'lucide-react';

interface DashboardViewProps {
  isConnected: boolean;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ isConnected }) => {
  const { data, loading, error, lastUpdated, refresh } = useDashboard(30000);
  const [selectedNode, setSelectedNode] = useState<NodeWithConnectivity | null>(null);

  if (loading && !data) {
    return (
      <div className="dashboard-view">
        <div className="loading-screen">
          <Loader size={48} className="spinning" />
          <p>Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="dashboard-view">
        <div className="error-screen">
          <AlertTriangle size={48} />
          <h2>Failed to load dashboard</h2>
          <p>{error}</p>
          <button onClick={refresh}>Retry</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="dashboard-view">
      <Header
        health={data.health}
        lastUpdated={lastUpdated}
        onRefresh={refresh}
        loading={loading}
        isConnected={isConnected}
      />

      <main className="app-main">
        <div className="dashboard-content">
          <section className="stats-section">
            <StatsCards stats={data.stats} health={data.health} />
          </section>

          <section className="nodes-section">
            <div className="section-header">
              <h2>Nodes ({data.nodes.length})</h2>
            </div>
            <NodeGrid
              nodes={data.nodes}
              selectedNode={selectedNode?.name}
              onNodeSelect={setSelectedNode}
            />
          </section>
        </div>

        {selectedNode && (
          <aside className="detail-sidebar">
            <NodeDetailPanel
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
            />
          </aside>
        )}
      </main>
    </div>
  );
};
