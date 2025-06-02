import React from 'react';
import { 
  Box, 
  Typography, 
  Paper,
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
  Star as StarIcon
} from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { useCodeExecution } from '../hooks/useCodeExecution';
import { useFavorites } from '../hooks/useFavorites';

export const FavoritesPanel = () => {
  const theme = useTheme();
  const { setCode } = useCodeExecution();
  const { favorites, removeFavorite } = useFavorites();
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

  const applyFavorite = (code) => {
    setCode(code);
  };

  return (
    <Paper elevation={2} sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" sx={{ fontWeight: 'bold' }}>
          收藏的代码片段
        </Typography>
        <Typography variant="body2" color="text.secondary">
          共 {favorites.length} 个收藏
        </Typography>
      </Box>
      
      {favorites.length === 0 ? (
        <Box sx={{ 
          display: 'flex', 
          justifyContent: 'center', 
          alignItems: 'center', 
          height: 200,
          color: theme.palette.text.secondary
        }}>
          <Typography variant="body1">暂无收藏片段</Typography>
        </Box>
      ) : (
        <List sx={{ maxHeight: 500, overflow: 'auto' }}>
          {favorites.map((fav) => (
            <React.Fragment key={fav.id}>
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
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mr: 1 }}>
                        {fav.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatDistanceToNow(new Date(fav.timestamp), { 
                          addSuffix: true, 
                          locale: zhCN 
                        })}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    <>
                      {fav.description && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          {fav.description}
                        </Typography>
                      )}
                      <Box 
                        component="pre" 
                        sx={{ 
                          fontFamily: '"Roboto Mono", monospace', 
                          fontSize: 12,
                          whiteSpace: 'pre-wrap',
                          maxHeight: expandedItems[fav.id] ? 'none' : 100,
                          overflow: 'hidden',
                          mt: 1,
                          backgroundColor: theme.palette.action.selected,
                          p: 1,
                          borderRadius: 1
                        }}
                      >
                        {fav.code}
                      </Box>
                    </>
                  }
                  secondaryTypographyProps={{ component: 'div' }}
                />
                <ListItemSecondaryAction>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Tooltip title="应用此代码">
                      <IconButton onClick={() => applyFavorite(fav.code)}>
                        <ExecuteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="复制代码">
                      <IconButton onClick={() => copyToClipboard(fav.code)}>
                        <CopyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={expandedItems[fav.id] ? "收起详情" : "展开详情"}>
                      <IconButton onClick={() => toggleExpandItem(fav.id)}>
                        {expandedItems[fav.id] ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="移除收藏">
                      <IconButton onClick={() => removeFavorite(fav.id)} color="error">
                        <StarIcon fontSize="small" />
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