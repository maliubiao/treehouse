import React from 'react';
import { 
  Box, 
  Typography, 
  Paper,
  Button,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Divider,
  Chip,
  IconButton,
  Tooltip,
  useTheme
} from '@mui/material';
import { 
  PlayArrow as ExecuteIcon,
  ContentCopy as CopyIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Delete as DeleteIcon
} from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { useCodeExecution } from '../hooks/useCodeExecution';
import { useHistory } from '../hooks/useHistory';

export const HistoryPanel = () => {
  const theme = useTheme();
  const { setCode } = useCodeExecution();
  const { history, clearHistory } = useHistory();
  const [expandedItems, setExpandedItems] = React.useState({});

  const toggleExpandItem = (id) => {
    setExpandedItems(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <Paper elevation={2} sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
          最近执行历史
        </Typography>
        <Button 
          variant="outlined" 
          color="error" 
          onClick={clearHistory}
          startIcon={<DeleteIcon />}
          disabled={history.length === 0}
        >
          清除历史
        </Button>
      </Box>
      
      {history.length === 0 ? (
        <Box sx={{ 
          display: 'flex', 
          justifyContent: 'center', 
          alignItems: 'center', 
          height: 200,
          color: theme.palette.text.secondary
        }}>
          <Typography variant="body1">暂无执行历史</Typography>
        </Box>
      ) : (
        <List sx={{ maxHeight: 500, overflow: 'auto' }}>
          {history.map((item) => (
            <React.Fragment key={item.id}>
              <ListItem 
                sx={{ 
                  backgroundColor: theme.palette.background.paper,
                  '&:hover': { backgroundColor: theme.palette.action.hover },
                  borderRadius: 1,
                  mb: 1
                }}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <Typography variant="body2" sx={{ fontWeight: 'bold', mr: 1 }}>
                        {formatDistanceToNow(new Date(item.timestamp), { 
                          addSuffix: true, 
                          locale: zhCN 
                        })}
                      </Typography>
                      <Chip 
                        label={item.output ? '成功' : '失败'} 
                        size="small" 
                        color={item.output ? 'success' : 'error'}
                        variant="outlined"
                      />
                    </Box>
                  }
                  secondary={
                    <Box>
                      <Box 
                        component="pre" 
                        sx={{ 
                          fontFamily: '"Roboto Mono", monospace', 
                          fontSize: 12,
                          whiteSpace: 'pre-wrap',
                          maxHeight: expandedItems[item.id] ? 'none' : 100,
                          overflow: 'hidden',
                          mt: 1
                        }}
                      >
                        {item.code}
                      </Box>
                      {expandedItems[item.id] && (
                        <Box sx={{ mt: 1 }}>
                          <Typography variant="body2" sx={{ fontWeight: 'bold' }}>输出:</Typography>
                          <Box 
                            component="pre" 
                            sx={{ 
                              fontFamily: '"Roboto Mono", monospace', 
                              fontSize: 12,
                              whiteSpace: 'pre-wrap',
                              backgroundColor: theme.palette.action.hover,
                              p: 1,
                              borderRadius: 1,
                              mt: 1
                            }}
                          >
                            {item.output}
                          </Box>
                        </Box>
                      )}
                    </Box>
                  }
                  secondaryTypographyProps={{ component: 'div' }}
                />
                <ListItemSecondaryAction>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Tooltip title="使用此代码">
                      <IconButton onClick={() => setCode(item.code)}>
                        <ExecuteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="复制代码">
                      <IconButton onClick={() => copyToClipboard(item.code)}>
                        <CopyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={expandedItems[item.id] ? "收起详情" : "展开详情"}>
                      <IconButton onClick={() => toggleExpandItem(item.id)}>
                        {expandedItems[item.id] ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                      </IconButton>
                    </Tooltip>
                  </Box>
                </ListItemSecondaryAction>
              </ListItem>
              <Divider />
            </React.Fragment>
          ))}
        </List>
      )}
    </Paper>
  );
};