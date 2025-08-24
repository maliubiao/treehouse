import React, { useEffect, useState } from 'react';
import { 
  Box, 
  Container, 
  CssBaseline, 
  ThemeProvider, 
  createTheme,
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Tabs,
  Tab,
  Grid,
  Snackbar,
  Tooltip,
  Button,
  useMediaQuery
} from '@mui/material';
import { 
  Brightness4 as DarkIcon, 
  Brightness7 as LightIcon,
  History as HistoryIcon,
  Star as StarIcon,
  Settings as SettingsIcon,
  PlayArrow as ExecuteIcon
} from '@mui/icons-material';
import { useDispatch, useSelector } from 'react-redux';
import { toggleTheme } from './features/themeSlice';
import { testServerConnection } from './features/serverSlice';
import ServerDialog from './components/ServerDialog';
import { CodeEditorPanel } from './components/CodeEditorPanel';
import { ExecutionResultPanel } from './components/ExecutionResultPanel';
import { HistoryPanel } from './components/HistoryPanel';
import { FavoritesPanel } from './components/FavoritesPanel';
import { useCodeExecution } from './hooks/useCodeExecution';
import './App.css';

const getDesignTokens = (mode) => ({
  palette: {
    mode,
    ...(mode === 'light'
      ? {
          primary: { main: '#1976d2' },
          secondary: { main: '#9c27b0' },
          background: { default: '#f5f5f5' },
          editorBackground: '#ffffff'
        }
      : {
          primary: { main: '#90caf9' },
          secondary: { main: '#ce93d8' },
          background: { default: '#121212' },
          editorBackground: '#1e1e1e'
        }),
  },
  typography: {
    fontFamily: [
      'Roboto Mono',
      'monospace'
    ].join(','),
  },
});

const ServerStatusIndicator = () => {
  const { status, url } = useSelector(state => state.server);
  const dispatch = useDispatch();
  
  const statusColors = {
    connected: '#4caf50',
    connecting: '#ff9800',
    disconnected: '#f44336'
  };
  
  const handleTestConnection = async () => {
    await dispatch(testServerConnection());
  };

  return (
    <Tooltip title={
      <Box>
        <Typography variant="caption">服务器状态: {status}</Typography>
        <br/>
        <Typography variant="caption">地址: {url}</Typography>
        <br/>
        <Button 
          size="small" 
          onClick={handleTestConnection}
          sx={{ mt: 1 }}
        >
          重新测试连接
        </Button>
      </Box>
    }>
      <Box sx={{
        width: 12,
        height: 12,
        borderRadius: '50%',
        backgroundColor: statusColors[status],
        mr: 2,
        cursor: 'pointer',
        animation: status === 'connecting' ? 'pulse 1.5s infinite' : 'none'
      }} />
    </Tooltip>
  );
};

function App() {
  const themeMode = useSelector(state => state.theme.mode);
  const dispatch = useDispatch();
  const { 
    output, 
    isExecuting, 
    error,
    executeCode
  } = useCodeExecution();
  const [activeTab, setActiveTab] = React.useState(0);
  const [snackbarOpen, setSnackbarOpen] = React.useState(false);
  const [snackbarMessage, setSnackbarMessage] = React.useState('');
  const [showServerDialog, setShowServerDialog] = useState(false);
  
  const theme = createTheme(getDesignTokens(themeMode));
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

  const showSnackbar = (message) => {
    setSnackbarMessage(message);
    setSnackbarOpen(true);
  };

  // 键盘快捷键
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        executeCode();
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [executeCode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <AppBar position="static" color="default" elevation={1}>
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
              <Box component="span" sx={{ color: 'primary.main' }}>Python</Box> 远程调试器
            </Typography>
            <ServerStatusIndicator />
            <Tooltip title="服务器设置">
              <IconButton 
                onClick={() => setShowServerDialog(true)}
                color="inherit"
              >
                <SettingsIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title="切换主题">
              <IconButton onClick={() => dispatch(toggleTheme())} color="inherit">
                {themeMode === 'dark' ? <LightIcon /> : <DarkIcon />}
              </IconButton>
            </Tooltip>
          </Toolbar>
        </AppBar>
        
        {/* 移除最大宽度限制，让内容区域填充整个宽度 */}
        <Box sx={{ flexGrow: 1, py: 2, px: isMobile ? 0 : 2 }}>
          <Container maxWidth={false} disableGutters>
            <Tabs 
              value={activeTab} 
              onChange={(e, newValue) => setActiveTab(newValue)}
              variant={isMobile ? "scrollable" : "standard"}
              scrollButtons="auto"
              sx={{ mb: 2 }}
            >
              <Tab label="代码编辑器" icon={<ExecuteIcon />} />
              <Tab label="执行历史" icon={<HistoryIcon />} />
              <Tab label="收藏片段" icon={<StarIcon />} />
            </Tabs>
            
            {activeTab === 0 && (
              // 升级到 Grid v2: 移除 item 属性，使用 size 属性，添加宽度设置
              <Grid 
                container 
                spacing={2} 
                sx={{ 
                  minHeight: '65vh',
                  width: '100%', // 确保容器占满宽度
                  flexGrow: 1,   // 在 flex 布局中扩展
                  disableEqualOverflow: true // 保持负边距行为
                }}
              >
                {/* 在大屏幕上增加代码编辑器占比 */}
                <Grid size={{ xs: 12, lg: 8, xl: 9 }}>
                  <CodeEditorPanel themeMode={themeMode} />
                </Grid>
                
                <Grid size={{ xs: 12, lg: 4, xl: 3 }}>
                  <ExecutionResultPanel 
                    output={output}
                    error={error}
                    isExecuting={isExecuting}
                    theme={theme}
                  />
                </Grid>
              </Grid>
            )}

            {activeTab === 1 && (
              <HistoryPanel theme={theme} />
            )}

            {activeTab === 2 && (
              <FavoritesPanel theme={theme} />
            )}
          </Container>
        </Box>

        <Box component="footer" sx={{ py: 1, px: 2, backgroundColor: theme.palette.background.paper, mt: 'auto' }}>
          <Typography variant="body2" color="text.secondary" align="center">
            Python远程调试器 © {new Date().getFullYear()} | 保留断点处的完整执行上下文
          </Typography>
        </Box>

        <Snackbar
          open={snackbarOpen}
          autoHideDuration={3000}
          onClose={() => setSnackbarOpen(false)}
          message={snackbarMessage}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        />

        {showServerDialog && (
          <ServerDialog
            open={showServerDialog}
            onClose={() => setShowServerDialog(false)}
          />
        )}
      </Box>
    </ThemeProvider>
  );
}

export default App;