import React, { useState } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { Sidebar, type ViewType } from './components/Sidebar';
import { DashboardView } from './components/DashboardView';
import { ConnectivityGraphView } from './components/ConnectivityGraph';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<ViewType>('graph');
  const { isConnected } = useWebSocket();

  return (
    <div className="app-root">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        isConnected={isConnected}
      />

      <div className="app-content">
        {currentView === 'graph' && <ConnectivityGraphView refreshInterval={30000} />}
        {currentView === 'dashboard' && <DashboardView isConnected={isConnected} />}
      </div>

      <footer className="app-footer">
        <span>Kitchen Node Manager</span>
        <span className="footer-sep">•</span>
        <span>Auto-refresh: 30s</span>
      </footer>
    </div>
  );
};

export default App;
