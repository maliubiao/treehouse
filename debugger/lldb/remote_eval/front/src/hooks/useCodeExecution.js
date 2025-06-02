import { useDispatch, useSelector } from 'react-redux';
import { 
  setCode, 
  setOutput, 
  setError, 
  setExecuting 
} from '../features/codeSlice';
import { addHistoryItem } from '../features/historySlice';
import axios from 'axios';

export const useCodeExecution = () => {
  const dispatch = useDispatch();
  const { content, output, isExecuting, error } = useSelector(state => state.code);
  
  const executeCode = async () => {
    if (!content.trim() || isExecuting) return;
    
    dispatch(setExecuting(true));
    try {
      const response = await axios.post('/evaluate', {
        code: content
      });
      
      const result = response.data.result || response.data.error;
      
      dispatch(setOutput(result));
      dispatch(setError(null));
      
      const newHistoryItem = {
        id: Date.now(),
        timestamp: new Date().toISOString(),
        code: content,
        output: result
      };
      
      dispatch(addHistoryItem(newHistoryItem));
    } catch (error) {
      const errorMsg = error.response?.data?.error || error.message || '未知错误';
      dispatch(setError(`执行错误: ${errorMsg}`));
    } finally {
      dispatch(setExecuting(false));
    }
  };

  return {
    content,
    output,
    isExecuting,
    error,
    setCode: (code) => dispatch(setCode(code)),
    executeCode,
    setOutput: (output) => dispatch(setOutput(output)),
    setError: (error) => dispatch(setError(error)),
    setExecuting: (isExecuting) => dispatch(setExecuting(isExecuting))
  };
};