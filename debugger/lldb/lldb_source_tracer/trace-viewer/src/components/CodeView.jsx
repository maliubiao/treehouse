import React, { useMemo } from 'react';

const CodeView = ({ traceData, selectedEvent }) => {
  const { source_files: sourceFiles } = traceData;
  
  const { sourceCode, highlightedLine } = useMemo(() => {
    if (!selectedEvent || !sourceFiles) {
      return { sourceCode: [], highlightedLine: -1 };
    }
    
    const fullPath = Object.keys(sourceFiles).find(path => 
      path.endsWith(selectedEvent.source_file)
    );
    
    if (!fullPath || !sourceFiles[fullPath]) {
      return { sourceCode: [], highlightedLine: -1 };
    }
    
    return {
      sourceCode: sourceFiles[fullPath].content,
      highlightedLine: selectedEvent.line
    };
  }, [selectedEvent, sourceFiles]);
  
  if (!selectedEvent) {
    return (
      <div className="code-view">
        <p>Select an event from the timeline to view source code</p>
      </div>
    );
  }
  
  return (
    <div className="code-view">
      <div className="code-header">
        <h3>{selectedEvent.source_file}</h3>
        <div className="code-location">
          Line {selectedEvent.line} in {selectedEvent.function}
        </div>
      </div>
      
      <div className="code-container">
        <pre>
          {sourceCode.map((line, index) => {
            const lineNum = index + 1;
            const isHighlighted = lineNum === highlightedLine;
            return (
              <div 
                key={index} 
                className={`code-line ${isHighlighted ? 'highlighted' : ''}`}
              >
                <span className="line-number">{lineNum}</span>
                <span className="line-content">{line}</span>
              </div>
            );
          })}
        </pre>
      </div>
      
      {selectedEvent.type === 'STEP' && (
        <div className="locals-panel">
          <h4>Local Variables</h4>
          <div className="locals-grid">
            {JSON.parse(selectedEvent.message).map((variable, idx) => (
              <div key={idx} className="local-variable">
                <span className="var-name">{variable.name}</span>
                <span className="var-type">{variable.type}</span>
                <span className="var-value">{variable.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default CodeView;