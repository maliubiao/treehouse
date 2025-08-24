import { useDispatch, useSelector } from 'react-redux';
import { addFavorite, removeFavorite } from '../features/favoritesSlice';

export const useFavorites = () => {
  const dispatch = useDispatch();
  const favorites = useSelector(state => state.favorites.items);
  
  return {
    favorites,
    addFavorite: (item) => dispatch(addFavorite(item)),
    removeFavorite: (id) => dispatch(removeFavorite(id))
  };
};