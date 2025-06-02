import React from 'react';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  Legend,
  ResponsiveContainer
} from 'recharts';

const StatsChart = ({ functions }) => {
  const prepareData = () => {
    if (!functions) return [];
    
    return Object.values(functions)
      .filter(func => func.duration > 0)
      .map(func => ({
        name: func.function,
        duration: func.duration * 1000, // Convert to ms
        calls: 1,
        steps: func.steps.length
      }))
      .sort((a, b) => b.duration - a.duration)
      .slice(0, 20); // Top 20 functions
  };
  
  const data = prepareData();
  
  return (
    <div className="stats-chart">
      <h3>Function Performance</h3>
      
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={400}>
          <BarChart
            data={data}
            margin={{ top: 20, right: 30, left: 20, bottom: 70 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" angle={-45} textAnchor="end" height={70} />
            <YAxis />
            <Tooltip formatter={(value) => value.toFixed(2)} />
            <Legend />
            <Bar dataKey="duration" name="Duration (ms)" fill="#8884d8" />
            <Bar dataKey="steps" name="Steps" fill="#82ca9d" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      
      <div className="stats-summary">
        <div className="stat-card">
          <h4>Total Functions</h4>
          <p>{Object.keys(functions).length}</p>
        </div>
        <div className="stat-card">
          <h4>Longest Function</h4>
          <p>
            {data.length > 0 ? data[0].name : 'N/A'}: 
            {data.length > 0 ? data[0].duration.toFixed(2) + 'ms' : ''}
          </p>
        </div>
        <div className="stat-card">
          <h4>Most Steps</h4>
          <p>
            {data.length > 0 
              ? data.reduce((max, curr) => curr.steps > max.steps ? curr : max, data[0]).name 
              : 'N/A'
            }
          </p>
        </div>
      </div>
    </div>
  );
};

export default StatsChart;