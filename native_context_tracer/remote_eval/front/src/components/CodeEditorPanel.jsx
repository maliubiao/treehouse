import React, { useState, useRef, useEffect } from 'react';
import { 
  Box, 
  Typography, 
  Chip,
  Button,
  TextField,
  Tooltip,
  Paper,
  CircularProgress,
  useTheme,
  Grid
} from '@mui/material';
import { 
  PlayArrow as ExecuteIcon,
  Clear as ClearIcon,
  StarBorder as StarBorderIcon,
  Star as StarIcon
} from '@mui/icons-material';
import Editor from '@monaco-editor/react';
import { useCodeExecution } from '../hooks/useCodeExecution';
import { useFavorites } from '../hooks/useFavorites';

export const CodeEditorPanel = ({ themeMode }) => {
  const theme = useTheme();
  const {
    content,
    isExecuting,
    setCode,
    executeCode
  } = useCodeExecution();
  
  const { addFavorite } = useFavorites();
  const [favoriteName, setFavoriteName] = useState('');
  const [favoriteDescription, setFavoriteDescription] = useState('');
  const [showFavoriteForm, setShowFavoriteForm] = useState(false);
  const containerRef = useRef(null);
  const [editorHeight, setEditorHeight] = useState(400);

  // 根据容器高度计算编辑器高度
  useEffect(() => {
    const updateHeight = () => {
      if (containerRef.current) {
        const containerHeight = containerRef.current.clientHeight;
        // 保留操作区域高度
        const newHeight = Math.max(containerHeight - 120, 200);
        setEditorHeight(newHeight);
      }
    };

    updateHeight();
    window.addEventListener('resize', updateHeight);
    
    return () => window.removeEventListener('resize', updateHeight);
  }, []);

  const editorOptions = {
    minimap: { enabled: false },
    fontSize: 14,
    scrollBeyondLastLine: false,
    automaticLayout: true,
    lineNumbers: 'on',
    roundedSelection: false,
    scrollbar: {
      vertical: 'auto',
      horizontal: 'auto'
    },
    wordWrap: 'on',
    theme: themeMode === 'dark' ? 'vs-dark' : 'vs',
  };

  const handleAddToFavorites = () => {
    if (!favoriteName.trim() || !content.trim()) return;
    
    addFavorite({
      id: Date.now(),
      name: favoriteName,
      description: favoriteDescription,
      code: content,
      timestamp: new Date().toISOString()
    });
    
    setFavoriteName('');
    setFavoriteDescription('');
    setShowFavoriteForm(false);
  };

  return (
    <Paper 
      elevation={2} 
      sx={{ 
        p: 2, 
        height: '100%', 
        display: 'flex', 
        flexDirection: 'column',
        minHeight: '400px'
      }}
      ref={containerRef}
    >
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
          调试代码编辑器
        </Typography>
        <Chip 
          label="Python 3.9" 
          size="small" 
          color="secondary" 
          sx={{ fontWeight: 'bold' }}
        />
      </Box>
      
      <Box sx={{ flexGrow: 1, border: `1px solid ${theme.palette.divider}`, borderRadius: 1, minHeight: '200px' }}>
        <Editor
          height={`${editorHeight}px`}
          language="python"
          value={content}
          onChange={(value) => setCode(value)}
          options={editorOptions}
          loading={<CircularProgress />}
        />
      </Box>
      
      <Box sx={{ mt: 2 }}>
        {/* 升级到 Grid v2: 移除 item 属性 */}
        <Grid container spacing={1} alignItems="center">
          <Grid>
            <Button 
              variant="contained" 
              color="primary" 
              onClick={executeCode}
              disabled={isExecuting}
              startIcon={isExecuting ? <CircularProgress size={20} /> : <ExecuteIcon />}
            >
              {isExecuting ? '执行中...' : '执行'}
            </Button>
          </Grid>
          
          <Grid>
            <Button 
              variant="outlined" 
              color="secondary" 
              onClick={() => setCode('')}
              startIcon={<ClearIcon />}
            >
              清空
            </Button>
          </Grid>
          
          <Grid>
            <Tooltip title={showFavoriteForm ? "取消收藏" : "添加到收藏"}>
              <Button 
                variant="outlined" 
                color={showFavoriteForm ? "primary" : "secondary"}
                onClick={() => setShowFavoriteForm(!showFavoriteForm)}
                startIcon={showFavoriteForm ? <StarIcon /> : <StarBorderIcon />}
              >
                收藏
              </Button>
            </Tooltip>
          </Grid>
        </Grid>
        
        {showFavoriteForm && (
          <Box sx={{ mt: 2, borderTop: `1px solid ${theme.palette.divider}`, pt: 2 }}>
            {/* 升级到 Grid v2: 使用 size 属性 */}
            <Grid container spacing={2} alignItems="flex-end">
              <Grid size={{ xs: 12, sm: 5 }}>
                <TextField
                  fullWidth
                  label="收藏名称"
                  variant="outlined"
                  size="small"
                  value={favoriteName}
                  onChange={(e) => setFavoriteName(e.target.value)}
                  placeholder="必填"
                  autoFocus
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 5 }}>
                <TextField
                  fullWidth
                  label="收藏描述"
                  variant="outlined"
                  size="small"
                  value={favoriteDescription}
                  onChange={(e) => setFavoriteDescription(e.target.value)}
                  placeholder="可选"
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 2 }}>
                <Button 
                  fullWidth
                  variant="contained" 
                  color="primary" 
                  onClick={handleAddToFavorites}
                  disabled={!favoriteName.trim() || !content.trim()}
                >
                  添加
                </Button>
              </Grid>
            </Grid>
          </Box>
        )}
      </Box>
    </Paper>
  );
};