// Jest setup file for DOM testing
require('@testing-library/jest-dom');

// Add missing globals for jsdom
const { TextEncoder, TextDecoder } = require('util');
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// Mock global objects that would be available in browser
const { JSDOM } = require('jsdom');

const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
  url: 'http://localhost',
});

global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;

// Mock localStorage and sessionStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};

global.localStorage = localStorageMock;

const sessionStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};

global.sessionStorage = sessionStorageMock;

// Mock matchMedia
global.matchMedia = jest.fn().mockImplementation(query => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: jest.fn(),
  removeListener: jest.fn(),
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  dispatchEvent: jest.fn(),
}));

// Mock requestAnimationFrame
global.requestAnimationFrame = jest.fn().mockImplementation(cb => {
  const id = Math.random();
  setTimeout(() => cb(), 0);
  return id;
});

global.cancelAnimationFrame = jest.fn();

// Mock clipboard API
global.navigator.clipboard = {
  writeText: jest.fn().mockResolvedValue(undefined),
  readText: jest.fn().mockResolvedValue(''),
};

// Mock fetch
global.fetch = jest.fn().mockResolvedValue({
  ok: true,
  json: jest.fn().mockResolvedValue({}),
  text: jest.fn().mockResolvedValue(''),
});

// Mock Prism for syntax highlighting
const Prism = {
  highlightElement: jest.fn(),
  languages: {},
};

global.Prism = Prism;

// Add prism theme element for theme testing
const prismTheme = document.createElement('link');
prismTheme.id = 'prism-theme';
document.head.appendChild(prismTheme);


// Mock global data that would be set by Python backend
beforeEach(() => {
  global.window.executedLines = {};
  global.window.sourceFiles = {};
  global.window.commentsData = {};
  global.window.lineComment = {};
  
  // Reset mocks
  jest.clearAllMocks();
});