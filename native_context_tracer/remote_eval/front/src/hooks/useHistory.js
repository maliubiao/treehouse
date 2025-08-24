import { useDispatch, useSelector } from 'react-redux';
import { addHistoryItem, clearHistory } from '../features/historySlice';

export const useHistory = () => {
  const dispatch = useDispatch();
  const history = useSelector(state => state.history.items);
  
  return {
    history,
    addHistoryItem: (item) => dispatch(addHistoryItem(item)),
    clearHistory: () => dispatch(clearHistory())
  };
};