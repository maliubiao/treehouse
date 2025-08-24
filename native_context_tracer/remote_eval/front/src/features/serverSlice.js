import { createSlice } from '@reduxjs/toolkit';

const initialServerConfig = {
  url: localStorage.getItem('serverUrl') || 'http://localhost:5000',
  status: 'disconnected',
  lastChecked: null,
  latency: null,
  error: null
};

export const serverSlice = createSlice({
  name: 'server',
  initialState: initialServerConfig,
  reducers: {
    setServerUrl: (state, action) => {
      state.url = action.payload;
      localStorage.setItem('serverUrl', action.payload);
    },
    setConnectionStatus: (state, action) => {
      Object.assign(state, action.payload);
      state.lastChecked = Date.now();
    },
    startConnectionTest: (state) => {
      state.status = 'connecting';
      state.error = null;
    }
  }
});

export const testServerConnection = (url) => async (dispatch, getState) => {
  const targetUrl = url || getState().server.url;
  dispatch(startConnectionTest());
  
  try {
    const startTime = Date.now();
    const response = await fetch(`${targetUrl}/health`, {
      signal: AbortSignal.timeout(3000)
    });
    const latency = Date.now() - startTime;
    
    if (response.ok) {
      const data = await response.json();
      dispatch(setConnectionStatus({
        status: 'connected',
        latency,
        error: null
      }));
      return true;
    }
    throw new Error(`HTTP ${response.status}`);
  } catch (error) {
    dispatch(setConnectionStatus({
      status: 'disconnected',
      error: error.message,
      latency: null
    }));
    return false;
  }
};

export const { setServerUrl, setConnectionStatus, startConnectionTest } = serverSlice.actions;
export default serverSlice.reducer;