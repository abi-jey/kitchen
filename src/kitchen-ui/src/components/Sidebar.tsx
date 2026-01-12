// Sidebar navigation component

import React from 'react';
import { Network, LayoutDashboard, Settings, Activity, Server } from 'lucide-react';

export type ViewType = 'graph' | 'dashboard' | 'history';

interface SidebarProps {
  currentView: ViewType;
  onViewChange: (view: ViewType) => void;
  isConnected: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onViewChange,
  isConnected,
}) => {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <Server size={20} />
          </div>
          <div className="sidebar-logo-text">
            <h1>Kitchen</h1>
            <span>Node Manager</span>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav">
        <button
          className={`nav-item ${currentView === 'graph' ? 'active' : ''}`}
          onClick={() => onViewChange('graph')}
        >
          <Network size={18} />
          <span>Connectivity Graph</span>
        </button>

        <button
          className={`nav-item ${currentView === 'dashboard' ? 'active' : ''}`}
          onClick={() => onViewChange('dashboard')}
        >
          <LayoutDashboard size={18} />
          <span>Dashboard</span>
        </button>

        <div className="nav-section">
          <div className="nav-section-title">Monitoring</div>
          <button
            className={`nav-item ${currentView === 'history' ? 'active' : ''}`}
            onClick={() => onViewChange('history')}
          >
            <Activity size={18} />
            <span>Health History</span>
          </button>
        </div>

        <div className="nav-section">
          <div className="nav-section-title">Settings</div>
          <button className="nav-item" disabled>
            <Settings size={18} />
            <span>Configuration</span>
          </button>
        </div>
      </nav>

      <div className="sidebar-footer">
        <div className="connection-status">
          <span className={`status-dot ${isConnected ? '' : 'disconnected'}`} />
          <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>
    </aside>
  );
};
