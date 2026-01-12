import React, { useState, useEffect } from 'react';
import type { NodeWithConnectivity, ConnectivityRecord } from '../types';
import { formatLatency, formatTimeAgo } from '../types';
import { getNodeConnectivity, getNodeDetail } from '../api/client';
import type { NodeDetail } from '../types';
import {
  X,
  Server,
  Cpu,
  HardDrive,
  Globe,
  Network,
  Calendar,
  Activity,
  CheckCircle,
  XCircle,
} from 'lucide-react';

interface NodeDetailPanelProps {
  node: NodeWithConnectivity;
  onClose: () => void;
}

export const NodeDetailPanel: React.FC<NodeDetailPanelProps> = ({
  node,
  onClose,
}) => {
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [connectivity, setConnectivity] = useState<ConnectivityRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    Promise.all([
      getNodeDetail(node.name),
      getNodeConnectivity(node.name, 24),
    ])
      .then(([d, c]) => {
        if (mounted) {
          setDetail(d);
          setConnectivity(c);
        }
      })
      .catch(console.error)
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [node.name]);

  const successRate =
    connectivity.length > 0
      ? (connectivity.filter((c) => c.success).length / connectivity.length) * 100
      : null;

  const avgLatency =
    connectivity.length > 0
      ? connectivity
          .filter((c) => c.latency_ms !== null)
          .reduce((acc, c) => acc + (c.latency_ms ?? 0), 0) /
        connectivity.filter((c) => c.latency_ms !== null).length
      : null;

  return (
    <div className="detail-panel">
      <div className="detail-panel-header">
        <h2>
          <Server size={20} />
          {node.name}
        </h2>
        <button className="close-btn" onClick={onClose}>
          <X size={20} />
        </button>
      </div>

      {loading ? (
        <div className="detail-loading">Loading...</div>
      ) : (
        <>
          <div className="detail-section">
            <h3>Status</h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">Ready</span>
                <span className={`value ${node.ready ? 'success' : 'error'}`}>
                  {node.ready ? (
                    <CheckCircle size={16} />
                  ) : (
                    <XCircle size={16} />
                  )}
                  {node.ready ? 'Yes' : 'No'}
                </span>
              </div>
              <div className="detail-item">
                <span className="label">Schedulable</span>
                <span className={`value ${node.schedulable ? 'success' : 'warning'}`}>
                  {node.schedulable ? 'Yes' : 'Cordoned'}
                </span>
              </div>
              <div className="detail-item">
                <span className="label">Status</span>
                <span className="value">{node.status}</span>
              </div>
            </div>
          </div>

          <div className="detail-section">
            <h3>
              <Network size={16} />
              Network
            </h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">Internal IP</span>
                <span className="value mono">{detail?.internal_ip || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Tailscale IP</span>
                <span className="value mono">{node.tailscale_ip || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Hostname</span>
                <span className="value">{detail?.hostname || '—'}</span>
              </div>
            </div>
          </div>

          <div className="detail-section">
            <h3>
              <Cpu size={16} />
              Resources
            </h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">CPU</span>
                <span className="value">{detail?.cpu_capacity || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Memory</span>
                <span className="value">{detail?.memory_capacity || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Pods</span>
                <span className="value">{detail?.pods_capacity ?? '—'}</span>
              </div>
            </div>
          </div>

          <div className="detail-section">
            <h3>
              <Globe size={16} />
              System
            </h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">OS</span>
                <span className="value">{detail?.os_image || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Kernel</span>
                <span className="value">{detail?.kernel_version || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Container Runtime</span>
                <span className="value">{detail?.container_runtime || '—'}</span>
              </div>
              <div className="detail-item">
                <span className="label">Kubelet</span>
                <span className="value">{node.kubelet_version || '—'}</span>
              </div>
            </div>
          </div>

          <div className="detail-section">
            <h3>
              <Activity size={16} />
              Connectivity (24h)
            </h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">Success Rate</span>
                <span
                  className={`value ${
                    successRate !== null
                      ? successRate >= 95
                        ? 'success'
                        : successRate >= 80
                        ? 'warning'
                        : 'error'
                      : ''
                  }`}
                >
                  {successRate !== null ? `${successRate.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="detail-item">
                <span className="label">Avg Latency</span>
                <span className="value">{formatLatency(avgLatency)}</span>
              </div>
              <div className="detail-item">
                <span className="label">Measurements</span>
                <span className="value">{connectivity.length}</span>
              </div>
            </div>

            {connectivity.length > 0 && (
              <div className="connectivity-history">
                <div className="history-chart">
                  {connectivity.slice(0, 48).reverse().map((c, i) => (
                    <div
                      key={i}
                      className={`history-bar ${c.success ? 'success' : 'error'}`}
                      style={{
                        height: c.latency_ms
                          ? `${Math.min(100, (c.latency_ms / 200) * 100)}%`
                          : '10%',
                      }}
                      title={`${formatTimeAgo(c.measured_at)}: ${
                        c.success ? formatLatency(c.latency_ms) : 'Failed'
                      }`}
                    />
                  ))}
                </div>
                <div className="history-label">Last 48 measurements</div>
              </div>
            )}
          </div>

          <div className="detail-section">
            <h3>
              <Calendar size={16} />
              Timestamps
            </h3>
            <div className="detail-grid">
              <div className="detail-item">
                <span className="label">First Seen</span>
                <span className="value">{formatTimeAgo(node.first_seen_at)}</span>
              </div>
              <div className="detail-item">
                <span className="label">Last Seen</span>
                <span className="value">{formatTimeAgo(node.last_seen_at)}</span>
              </div>
              {node.unavailable_since && (
                <div className="detail-item">
                  <span className="label">Unavailable Since</span>
                  <span className="value error">
                    {formatTimeAgo(node.unavailable_since)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
