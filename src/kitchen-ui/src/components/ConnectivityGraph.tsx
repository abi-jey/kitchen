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
import { Loader, Network, RefreshCw, X, Server, Wifi, Clock, Cpu, HardDrive } from 'lucide-react';
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
  kubelet_version?: string | null;
  cpu_capacity?: string | null;
  memory_capacity?: string | null;
  [key: string]: unknown;
}

// Custom node component showing hostname and IP
const ClusterNode: React.FC<NodeProps<Node<ClusterNodeData>>> = ({ data, selected }) => {
  const statusColor = data.ready
    ? 'var(--success)'
    : data.status !== 'Ready'
      ? 'var(--warning)'
      : 'var(--error)';

  return (
    <div
      className="cluster-node"
      style={{
        background: `linear-gradient(145deg, var(--bg-card) 0%, ${data.ready ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)'} 100%)`,
        border: `2px solid ${selected ? 'var(--accent)' : statusColor}`,
        borderRadius: '12px',
        padding: '14px 18px',
        minWidth: '140px',
        textAlign: 'center',
        boxShadow: selected 
          ? '0 0 0 3px rgba(59, 130, 246, 0.3), var(--shadow-lg)' 
          : 'var(--shadow)',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
      }}
    >
      <Handle type="target" position={Position.Left} id="left" style={{ visibility: 'hidden' }} />
      <Handle type="source" position={Position.Right} id="right" style={{ visibility: 'hidden' }} />
      
      {/* Status indicator */}
      <div style={{
        position: 'absolute',
        top: '8px',
        right: '8px',
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: statusColor,
        boxShadow: `0 0 6px ${statusColor}`,
      }} />
      
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '6px',
        marginBottom: '6px',
      }}>
        <Server size={14} style={{ color: 'var(--text-secondary)' }} />
        <span style={{
          fontWeight: 600,
          fontSize: '14px',
          color: 'var(--text-primary)',
        }}>
          {data.label}
        </span>
      </div>
      
      <div style={{
        fontSize: '11px',
        color: 'var(--text-muted)',
        fontFamily: 'monospace',
        background: 'var(--bg-primary)',
        padding: '4px 8px',
        borderRadius: '4px',
        display: 'inline-block',
      }}>
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

// Selected node type for sidebar
interface SelectedNodeInfo {
  id: string;
  label: string;
  ip: string | null;
  ready: boolean;
  status: string;
  kubelet_version?: string | null;
  cpu_capacity?: string | null;
  memory_capacity?: string | null;
}

export const ConnectivityGraphView: React.FC<ConnectivityGraphViewProps> = ({
  refreshInterval = 30000,
}) => {
  const [graphData, setGraphData] = useState<ConnectivityGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  // Close sidebar on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedNode) {
        setSelectedNode(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedNode]);

  // Handle node click
  const onNodeClick = useCallback((_: React.MouseEvent, node: FlowNode) => {
    const apiNode = graphData?.nodes.find((n) => n.id === node.id);
    if (apiNode) {
      setSelectedNode({
        id: apiNode.id,
        label: apiNode.label,
        ip: apiNode.ip,
        ready: apiNode.ready,
        status: apiNode.status,
        kubelet_version: apiNode.kubelet_version,
        cpu_capacity: apiNode.cpu_capacity,
        memory_capacity: apiNode.memory_capacity,
      });
    }
  }, [graphData]);

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
          onNodeClick={onNodeClick}
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

      {/* Node Detail Sidebar - Generated by Copilot */}
      {selectedNode && (
        <div className="node-sidebar">
          <div className="sidebar-header">
            <div className="sidebar-title">
              <Server size={20} />
              <span>{selectedNode.label}</span>
            </div>
            <button className="sidebar-close" onClick={() => setSelectedNode(null)}>
              <X size={20} />
            </button>
          </div>
          <div className="sidebar-content">
            <div className="sidebar-section">
              <h4>Connection</h4>
              <div className="sidebar-field">
                <span className="field-label">IP Address</span>
                <span className="field-value">{selectedNode.ip}</span>
              </div>
              <div className="sidebar-field">
                <span className="field-label">Status</span>
                <span className={`field-value status-badge ${selectedNode.status}`}>
                  {selectedNode.status === 'healthy' ? 'Healthy' : 
                   selectedNode.status === 'degraded' ? 'Degraded' : 'Unhealthy'}
                </span>
              </div>
            </div>
            
            {selectedNode.kubelet_version && (
              <div className="sidebar-section">
                <h4>Kubernetes</h4>
                <div className="sidebar-field">
                  <span className="field-label">Kubelet Version</span>
                  <span className="field-value">{selectedNode.kubelet_version}</span>
                </div>
              </div>
            )}
            
            {(selectedNode.cpu_capacity || selectedNode.memory_capacity) && (
              <div className="sidebar-section">
                <h4>Resources</h4>
                {selectedNode.cpu_capacity && (
                  <div className="sidebar-field">
                    <Cpu size={14} />
                    <span className="field-label">CPU</span>
                    <span className="field-value">{selectedNode.cpu_capacity}</span>
                  </div>
                )}
                {selectedNode.memory_capacity && (
                  <div className="sidebar-field">
                    <HardDrive size={14} />
                    <span className="field-label">Memory</span>
                    <span className="field-value">{selectedNode.memory_capacity}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

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
