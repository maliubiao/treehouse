import { useDispatch, useSelector } from 'react-redux';
import { 
  setCode, 
  setOutput, 
  setError, 
  setExecuting,
  setConsole 
} from '../features/codeSlice';
import { addHistoryItem } from '../features/historySlice';
import axios from 'axios';

export const useCodeExecution = () => {
  const dispatch = useDispatch();
  const { content, output, isExecuting, error, consoleOutput } = useSelector(state => state.code);
  
  const executeCode = async () => {
    if (!content.trim() || isExecuting) return;
    
    dispatch(setExecuting(true));
    try {
      const response = await axios.post('/execute', {
        code: content
      });
      
      dispatch(setOutput(response.data.output));
      dispatch(setConsole(response.data.console));
      dispatch(setError(response.data.error || ''));
      
      const newHistoryItem = {
        id: Date.now(),
        timestamp: new Date().toISOString(),
        code: content,
        output: response.data.output,
        console: response.data.console
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
    consoleOutput,
    isExecuting,
    error,
    setCode: (code) => dispatch(setCode(code)),
    executeCode
  };
};