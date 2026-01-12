// Health History View - displays connectivity history records

import React, { useState, useEffect, useCallback } from 'react';
import { Loader, History, CheckCircle, XCircle, Clock, RefreshCw, Filter, Search } from 'lucide-react';
import { getNodesDashboard, getNodeConnectivityHistory } from '../api/client';
import type { ConnectivityRecord, NodeWithConnectivity } from '../types';
import { formatLatency, formatTimeAgo } from '../types';

interface HealthHistoryViewProps {
  refreshInterval?: number;
}

export const HealthHistoryView: React.FC<HealthHistoryViewProps> = ({
  refreshInterval = 60000,
}) => {
  const [nodes, setNodes] = useState<NodeWithConnectivity[]>([]);
  const [selectedNode, setSelectedNode] = useState<string>('');
  const [history, setHistory] = useState<ConnectivityRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);
  const [filterSuccess, setFilterSuccess] = useState<boolean | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  // Fetch nodes list
  const fetchNodes = useCallback(async () => {
    try {
      const data = await getNodesDashboard();
      setNodes(data);
      if (data.length > 0 && !selectedNode) {
        setSelectedNode(data[0].name);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load nodes');
    } finally {
      setLoading(false);
    }
  }, [selectedNode]);

  // Fetch history for selected node
  const fetchHistory = useCallback(async () => {
    if (!selectedNode) return;
    
    setHistoryLoading(true);
    try {
      const options: { limit: number; success?: boolean } = { limit };
      if (filterSuccess !== null) {
        options.success = filterSuccess;
      }
      const data = await getNodeConnectivityHistory(selectedNode, options);
      setHistory(data);
    } catch (err) {
      console.error('Failed to fetch history:', err);
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [selectedNode, limit, filterSuccess]);

  useEffect(() => {
    fetchNodes();
    const interval = setInterval(fetchNodes, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchNodes, refreshInterval]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Filter history by search term
  const filteredHistory = history.filter((record) => {
    if (!searchTerm) return true;
    const search = searchTerm.toLowerCase();
    return (
      record.source_node.toLowerCase().includes(search) ||
      record.node_name.toLowerCase().includes(search) ||
      record.target_ip.toLowerCase().includes(search) ||
      (record.error_message && record.error_message.toLowerCase().includes(search))
    );
  });

  if (loading) {
    return (
      <div className="health-history-view">
        <div className="history-loading-state">
          <Loader size={48} className="spinning" />
          <p>Loading nodes...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="health-history-view">
        <div className="history-error-state">
          <History size={64} />
          <p>Failed to load: {error}</p>
          <button onClick={fetchNodes}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="health-history-view">
      <div className="history-header">
        <div className="header-title">
          <History size={24} />
          <h2>Health History</h2>
        </div>
        <button className="refresh-btn" onClick={fetchHistory} disabled={historyLoading}>
          <RefreshCw size={16} className={historyLoading ? 'spinning' : ''} />
        </button>
      </div>

      <div className="history-filters">
        <div className="filter-group">
          <label>Node</label>
          <select
            value={selectedNode}
            onChange={(e) => setSelectedNode(e.target.value)}
          >
            {nodes.map((node) => (
              <option key={node.name} value={node.name}>
                {node.name}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Status</label>
          <select
            value={filterSuccess === null ? 'all' : filterSuccess ? 'success' : 'failed'}
            onChange={(e) => {
              const val = e.target.value;
              setFilterSuccess(val === 'all' ? null : val === 'success');
            }}
          >
            <option value="all">All</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Limit</label>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={250}>250</option>
            <option value={500}>500</option>
          </select>
        </div>

        <div className="filter-group search-group">
          <label>Search</label>
          <div className="search-input">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search source, IP, error..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="history-stats">
        <div className="stat">
          <span className="stat-value">{filteredHistory.length}</span>
          <span className="stat-label">Records</span>
        </div>
        <div className="stat success">
          <span className="stat-value">{filteredHistory.filter(r => r.success).length}</span>
          <span className="stat-label">Successful</span>
        </div>
        <div className="stat error">
          <span className="stat-value">{filteredHistory.filter(r => !r.success).length}</span>
          <span className="stat-label">Failed</span>
        </div>
      </div>

      {historyLoading ? (
        <div className="history-loading-state">
          <Loader size={32} className="spinning" />
          <p>Loading history...</p>
        </div>
      ) : filteredHistory.length === 0 ? (
        <div className="history-empty-state">
          <Filter size={48} />
          <p>No records found</p>
        </div>
      ) : (
        <div className="history-table-container">
          <table className="history-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Time</th>
                <th>Source Node</th>
                <th>Target Node</th>
                <th>Target IP</th>
                <th>Latency</th>
                <th>Packet Loss</th>
                <th>Ping Count</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {filteredHistory.map((record) => (
                <tr key={record.id} className={record.success ? 'success' : 'failure'}>
                  <td className="status-cell">
                    {record.success ? (
                      <CheckCircle size={16} className="success-icon" />
                    ) : (
                      <XCircle size={16} className="error-icon" />
                    )}
                  </td>
                  <td className="time-cell">
                    <Clock size={12} />
                    <span title={record.measured_at}>{formatTimeAgo(record.measured_at)}</span>
                  </td>
                  <td className="node-cell">{record.source_node}</td>
                  <td className="node-cell">{record.node_name}</td>
                  <td className="ip-cell">{record.target_ip}</td>
                  <td className="latency-cell">
                    {record.latency_ms !== null && record.latency_ms !== undefined
                      ? formatLatency(record.latency_ms)
                      : '-'}
                  </td>
                  <td className="loss-cell">
                    {record.packet_loss !== null && record.packet_loss !== undefined
                      ? `${record.packet_loss.toFixed(1)}%`
                      : '-'}
                  </td>
                  <td className="ping-cell">{record.ping_count || '-'}</td>
                  <td className="error-cell" title={record.error_message || ''}>
                    {record.error_message || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
