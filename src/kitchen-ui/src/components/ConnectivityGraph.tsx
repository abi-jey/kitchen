// Connectivity Graph visualization using React Flow

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Handle,
  Position,
  NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Loader, Network, RefreshCw } from 'lucide-react';
import { getConnectivityGraph } from '../api/client';
import type { ConnectivityGraph, GraphNode as ApiGraphNode } from '../types';
import { formatLatency } from '../types';

// Node data type for React Flow
interface ClusterNodeData {
  type: 'hub' | 'node';
  label: string;
  ip: string | null;
  ready: boolean;
  status: string;
  [key: string]: unknown;
}

// Custom node component showing hostname and IP
const ClusterNode: React.FC<NodeProps<Node<ClusterNodeData>>> = ({ data }) => {
  const isHub = data.type === 'hub';
  const statusColor = isHub
    ? 'var(--accent)'
    : data.ready
      ? 'var(--success)'
      : data.status !== 'Ready'
        ? 'var(--warning)'
        : 'var(--error)';

  return (
    <div
      className="cluster-node"
      style={{
        background: 'var(--bg-card)',
        border: `2px solid ${statusColor}`,
        borderRadius: isHub ? '12px' : '8px',
        padding: isHub ? '16px 20px' : '12px 16px',
        minWidth: isHub ? '140px' : '120px',
        textAlign: 'center',
        boxShadow: 'var(--shadow)',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div
        style={{
          fontWeight: 600,
          fontSize: isHub ? '14px' : '13px',
          color: 'var(--text-primary)',
          marginBottom: '4px',
        }}
      >
        {data.label}
      </div>
      <div
        style={{
          fontSize: '11px',
          color: 'var(--text-muted)',
          fontFamily: 'monospace',
        }}
      >
        {isHub ? 'Hub' : data.ip || 'No IP'}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  );
};

const nodeTypes = { cluster: ClusterNode };

type FlowNode = Node<ClusterNodeData>;
type FlowEdge = Edge;

interface ConnectivityGraphViewProps {
  refreshInterval?: number;
}

export const ConnectivityGraphView: React.FC<ConnectivityGraphViewProps> = ({
  refreshInterval = 30000,
}) => {
  const [graphData, setGraphData] = useState<ConnectivityGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  const fetchGraph = useCallback(async () => {
    try {
      const data = await getConnectivityGraph();
      setGraphData(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGraph();
    const interval = setInterval(fetchGraph, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchGraph, refreshInterval]);

  // Convert API data to React Flow nodes and edges
  useEffect(() => {
    if (!graphData) return;

    const hubNode = graphData.nodes.find((n) => n.type === 'hub');
    const otherNodes = graphData.nodes.filter((n) => n.type !== 'hub');

    const centerX = 400;
    const centerY = 300;
    const radius = Math.max(200, 100 + otherNodes.length * 40);

    const flowNodes: FlowNode[] = [];

    // Hub in center
    if (hubNode) {
      flowNodes.push({
        id: hubNode.id,
        type: 'cluster',
        position: { x: centerX - 70, y: centerY - 30 },
        data: {
          type: hubNode.type,
          label: hubNode.label,
          ip: hubNode.ip,
          ready: hubNode.ready,
          status: hubNode.status,
        },
      });
    }

    // Other nodes in a circle
    otherNodes.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / otherNodes.length - Math.PI / 2;
      flowNodes.push({
        id: node.id,
        type: 'cluster',
        position: {
          x: centerX + radius * Math.cos(angle) - 60,
          y: centerY + radius * Math.sin(angle) - 25,
        },
        data: {
          type: node.type,
          label: node.label,
          ip: node.ip,
          ready: node.ready,
          status: node.status,
        },
      });
    });

    // Create edges
    const flowEdges: FlowEdge[] = graphData.edges.map((edge) => {
      const isSuccess = edge.success;
      const hasMeasurement = edge.measured_at !== null;

      return {
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: 'default',
        animated: !isSuccess && hasMeasurement,
        style: {
          stroke: !hasMeasurement
            ? 'var(--text-muted)'
            : isSuccess
              ? 'var(--success)'
              : 'var(--error)',
          strokeWidth: 2,
          strokeDasharray: !hasMeasurement ? '4 4' : isSuccess ? undefined : '6 3',
        },
        label: hasMeasurement
          ? isSuccess
            ? formatLatency(edge.latency_ms)
            : 'Failed'
          : undefined,
        labelStyle: {
          fontSize: 10,
          fontWeight: 500,
          fill: !hasMeasurement
            ? 'var(--text-muted)'
            : isSuccess
              ? 'var(--success)'
              : 'var(--error)',
        },
        labelBgStyle: {
          fill: 'var(--bg-secondary)',
          fillOpacity: 0.9,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: !hasMeasurement
            ? 'var(--text-muted)'
            : isSuccess
              ? 'var(--success)'
              : 'var(--error)',
          width: 15,
          height: 15,
        },
      };
    });

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [graphData, setNodes, setEdges]);

  // Calculate stats
  const stats = useMemo(() => {
    if (!graphData) return null;

    const successEdges = graphData.edges.filter((e) => e.success);
    const failedEdges = graphData.edges.filter(
      (e) => !e.success && e.measured_at
    );
    const avgLatency =
      successEdges.length > 0
        ? successEdges.reduce((sum, e) => sum + (e.latency_ms || 0), 0) /
          successEdges.length
        : null;

    return {
      totalNodes: graphData.nodes.length,
      totalEdges: graphData.edges.length,
      successCount: successEdges.length,
      failedCount: failedEdges.length,
      avgLatency,
    };
  }, [graphData]);

  if (loading && !graphData) {
    return (
      <div className="graph-container">
        <div className="graph-loading">
          <Loader size={48} className="spinning" />
          <p>Loading connectivity graph...</p>
        </div>
      </div>
    );
  }

  if (error && !graphData) {
    return (
      <div className="graph-container">
        <div className="graph-empty">
          <Network size={64} />
          <p>Failed to load graph: {error}</p>
          <button onClick={fetchGraph}>Retry</button>
        </div>
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="graph-container">
        <div className="graph-empty">
          <Network size={64} />
          <p>No nodes available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="graph-container">
      <div className="graph-header">
        <h2>Node Connectivity</h2>
        <div className="graph-legend">
          <div className="legend-item">
            <span className="legend-dot hub" />
            <span>Hub</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot healthy" />
            <span>Healthy</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot degraded" />
            <span>Degraded</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot unreachable" />
            <span>Unreachable</span>
          </div>
          <button
            onClick={fetchGraph}
            className="refresh-btn"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      <div className="graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--border)" gap={20} size={1} />
          <Controls
            showInteractive={false}
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
            }}
          />
          <MiniMap
            nodeColor={(node) => {
              if (node.data.type === 'hub') return 'var(--accent)';
              if (!node.data.ready) return 'var(--error)';
              if (node.data.status !== 'Ready') return 'var(--warning)';
              return 'var(--success)';
            }}
            maskColor="rgba(0, 0, 0, 0.7)"
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
            }}
          />
        </ReactFlow>
      </div>

      {stats && (
        <div className="graph-stats">
          <div className="stat-item">
            <span className="stat-label">Nodes:</span>
            <span className="stat-value">{stats.totalNodes}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Connections:</span>
            <span className="stat-value">{stats.totalEdges}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Successful:</span>
            <span className="stat-value success">{stats.successCount}</span>
          </div>
          {stats.failedCount > 0 && (
            <div className="stat-item">
              <span className="stat-label">Failed:</span>
              <span className="stat-value error">{stats.failedCount}</span>
            </div>
          )}
          {stats.avgLatency !== null && (
            <div className="stat-item">
              <span className="stat-label">Avg Latency:</span>
              <span className="stat-value">{formatLatency(stats.avgLatency)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
