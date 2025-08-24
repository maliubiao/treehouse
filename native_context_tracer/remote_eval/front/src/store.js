import { configureStore } from '@reduxjs/toolkit';
import { persistStore, persistReducer } from 'redux-persist';
import storage from 'redux-persist/lib/storage';
import codeReducer from './features/codeSlice';
import historyReducer from './features/historySlice';
import favoritesReducer from './features/favoritesSlice';
import themeReducer from './features/themeSlice';
import serverReducer from './features/serverSlice';

const persistConfig = {
  key: 'root',
  storage,
  whitelist: ['theme', 'favorites', 'history', 'server']
};

const codePersistConfig = {
  key: 'code',
  storage,
  blacklist: ['isExecuting']
};

export const store = configureStore({
  reducer: {
    code: persistReducer(codePersistConfig, codeReducer),
    history: persistReducer(persistConfig, historyReducer),
    favorites: persistReducer(persistConfig, favoritesReducer),
    theme: persistReducer(persistConfig, themeReducer),
    server: persistReducer(persistConfig, serverReducer)
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: false
    })
});

export const persistor = persistStore(store);