import React from 'react';

const Toolbar = ({ onFileSelect, loading }) => {
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      onFileSelect(file);
    }
  };
  
  return (
    <div className="toolbar">
      <div className="title">LLDB Trace Viewer</div>
      
      <div className="controls">
        <label className="file-upload-button">
          {loading ? 'Loading...' : 'Open Trace File'}
          <input 
            type="file" 
            accept=".json" 
            onChange={handleFileChange}
            disabled={loading}
            style={{ display: 'none' }}
          />
        </label>
      </div>
    </div>
  );
};

export default Toolbar;