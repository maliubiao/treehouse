import React from 'react';
import { 
  Box, 
  Typography, 
  Paper,
  Alert,
  CircularProgress
} from '@mui/material';

export const ExecutionResultPanel = ({ 
  output, 
  error, 
  isExecuting,
  theme
}) => {
  return (
    <Paper elevation={2} sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Typography variant="h6" gutterBottom sx={{ fontWeight: 'bold' }}>
        执行结果
      </Typography>
      
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}
      
      {isExecuting ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200 }}>
          <CircularProgress />
          <Typography variant="body1" sx={{ ml: 2 }}>正在执行代码...</Typography>
        </Box>
      ) : output ? (
        <Box sx={{ 
          fontFamily: '"Roboto Mono", monospace', 
          whiteSpace: 'pre-wrap', 
          backgroundColor: theme.palette.background.paper,
          p: 2,
          borderRadius: 1,
          border: `1px solid ${theme.palette.divider}`,
          flexGrow: 1,
          overflow: 'auto',
          maxHeight: 400
        }}>
          {output}
        </Box>
      ) : (
        <Box sx={{ 
          display: 'flex', 
          justifyContent: 'center', 
          alignItems: 'center', 
          height: 200,
          color: theme.palette.text.secondary
        }}>
          <Typography variant="body1">执行结果将显示在这里</Typography>
        </Box>
      )}
    </Paper>
  );
};