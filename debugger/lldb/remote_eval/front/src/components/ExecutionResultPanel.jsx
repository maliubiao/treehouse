import React, { useEffect, useState } from 'react';
import { 
  Box, 
  Typography, 
  Paper,
  Alert,
  CircularProgress,
  Tabs,
  Tab,
  useTheme
} from '@mui/material';
import { Terminal as ConsoleIcon, Code as CodeIcon } from '@mui/icons-material';

export const ExecutionResultPanel = ({ 
  output, 
  error, 
  isExecuting,
  theme,
  consoleOutput 
}) => {
  const [activeTab, setActiveTab] = useState(0);
  
  return (
    <Paper elevation={2} sx={{ 
      p: 2, 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      minHeight: '300px'
    }}>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs 
          value={activeTab} 
          onChange={(e, newValue) => setActiveTab(newValue)}
          variant="scrollable"
        >
          <Tab label="执行结果" icon={<CodeIcon fontSize="small" />} />
          <Tab label="终端输出" icon={<ConsoleIcon fontSize="small" />} />
        </Tabs>
      </div>

      {activeTab === 0 ? (
        <>
          {error ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          ) : null}
          
          {isExecuting ? (
            <Box sx={{ 
              flexGrow: 1,
              display: 'flex', 
              justifyContent: 'center', 
              alignItems: 'center',
              height: '100%'
            }}>
              <CircularProgress />
              <Typography variant="body1" sx={{ ml: 2 }}>正在执行代码...</Typography>
            </Box>
          ) : output ? (
            <Box sx={{ 
              flexGrow: 1,
              fontFamily: '"Roboto Mono", monospace', 
              whiteSpace: 'pre-wrap', 
              backgroundColor: theme.palette.background.paper,
              p: 2,
              borderRadius: 1,
              border: `1px solid ${theme.palette.divider}`,
              overflow: 'auto'
            }}>
              {output}
            </Box>
          ) : (
            <Box sx={{ 
              flexGrow: 1,
              display: 'flex', 
              justifyContent: 'center', 
              alignItems: 'center',
              color: theme.palette.text.secondary
            }}>
              <Typography variant="body1">执行结果将显示在这里</Typography>
            </Box>
          )}
        </>
      ) : (
        <Box sx={{
          flexGrow: 1,
          fontFamily: '"Roboto Mono", monospace',
          whiteSpace: 'pre-wrap',
          backgroundColor: theme.palette.background.default,
          p: 2,
          borderRadius: 1,
          overflow: 'auto',
          fontSize: '0.8rem'
        }}>
          {consoleOutput || "终端输出将显示在这里"}
        </Box>
      )}
    </Paper>
  );
};