import React, { useCallback } from 'react';
import ReactFlow, { 
  Controls, 
  Background, 
  MiniMap,
  useNodesState,
  useEdgesState
} from 'reactflow';
import 'reactflow/dist/style.css';

const CallGraph = ({ callEdges }) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  
  const generateGraph = useCallback(() => {
    if (!callEdges || Object.keys(callEdges).length === 0) {
      return;
    }
    
    const nodeMap = new Map();
    const newNodes = [];
    const newEdges = [];
    let nodeId = 1;
    
    // Create nodes for all functions
    Object.keys(callEdges).forEach(caller => {
      if (!nodeMap.has(caller)) {
        nodeMap.set(caller, nodeId++);
        newNodes.push({
          id: `node-${nodeMap.get(caller)}`,
          data: { label: caller },
          position: { x: Math.random() * 500, y: Math.random() * 500 }
        });
      }
      
      Object.keys(callEdges[caller]).forEach(callee => {
        if (!nodeMap.has(callee)) {
          nodeMap.set(callee, nodeId++);
          newNodes.push({
            id: `node-${nodeMap.get(callee)}`,
            data: { label: callee },
            position: { x: Math.random() * 500, y: Math.random() * 500 }
          });
        }
        
        newEdges.push({
          id: `edge-${nodeMap.get(caller)}-${nodeMap.get(callee)}`,
          source: `node-${nodeMap.get(caller)}`,
          target: `node-${nodeMap.get(callee)}`,
          label: `${callEdges[caller][callee]} calls`,
          animated: true
        });
      });
    });
    
    setNodes(newNodes);
    setEdges(newEdges);
  }, [callEdges, setNodes, setEdges]);
  
  React.useEffect(() => {
    generateGraph();
  }, [callEdges, generateGraph]);
  
  if (!callEdges || Object.keys(callEdges).length === 0) {
    return (
      <div className="call-graph" style={{ 
        height: '100%', 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center' 
      }}>
        <p>No call graph data available</p>
      </div>
    );
  }
  
  return (
    <div className="call-graph" style={{ height: '100%', width: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
      >
        <Controls />
        <MiniMap />
        <Background gap={12} size={1} />
      </ReactFlow>
    </div>
  );
};

export default CallGraph;