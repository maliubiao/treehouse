import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  CircularProgress,
  Alert,
  Box,
  Typography
} from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { setServerUrl, testServerConnection } from '../features/serverSlice';

const ServerDialog = ({ open, onClose }) => {
  const dispatch = useDispatch();
  const { url, status } = useSelector(state => state.server);
  const [inputUrl, setInputUrl] = useState(url);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const success = await dispatch(testServerConnection(inputUrl));
      setTestResult({
        type: success ? 'success' : 'error',
        message: success ? '连接成功' : '连接失败'
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = () => {
    dispatch(setServerUrl(inputUrl));
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center">
          <Typography variant="h6" component="div">
            服务器设置
          </Typography>
        </Box>
      </DialogTitle>
      <DialogContent>
        <Box my={2}>
          <TextField
            fullWidth
            label="服务器地址"
            variant="outlined"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            placeholder="例: http://localhost:5000"
          />
        </Box>
        
        {testResult && (
          <Alert severity={testResult.type} sx={{ mb: 2 }}>
            {testResult.message}
          </Alert>
        )}

        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Button
            variant="contained"
            onClick={handleTest}
            disabled={isTesting}
            startIcon={isTesting ? <CircularProgress size={20} /> : null}
          >
            {isTesting ? '测试中...' : '测试连接'}
          </Button>
          
          <Typography variant="body2" color="textSecondary">
            当前状态: {status}
          </Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button 
          onClick={handleSave} 
          color="primary"
          disabled={!inputUrl.startsWith('http')}
        >
          保存设置
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ServerDialog;