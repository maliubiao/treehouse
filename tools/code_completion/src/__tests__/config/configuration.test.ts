import { 
  getAiServiceConfigs, 
  saveAiServiceConfigs, 
  getActiveAiServiceConfig, 
  setActiveAiService,
  AiServiceConfig 
} from '../../config/configuration';
import * as vscode from 'vscode';

// Mock vscode
const mockGetConfiguration = jest.fn();
const mockUpdate = jest.fn();

jest.mock('vscode', () => ({
  workspace: {
    getConfiguration: () => ({
      get: mockGetConfiguration,
      update: mockUpdate
    })
  },
  ConfigurationTarget: {
    Global: 1
  }
}));

describe('configuration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getAiServiceConfigs', () => {
    it('should return empty array when no services configured', () => {
      mockGetConfiguration.mockReturnValue([]);
      
      const result = getAiServiceConfigs();
      
      expect(result).toEqual([]);
      expect(mockGetConfiguration).toHaveBeenCalledWith('services', []);
    });

    it('should return configured services', () => {
      const mockServices: AiServiceConfig[] = [
        {
          name: 'test-service',
          max_context_size: 128000,
          max_tokens: 4000,
          is_thinking: false,
          temperature: 0.7,
          key: 'test-key',
          base_url: 'https://api.test.com',
          model_name: 'test-model',
          price_1M_input: 0.01,
          price_1M_output: 0.02,
          supports_json_output: true,
          timeout_seconds: 60
        }
      ];
      mockGetConfiguration.mockReturnValue(mockServices);
      
      const result = getAiServiceConfigs();
      
      expect(result).toEqual(mockServices);
    });
  });

  describe('saveAiServiceConfigs', () => {
    it('should save services to configuration', async () => {
      const services: AiServiceConfig[] = [
        {
          name: 'test-service',
          max_context_size: 128000,
          max_tokens: 4000,
          is_thinking: false,
          temperature: 0.7,
          key: 'test-key',
          base_url: 'https://api.test.com',
          model_name: 'test-model',
          price_1M_input: 0.01,
          price_1M_output: 0.02,
          supports_json_output: true,
          timeout_seconds: 60
        }
      ];
      
      await saveAiServiceConfigs(services);
      
      expect(mockUpdate).toHaveBeenCalledWith('services', services, vscode.ConfigurationTarget.Global);
    });
  });

  describe('getActiveAiServiceConfig', () => {
    it('should return undefined when no services exist', () => {
      mockGetConfiguration.mockImplementation((key: string) => {
        if (key === 'services') return [];
        if (key === 'activeService') return 'some-service';
        return undefined;
      });
      
      const result = getActiveAiServiceConfig();
      
      expect(result).toBeUndefined();
    });

    it('should return undefined when no active service set', () => {
        const mockServices: AiServiceConfig[] = [
            { name: 'service1' } as AiServiceConfig,
            { name: 'service2' } as AiServiceConfig
        ];
        mockGetConfiguration.mockImplementation((key: string) => {
            if (key === 'services') return mockServices;
            if (key === 'activeService') return undefined; // No active service name
            return undefined;
        });

      const result = getActiveAiServiceConfig();
      
      expect(result).toBeUndefined();
    });

    it('should return active service by name', () => {
      const services: AiServiceConfig[] = [
        { name: 'service1' } as AiServiceConfig,
        { name: 'active-service', key: 'key2' } as AiServiceConfig
      ];
      
      mockGetConfiguration.mockImplementation((key: string) => {
        if (key === 'services') return services;
        if (key === 'activeService') return 'active-service';
        return undefined;
      });
        
      const result = getActiveAiServiceConfig();
      
      expect(result).toEqual(services[1]);
    });

    it('should return undefined when active service not found', () => {
      const services: AiServiceConfig[] = [
        { name: 'service1' } as AiServiceConfig
      ];
      
      mockGetConfiguration.mockImplementation((key: string) => {
        if (key === 'services') return services;
        if (key === 'activeService') return 'nonexistent-service';
        return undefined;
      });
        
      const result = getActiveAiServiceConfig();
      
      expect(result).toBeUndefined();
    });
  });

  describe('setActiveAiService', () => {
    it('should set the active service name', async () => {
      await setActiveAiService('test-service');
      
      expect(mockUpdate).toHaveBeenCalledWith('activeService', 'test-service', vscode.ConfigurationTarget.Global);
    });
  });
});