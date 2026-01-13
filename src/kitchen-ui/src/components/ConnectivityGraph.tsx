// Connectivity Graph visualization using D3.js
// Preserves node positions across data refreshes

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import * as d3 from 'd3';
import { Loader, Network, RefreshCw, X, Server, Cpu, HardDrive } from 'lucide-react';
import { getConnectivityGraph } from '../api/client';
import type { ConnectivityGraph, GraphNode as ApiGraphNode, GraphEdge } from '../types';
import { formatLatency } from '../types';

// Node dimensions for edge calculations
const NODE_WIDTH = 160;
const NODE_HEIGHT = 90;

// D3 Node type with position
interface D3Node extends ApiGraphNode {
  x: number;
  y: number;
  fx?: number | null;
  fy?: number | null;
  location?: string;
}

// D3 Edge type
// sourceId/targetId store original string IDs (D3 force mutates source/target to objects)
interface D3Edge extends GraphEdge {
  sourceId: string;
  targetId: string;
  sourceNode?: D3Node;
  targetNode?: D3Node;
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
  location?: string;
}

interface ConnectivityGraphViewProps {
  refreshInterval?: number;
}

// Store for persisting node positions across renders
const nodePositions = new Map<string, { x: number; y: number }>();

export const ConnectivityGraphView: React.FC<ConnectivityGraphViewProps> = ({
  refreshInterval = 30000,
}) => {
  const [graphData, setGraphData] = useState<ConnectivityGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<D3Node, undefined> | null>(null);

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

  // Calculate closest points on rectangles for edge connections
  const getClosestPoints = (
    source: D3Node,
    target: D3Node
  ): { sx: number; sy: number; tx: number; ty: number } => {
    const sx = source.x;
    const sy = source.y;
    const tx = target.x;
    const ty = target.y;

    // Calculate center-to-center angle
    const angle = Math.atan2(ty - sy, tx - sx);

    // Calculate intersection points with node rectangles
    const halfW = NODE_WIDTH / 2;
    const halfH = NODE_HEIGHT / 2;

    // Source point (on the edge of source rectangle)
    let sourceX = sx;
    let sourceY = sy;
    const cosA = Math.cos(angle);
    const sinA = Math.sin(angle);
    
    if (Math.abs(cosA) * halfH > Math.abs(sinA) * halfW) {
      // Intersects left or right edge
      sourceX = sx + (cosA > 0 ? halfW : -halfW);
      sourceY = sy + (halfW * sinA / Math.abs(cosA));
    } else {
      // Intersects top or bottom edge
      sourceX = sx + (halfH * cosA / Math.abs(sinA));
      sourceY = sy + (sinA > 0 ? halfH : -halfH);
    }

    // Target point (on the edge of target rectangle)
    let targetX = tx;
    let targetY = ty;
    const reverseAngle = angle + Math.PI;
    const cosR = Math.cos(reverseAngle);
    const sinR = Math.sin(reverseAngle);

    if (Math.abs(cosR) * halfH > Math.abs(sinR) * halfW) {
      targetX = tx + (cosR > 0 ? halfW : -halfW);
      targetY = ty + (halfW * sinR / Math.abs(cosR));
    } else {
      targetX = tx + (halfH * cosR / Math.abs(sinR));
      targetY = ty + (sinR > 0 ? halfH : -halfH);
    }

    return { sx: sourceX, sy: sourceY, tx: targetX, ty: targetY };
  };

  // Calculate point on cubic bezier curve at parameter t (0-1)
  const bezierPoint = (
    t: number,
    p0: number,
    p1: number,
    p2: number,
    p3: number
  ): number => {
    const mt = 1 - t;
    return mt * mt * mt * p0 + 3 * mt * mt * t * p1 + 3 * mt * t * t * p2 + t * t * t * p3;
  };

  // D3 Graph rendering
  useEffect(() => {
    if (!graphData || !svgRef.current || !containerRef.current) return;

    const container = containerRef.current;
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Clear previous content
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // Filter out hub nodes
    const clusterNodes = graphData.nodes.filter((n) => n.type !== 'hub');
    const filteredEdges = graphData.edges.filter(
      (e) => e.source !== 'node-manager' && e.target !== 'node-manager'
    );

    // Create D3 nodes with preserved positions
    const d3Nodes: D3Node[] = clusterNodes.map((node, index) => {
      const savedPos = nodePositions.get(node.id);
      if (savedPos) {
        return { ...node, x: savedPos.x, y: savedPos.y, fx: savedPos.x, fy: savedPos.y, location: 'lab' };
      }
      // Initial diagonal layout for new nodes - ensures curves look good from start
      // Each node is placed diagonally so both X and Y differ, creating nice S-curves
      const spacing = 250;
      const startX = width / 2 - (clusterNodes.length - 1) * spacing / 2;
      const startY = height / 2 - (clusterNodes.length - 1) * spacing / 2;
      return {
        ...node,
        x: startX + index * spacing,
        y: startY + index * spacing,
        location: 'lab',
      };
    });

    // Create node lookup map
    const nodeMap = new Map(d3Nodes.map((n) => [n.id, n]));

    // Create bidirectional edges for all cluster node pairs
    // This ensures both directions always exist, even before ping data arrives
    const edgeMap = new Map<string, GraphEdge>();
    filteredEdges.forEach((edge) => {
      edgeMap.set(`${edge.source}->${edge.target}`, edge);
    });

    // Generate all bidirectional edges between cluster nodes
    const allBidirectionalEdges: D3Edge[] = [];
    for (let i = 0; i < clusterNodes.length; i++) {
      for (let j = i + 1; j < clusterNodes.length; j++) {
        const nodeA = clusterNodes[i];
        const nodeB = clusterNodes[j];
        
        // Edge A -> B
        const keyAB = `${nodeA.id}->${nodeB.id}`;
        const existingAB = edgeMap.get(keyAB);
        allBidirectionalEdges.push({
          source: nodeA.id,
          target: nodeB.id,
          sourceId: nodeA.id,  // Store original ID before D3 mutates
          targetId: nodeB.id,
          latency_ms: existingAB?.latency_ms ?? null,
          success: existingAB?.success ?? false,
          packet_loss: existingAB?.packet_loss ?? null,
          measured_at: existingAB?.measured_at ?? null,
          sourceNode: nodeMap.get(nodeA.id),
          targetNode: nodeMap.get(nodeB.id),
        });
        
        // Edge B -> A
        const keyBA = `${nodeB.id}->${nodeA.id}`;
        const existingBA = edgeMap.get(keyBA);
        allBidirectionalEdges.push({
          source: nodeB.id,
          target: nodeA.id,
          sourceId: nodeB.id,  // Store original ID before D3 mutates
          targetId: nodeA.id,
          latency_ms: existingBA?.latency_ms ?? null,
          success: existingBA?.success ?? false,
          packet_loss: existingBA?.packet_loss ?? null,
          measured_at: existingBA?.measured_at ?? null,
          sourceNode: nodeMap.get(nodeB.id),
          targetNode: nodeMap.get(nodeA.id),
        });
      }
    }
    
    const d3Edges = allBidirectionalEdges;

    // Setup zoom behavior with filter to ignore drags on nodes
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .filter((event) => {
        // Allow zoom on scroll, but filter out drags that start on nodes
        if (event.type === 'wheel') return true;
        // Check if the event target is within a node group
        const target = event.target as Element;
        const isNode = target.closest('.node') !== null;
        return !isNode;
      })
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Create main group for zoom/pan
    const g = svg.append('g');

    // Create arrow markers
    const defs = svg.append('defs');
    
    ['success', 'error', 'muted'].forEach((type) => {
      const color = type === 'success' ? 'var(--success)' : 
                    type === 'error' ? 'var(--error)' : 'var(--text-muted)';
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 8)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', color);
    });

    // Create edge groups
    const edgeGroup = g.append('g').attr('class', 'edges');
    
    // Draw edges
    const edges = edgeGroup.selectAll('.edge')
      .data(d3Edges)
      .enter()
      .append('g')
      .attr('class', 'edge');

    // Edge paths
    edges.append('path')
      .attr('class', (d) => {
        if (d.measured_at && d.success) return 'edge-path active';
        return 'edge-path';
      })
      .attr('fill', 'none')
      .attr('stroke-width', 2)
      .attr('stroke', (d) => {
        if (!d.measured_at) return 'var(--text-muted)';
        return d.success ? 'var(--success)' : 'var(--error)';
      })
      .attr('stroke-dasharray', (d) => {
        if (!d.measured_at) return '4 4';
        if (d.success) return '8 4';  // Flowing dash pattern
        return '6 3';
      })
      .attr('marker-end', (d) => {
        if (!d.measured_at) return 'url(#arrow-muted)';
        return d.success ? 'url(#arrow-success)' : 'url(#arrow-error)';
      });

    // Edge labels background
    edges.append('rect')
      .attr('class', 'edge-label-bg')
      .attr('fill', 'var(--bg-secondary)')
      .attr('rx', 3)
      .attr('ry', 3)
      .attr('opacity', 0.9);

    // Edge labels
    edges.append('text')
      .attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('font-size', 10)
      .attr('font-weight', 500)
      .attr('fill', (d) => {
        if (!d.measured_at) return 'var(--text-muted)';
        return d.success ? 'var(--success)' : 'var(--error)';
      })
      .text((d) => {
        if (!d.measured_at) return '';
        return d.success ? formatLatency(d.latency_ms) : 'Failed';
      });

    // Create node groups
    const nodeGroup = g.append('g').attr('class', 'nodes');

    const nodes = nodeGroup.selectAll('.node')
      .data(d3Nodes)
      .enter()
      .append('g')
      .attr('class', 'node')
      .attr('cursor', 'pointer')
      .call(d3.drag<SVGGElement, D3Node>()
        .on('start', (event, d) => {
          if (simulationRef.current) {
            if (!event.active) simulationRef.current.alphaTarget(0.3).restart();
          }
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
          d.x = event.x;
          d.y = event.y;
          nodePositions.set(d.id, { x: event.x, y: event.y });
          updatePositions();
        })
        .on('end', (event, d) => {
          if (simulationRef.current) {
            if (!event.active) simulationRef.current.alphaTarget(0);
          }
          // Keep the node fixed at its current position
          d.fx = d.x;
          d.fy = d.y;
          nodePositions.set(d.id, { x: d.x, y: d.y });
        })
      )
      .on('click', (event, d) => {
        event.stopPropagation();
        setSelectedNode({
          id: d.id,
          label: d.label,
          ip: d.ip,
          ready: d.ready,
          status: d.status,
          kubelet_version: d.kubelet_version,
          cpu_capacity: d.cpu_capacity,
          memory_capacity: d.memory_capacity,
          location: d.location || 'lab',
        });
      });

    // Node container (background)
    nodes.append('rect')
      .attr('class', 'node-bg')
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', NODE_WIDTH)
      .attr('height', NODE_HEIGHT)
      .attr('rx', 10)
      .attr('ry', 10)
      .attr('fill', 'var(--bg-card)')
      .attr('stroke', (d) => d.ready ? 'var(--success)' : 'var(--error)')
      .attr('stroke-width', 2);

    // Node header background
    nodes.append('rect')
      .attr('class', 'node-header')
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', NODE_WIDTH)
      .attr('height', 36)
      .attr('rx', 10)
      .attr('ry', 10)
      .attr('fill', (d) => d.ready ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)');

    // Clip the bottom corners of header
    nodes.append('rect')
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2 + 26)
      .attr('width', NODE_WIDTH)
      .attr('height', 10)
      .attr('fill', (d) => d.ready ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)');

    // Header divider line
    nodes.append('line')
      .attr('x1', -NODE_WIDTH / 2)
      .attr('x2', NODE_WIDTH / 2)
      .attr('y1', -NODE_HEIGHT / 2 + 36)
      .attr('y2', -NODE_HEIGHT / 2 + 36)
      .attr('stroke', 'var(--border)')
      .attr('stroke-width', 1);

    // Status indicator
    nodes.append('circle')
      .attr('cx', NODE_WIDTH / 2 - 14)
      .attr('cy', -NODE_HEIGHT / 2 + 18)
      .attr('r', 4)
      .attr('fill', (d) => d.ready ? 'var(--success)' : 'var(--error)');

    // Server icon (simplified)
    nodes.append('rect')
      .attr('x', -NODE_WIDTH / 2 + 12)
      .attr('y', -NODE_HEIGHT / 2 + 10)
      .attr('width', 12)
      .attr('height', 6)
      .attr('rx', 1)
      .attr('fill', 'none')
      .attr('stroke', (d) => d.ready ? 'var(--success)' : 'var(--error)')
      .attr('stroke-width', 1.5);

    nodes.append('rect')
      .attr('x', -NODE_WIDTH / 2 + 12)
      .attr('y', -NODE_HEIGHT / 2 + 20)
      .attr('width', 12)
      .attr('height', 6)
      .attr('rx', 1)
      .attr('fill', 'none')
      .attr('stroke', (d) => d.ready ? 'var(--success)' : 'var(--error)')
      .attr('stroke-width', 1.5);

    // Hostname label
    nodes.append('text')
      .attr('x', -NODE_WIDTH / 2 + 30)
      .attr('y', -NODE_HEIGHT / 2 + 22)
      .attr('font-size', 13)
      .attr('font-weight', 600)
      .attr('fill', 'var(--text-primary)')
      .text((d) => d.label);

    // IP Address
    nodes.append('text')
      .attr('x', 0)
      .attr('y', 2)
      .attr('text-anchor', 'middle')
      .attr('font-size', 12)
      .attr('font-family', "'JetBrains Mono', 'Fira Code', monospace")
      .attr('fill', 'var(--text-muted)')
      .text((d) => d.ip || 'No IP');

    // Location badge background
    nodes.append('rect')
      .attr('x', -20)
      .attr('y', 16)
      .attr('width', 40)
      .attr('height', 18)
      .attr('rx', 4)
      .attr('fill', 'var(--bg-secondary)');

    // Location text
    nodes.append('text')
      .attr('x', 0)
      .attr('y', 28)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('font-weight', 500)
      .attr('fill', 'var(--text-muted)')
      .text((d) => d.location || 'lab');

    // Update function for positions
    const updatePositions = () => {
      // Update node positions
      nodes.attr('transform', (d) => `translate(${d.x}, ${d.y})`);

      // Update edge paths with React Flow-style bezier curves
      edges.select('.edge-path')
        .attr('d', (d) => {
          if (!d.sourceNode || !d.targetNode) return '';
          
          const sx = d.sourceNode.x;
          const sy = d.sourceNode.y;
          const tx = d.targetNode.x;
          const ty = d.targetNode.y;
          
          // For cluster nodes, always assume bidirectional (they ping each other)
          // Use sourceId/targetId (original strings) since D3 mutates source/target to objects
          const hasReverse = d3Edges.some(
            (e) => e.sourceId === d.targetId && e.targetId === d.sourceId
          ) || (d.sourceNode.type !== 'hub' && d.targetNode.type !== 'hub');
          
          // Use sourceId for comparison (D3 may have mutated source to object)
          const isFirst = d.sourceId < d.targetId;
          const sideOffset = hasReverse ? (isFirst ? 12 : -12) : 0;
          
          // Determine primary direction and which side to connect
          const dx = tx - sx;
          const dy = ty - sy;
          const distance = Math.sqrt(dx * dx + dy * dy);
          
          // When nodes are very close, default to vertical layout with slight curve
          const minDistance = 10;
          const effectiveVertical = distance < minDistance 
            ? isFirst  // Use consistent direction based on edge order
            : Math.abs(dy) > Math.abs(dx);
          
          let startX: number, startY: number, endX: number, endY: number;
          let ctrl1X: number, ctrl1Y: number, ctrl2X: number, ctrl2Y: number;
          
          if (effectiveVertical) {
            // Vertical layout: connect from bottom/top of nodes
            if (dy > 0) {
              // Source above target
              startX = sx + sideOffset;
              startY = sy + NODE_HEIGHT / 2;
              endX = tx + sideOffset;
              endY = ty - NODE_HEIGHT / 2;
            } else {
              // Source below target
              startX = sx + sideOffset;
              startY = sy - NODE_HEIGHT / 2;
              endX = tx + sideOffset;
              endY = ty + NODE_HEIGHT / 2;
            }
            // Control points extend vertically (smoothstep style)
            const ctrlOffset = Math.abs(endY - startY) * 0.5;
            ctrl1X = startX;
            ctrl1Y = startY + (dy > 0 ? ctrlOffset : -ctrlOffset);
            ctrl2X = endX;
            ctrl2Y = endY + (dy > 0 ? -ctrlOffset : ctrlOffset);
          } else {
            // Horizontal layout: connect from left/right of nodes
            if (dx > 0) {
              // Source left of target
              startX = sx + NODE_WIDTH / 2;
              startY = sy + sideOffset;
              endX = tx - NODE_WIDTH / 2;
              endY = ty + sideOffset;
            } else {
              // Source right of target
              startX = sx - NODE_WIDTH / 2;
              startY = sy + sideOffset;
              endX = tx + NODE_WIDTH / 2;
              endY = ty + sideOffset;
            }
            // Control points extend horizontally (smoothstep style)
            const ctrlOffset = Math.abs(endX - startX) * 0.5;
            ctrl1X = startX + (dx > 0 ? ctrlOffset : -ctrlOffset);
            ctrl1Y = startY;
            ctrl2X = endX + (dx > 0 ? -ctrlOffset : ctrlOffset);
            ctrl2Y = endY;
          }
          
          return `M${startX},${startY} C${ctrl1X},${ctrl1Y} ${ctrl2X},${ctrl2Y} ${endX},${endY}`;
        });

      // Helper function to compute curve geometry for an edge
      // Returns start, end, and control points
      const getEdgeCurveGeometry = (d: D3Edge) => {
        if (!d.sourceNode || !d.targetNode) return null;
        
        const sx = d.sourceNode.x;
        const sy = d.sourceNode.y;
        const tx = d.targetNode.x;
        const ty = d.targetNode.y;
        const dx = tx - sx;
        const dy = ty - sy;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        // Use sourceId/targetId (original strings) since D3 mutates source/target to objects
        const hasReverse = d3Edges.some(
          (e) => e.sourceId === d.targetId && e.targetId === d.sourceId
        ) || (d.sourceNode.type !== 'hub' && d.targetNode.type !== 'hub');
        const isFirst = d.sourceId < d.targetId;
        const sideOffset = hasReverse ? (isFirst ? 12 : -12) : 0;
        
        const minDistance = 10;
        const effectiveVertical = distance < minDistance ? isFirst : Math.abs(dy) > Math.abs(dx);
        
        let startX: number, startY: number, endX: number, endY: number;
        let ctrl1X: number, ctrl1Y: number, ctrl2X: number, ctrl2Y: number;
        
        if (effectiveVertical) {
          if (dy > 0) {
            startX = sx + sideOffset;
            startY = sy + NODE_HEIGHT / 2;
            endX = tx + sideOffset;
            endY = ty - NODE_HEIGHT / 2;
          } else {
            startX = sx + sideOffset;
            startY = sy - NODE_HEIGHT / 2;
            endX = tx + sideOffset;
            endY = ty + NODE_HEIGHT / 2;
          }
          const ctrlOffset = Math.abs(endY - startY) * 0.5;
          ctrl1X = startX;
          ctrl1Y = startY + (dy > 0 ? ctrlOffset : -ctrlOffset);
          ctrl2X = endX;
          ctrl2Y = endY + (dy > 0 ? -ctrlOffset : ctrlOffset);
        } else {
          if (dx > 0) {
            startX = sx + NODE_WIDTH / 2;
            startY = sy + sideOffset;
            endX = tx - NODE_WIDTH / 2;
            endY = ty + sideOffset;
          } else {
            startX = sx - NODE_WIDTH / 2;
            startY = sy + sideOffset;
            endX = tx + NODE_WIDTH / 2;
            endY = ty + sideOffset;
          }
          const ctrlOffset = Math.abs(endX - startX) * 0.5;
          ctrl1X = startX + (dx > 0 ? ctrlOffset : -ctrlOffset);
          ctrl1Y = startY;
          ctrl2X = endX + (dx > 0 ? -ctrlOffset : ctrlOffset);
          ctrl2Y = endY;
        }
        
        return { startX, startY, ctrl1X, ctrl1Y, ctrl2X, ctrl2Y, endX, endY };
      };

      // Update edge labels position at the midpoint of the bezier curve
      // Position labels at 1/4 from source - this naturally separates bidirectional labels
      edges.select('.edge-label')
        .attr('x', (d) => {
          const geom = getEdgeCurveGeometry(d);
          if (!geom) return 0;
          return bezierPoint(0.25, geom.startX, geom.ctrl1X, geom.ctrl2X, geom.endX);
        })
        .attr('y', (d) => {
          const geom = getEdgeCurveGeometry(d);
          if (!geom) return 0;
          return bezierPoint(0.25, geom.startY, geom.ctrl1Y, geom.ctrl2Y, geom.endY);
        });

      // Update edge label backgrounds
      edges.select('.edge-label-bg')
        .each(function(d) {
          const label = d3.select(this.parentNode as Element).select('.edge-label');
          const text = label.text();
          if (!text) {
            d3.select(this).attr('width', 0).attr('height', 0);
            return;
          }
          const bbox = (label.node() as SVGTextElement)?.getBBox();
          if (bbox) {
            d3.select(this)
              .attr('x', bbox.x - 4)
              .attr('y', bbox.y - 2)
              .attr('width', bbox.width + 8)
              .attr('height', bbox.height + 4);
          }
        });
    };

    // Create force simulation (only for initial layout if no saved positions)
    const hasAllPositions = d3Nodes.every((n) => nodePositions.has(n.id));
    
    if (!hasAllPositions) {
      simulationRef.current = d3.forceSimulation(d3Nodes)
        .force('link', d3.forceLink(d3Edges)
          .id((d: any) => d.id)
          .distance(250)
        )
        .force('charge', d3.forceManyBody().strength(-800))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(NODE_WIDTH * 0.8))
        .on('tick', () => {
          // Save positions during simulation
          d3Nodes.forEach((n) => {
            nodePositions.set(n.id, { x: n.x, y: n.y });
          });
          updatePositions();
        })
        .on('end', () => {
          // Fix all nodes after simulation ends
          d3Nodes.forEach((n) => {
            n.fx = n.x;
            n.fy = n.y;
            nodePositions.set(n.id, { x: n.x, y: n.y });
          });
        });
    } else {
      // Just update positions without simulation
      updatePositions();
    }

    // Click on background to close sidebar
    svg.on('click', () => {
      setSelectedNode(null);
    });

    // Fit to view on initial render
    if (!hasAllPositions) {
      setTimeout(() => {
        const bounds = g.node()?.getBBox();
        if (bounds && bounds.width > 0 && bounds.height > 0) {
          const scale = Math.min(
            width / (bounds.width + 100),
            height / (bounds.height + 100),
            1.5
          );
          const translateX = width / 2 - (bounds.x + bounds.width / 2) * scale;
          const translateY = height / 2 - (bounds.y + bounds.height / 2) * scale;
          svg.transition()
            .duration(500)
            .call(zoom.transform, d3.zoomIdentity.translate(translateX, translateY).scale(scale));
        }
      }, 500);
    }

    return () => {
      if (simulationRef.current) {
        simulationRef.current.stop();
      }
    };
  }, [graphData]);

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

      <div className="graph-canvas" ref={containerRef}>
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          style={{ background: 'transparent' }}
        />
      </div>

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
                <span className="field-value">{selectedNode.ip || 'N/A'}</span>
              </div>
              <div className="sidebar-field">
                <span className="field-label">Location</span>
                <span className="field-value">{selectedNode.location || 'lab'}</span>
              </div>
              <div className="sidebar-field">
                <span className="field-label">Status</span>
                <span className={`field-value status-badge ${selectedNode.ready ? 'healthy' : 'unhealthy'}`}>
                  {selectedNode.ready ? 'Healthy' : 'Unhealthy'}
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
