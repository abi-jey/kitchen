import React from 'react';
import { RefreshCw, Activity, Clock, Wifi, WifiOff } from 'lucide-react';
import type { HealthStatus } from '../types';

interface HeaderProps {
  health: HealthStatus | null;
  lastUpdated: Date | null;
  onRefresh: () => void;
  loading?: boolean;
  isConnected?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  lastUpdated,
  onRefresh,
  loading,
  isConnected,
}) => {
  return (
    <header className="app-header">
      <div className="header-left">
        <h1>
          <Activity size={28} />
          Kitchen Node Manager
        </h1>
        {health && (
          <div className={`health-badge ${health.healthy ? 'healthy' : 'error'}`}>
            <span className="health-dot" />
            {health.healthy ? 'System Healthy' : 'Issues Detected'}
          </div>
        )}
      </div>
      <div className="header-right">
        <div
          className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}
          title={isConnected ? 'Live updates active' : 'Polling for updates'}
        >
          {isConnected ? <Wifi size={14} /> : <WifiOff size={14} />}
          {isConnected ? 'Live' : 'Polling'}
        </div>
        {lastUpdated && (
          <span className="last-update">
            <Clock size={14} />
            {formatTime(lastUpdated)}
          </span>
        )}
        <button
          className="refresh-btn"
          onClick={onRefresh}
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw size={18} className={loading ? 'spinning' : ''} />
        </button>
      </div>
    </header>
  );
};

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
