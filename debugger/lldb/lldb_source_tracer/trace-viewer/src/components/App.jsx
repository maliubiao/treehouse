import React, { useState, useEffect } from 'react';
import Sidebar from './Sidebar';
import CodeView from './CodeView';
import CallGraph from './CallGraph';
import StatsChart from './StatsChart';
import Toolbar from './Toolbar';
import { loadTraceData } from '../utils/dataLoader';

const App = () => {
  const [traceData, setTraceData] = useState(null);
  const [activeTab, setActiveTab] = useState('code');
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const handleFileSelect = async (file) => {
    try {
      setLoading(true);
      setError(null);
      const data = await loadTraceData(file);
      setTraceData(data);
      setSelectedEvent(data.log_entries[0]);
    } catch (err) {
      setError('Failed to load trace data: ' + err.message);
    } finally {
      setLoading(false);
    }
  };
  
  const handleEventSelect = (event) => {
    setSelectedEvent(event);
  };
  
  const renderTabContent = () => {
    if (!traceData) return null;
    
    switch (activeTab) {
      case 'code':
        return (
          <CodeView 
            traceData={traceData} 
            selectedEvent={selectedEvent} 
          />
        );
      case 'callgraph':
        return <CallGraph callEdges={traceData.call_edges} />;
      case 'stats':
        return <StatsChart functions={traceData.functions} />;
      default:
        return null;
    }
  };
  
  return (
    <div className="trace-container">
      <Toolbar onFileSelect={handleFileSelect} loading={loading} />
      
      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}
      
      {loading && (
        <div className="loading-overlay">
          <div className="spinner"></div>
          <p>Loading trace data...</p>
        </div>
      )}
      
      {traceData ? (
        <div className="main-content">
          <div className="tab-container">
            <div className="tabs">
              <button 
                className={activeTab === 'code' ? 'active' : ''}
                onClick={() => setActiveTab('code')}
              >
                Source Code
              </button>
              <button 
                className={activeTab === 'callgraph' ? 'active' : ''}
                onClick={() => setActiveTab('callgraph')}
              >
                Call Graph
              </button>
              <button 
                className={activeTab === 'stats' ? 'active' : ''}
                onClick={() => setActiveTab('stats')}
              >
                Performance
              </button>
            </div>
            
            <div className="tab-content">
              {renderTabContent()}
            </div>
          </div>
          
          <Sidebar 
            events={traceData.log_entries} 
            onEventSelect={handleEventSelect}
            selectedEvent={selectedEvent}
          />
        </div>
      ) : (
        <div className="welcome-screen">
          <h2>LLDB Trace Viewer</h2>
          <p>Select a trace.json file to begin</p>
          <p>Generate trace files using lldb_source_tracer.py</p>
        </div>
      )}
    </div>
  );
};

export default App;