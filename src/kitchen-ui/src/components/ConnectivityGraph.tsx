// Connectivity Graph visualization using React Flow

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
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
  const statusColor = data.ready
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
        borderRadius: '8px',
        padding: '12px 16px',
        minWidth: '120px',
        textAlign: 'center',
        boxShadow: 'var(--shadow)',
      }}
    >
      {/* Left side handles for incoming */}
      <Handle type="target" position={Position.Left} id="left" style={{ visibility: 'hidden' }} />
      {/* Right side handles for outgoing */}
      <Handle type="source" position={Position.Right} id="right" style={{ visibility: 'hidden' }} />
      <div
        style={{
          fontWeight: 600,
          fontSize: '13px',
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
        {data.ip || 'No IP'}
      </div>
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

    // Only show actual cluster nodes, not the hub
    const clusterNodes = graphData.nodes.filter((n) => n.type !== 'hub');

    const centerX = 400;
    const centerY = 300;
    const radius = Math.max(180, 80 + clusterNodes.length * 50);

    const flowNodes: FlowNode[] = [];

    // Position nodes in a circle (or line if only 2)
    clusterNodes.forEach((node, index) => {
      let x, y;
      if (clusterNodes.length === 1) {
        x = centerX - 60;
        y = centerY - 25;
      } else if (clusterNodes.length === 2) {
        // Two nodes: place them horizontally
        x = centerX + (index === 0 ? -radius / 2 : radius / 2) - 60;
        y = centerY - 25;
      } else {
        // Multiple nodes: circular layout
        const angle = (2 * Math.PI * index) / clusterNodes.length - Math.PI / 2;
        x = centerX + radius * Math.cos(angle) - 60;
        y = centerY + radius * Math.sin(angle) - 25;
      }
      flowNodes.push({
        id: node.id,
        type: 'cluster',
        position: { x, y },
        data: {
          type: node.type,
          label: node.label,
          ip: node.ip,
          ready: node.ready,
          status: node.status,
        },
      });
    });

    // Only show edges between actual nodes (filter out hub edges)
    const filteredEdges = graphData.edges
      .filter((edge) => edge.source !== 'node-manager' && edge.target !== 'node-manager');
    
    // Create parallel edges for bidirectional connections
    const flowEdges: FlowEdge[] = filteredEdges.map((edge, index) => {
      const isSuccess = edge.success;
      const hasMeasurement = edge.measured_at !== null;
      
      // Check if there's a reverse edge (bidirectional)
      const hasReverseEdge = filteredEdges.some(
        (e) => e.source === edge.target && e.target === edge.source
      );
      
      // Determine if this edge should use top or bottom offset
      const isFirstDirection = edge.source < edge.target;

      return {
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        sourceHandle: 'right',
        targetHandle: 'left',
        type: 'straight',
        animated: !isSuccess && hasMeasurement,
        style: {
          stroke: !hasMeasurement
            ? 'var(--text-muted)'
            : isSuccess
              ? 'var(--success)'
              : 'var(--error)',
          strokeWidth: 2,
          strokeDasharray: !hasMeasurement ? '4 4' : isSuccess ? undefined : '6 3',
          // Offset for parallel lines
          ...(hasReverseEdge && {
            transform: isFirstDirection ? 'translateY(-8px)' : 'translateY(8px)',
          }),
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
          width: 12,
          height: 12,
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
