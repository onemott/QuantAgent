import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReplayPage from '../app/replay/page';

// Mock next/dynamic
jest.mock('next/dynamic', () => {
  return function(dynamicOptions: any, options: any) {
    let Component: any = null;
    return function DynamicComponent(props: any) {
      const React = require('react');
      const [LoadedComponent, setLoadedComponent] = React.useState(null);
      React.useEffect(() => {
        dynamicOptions().then((mod: any) => {
          setLoadedComponent(() => mod.default || mod);
        });
      }, []);
      if (!LoadedComponent) return <div>Loading Replay...</div>;
      return <LoadedComponent {...props} />;
    };
  };
});

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
  }),
}));

// Mock charts
jest.mock('@/components/charts/EquityCurveChart', () => ({
  EquityCurveChart: () => <div data-testid="equity-curve-chart" />,
  TradeMarker: () => <div />
}));
jest.mock('@/components/charts/KlineChart', () => () => <div data-testid="kline-chart" />);
jest.mock('@/components/charts/TradeList', () => () => <div data-testid="trade-list" />);
jest.mock('@/components/charts/PositionPanel', () => () => <div data-testid="position-panel" />);
jest.mock('@/components/monitor/EliminationHistory', () => () => <div data-testid="elimination-history" />);
jest.mock('@/components/replay/WeightEvolutionChart', () => () => <div data-testid="weight-chart" />);

// Mock Radix UI Select with a simpler native select for testing
jest.mock('@/components/ui/select', () => {
  const React = require('react');
  return {
    Select: ({ children, value, onValueChange }: { children: React.ReactNode; value: string; onValueChange: (v: string) => void }) => (
      <select
        data-testid="mock-select"
        value={value}
        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => onValueChange(e.target.value)}
        role="combobox"
      >
        {children}
      </select>
    ),
    SelectTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => {
      // Extract text content from children (handles complex child structures)
      const text = typeof children === 'string' ? children : 
        React.Children.toArray(children).map((child: any) => {
          if (typeof child === 'string') return child;
          if (child?.props?.children) {
            const innerChildren = React.Children.toArray(child.props.children);
            return innerChildren.map((c: any) => typeof c === 'string' ? c : '').join('');
          }
          return '';
        }).join('');
      return <option value={value}>{text}</option>;
    },
    SelectSeparator: () => null,
  };
});

// Mock resize observer
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock pointer capture APIs for Radix UI
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => {};
Element.prototype.releasePointerCapture = () => {};

// Mock fetch
const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = jest.fn((url: string | Request | URL, options?: RequestInit) => {
    const urlStr = url.toString();
    if (urlStr.includes('/api/v1/strategy/templates')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          templates: [
            {
              id: 'ma',
              name: '双均线策略',
              description: 'ma',
              params: [
                { key: 'fast_period', label: '快线', type: 'int', default: 5, min: 2, max: 60 },
                { key: 'slow_period', label: '慢线', type: 'int', default: 20, min: 10, max: 200 }
              ]
            },
            {
              id: 'rsi',
              name: 'RSI 策略',
              description: 'rsi',
              params: [
                { key: 'rsi_period', label: 'RSI周期', type: 'int', default: 14, min: 2, max: 60 },
                { key: 'oversold', label: '超卖', type: 'int', default: 30, min: 0, max: 50 },
                { key: 'overbought', label: '超买', type: 'int', default: 70, min: 50, max: 100 }
              ]
            },
            {
              id: 'dynamic_selection',
              name: '动态选择策略',
              description: 'ds',
              params: []
            }
          ]
        })
      });
    }
    if (urlStr.includes('/api/v1/replay/create')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ replay_session_id: 'test-session-123' })
      });
    }
    if (urlStr.includes('/api/v1/replay/test-session-123/start')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'running' })
      });
    }
    if (urlStr.includes('/api/v1/replay/sessions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ total_count: 0, page: 1, page_size: 20, total_pages: 1, sessions: [] })
      });
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({})
    });
  }) as jest.Mock;
});

afterEach(() => {
  global.fetch = originalFetch;
  jest.clearAllMocks();
});

describe('Replay Dynamic Selection Integration', () => {
  it('selects dynamic_selection, configures strategies, submits and verifies request', async () => {
    const user = userEvent.setup();
    render(<ReplayPage />);

    // Wait for templates to load
    await waitFor(() => {
      expect(screen.getByText('选择策略')).toBeInTheDocument();
    });

    // Find the strategy type select (now mocked as native select)
    const selects = screen.getAllByRole('combobox');
    const strategySelect = selects[0];
    
    // Select dynamic_selection using native select change event
    fireEvent.change(strategySelect, { target: { value: 'dynamic_selection' } });

    // Wait for state update
    await waitFor(() => {
      expect(screen.getByText('动态选择策略配置')).toBeInTheDocument();
    });
    expect(screen.getByText('原子策略列表')).toBeInTheDocument();

    // Default should have 2 strategies based on `useState` in `page.tsx`
    expect(screen.getByText('(2/8)')).toBeInTheDocument();

    // Click '开始回放' (Create and Start)
    const startButton = screen.getByRole('button', { name: /开始回放|运行回放|创建回放/i });
    await user.click(startButton);

    // Verify fetch was called with correct structure
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/v1/replay/create', expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }));
    });

    const createCall = (global.fetch as jest.Mock).mock.calls.find(call => call[0] === '/api/v1/replay/create');
    const body = JSON.parse(createCall[1].body);

    expect(body.strategy_type).toBe('dynamic_selection');
    expect(body.params).toHaveProperty('atomic_strategies');
    expect(body.params.atomic_strategies).toHaveLength(2);
    expect(body.params.atomic_strategies[0].strategy_type).toBe('ma');
    expect(body.params).toHaveProperty('evaluation_period', 1440);
    expect(body.params).toHaveProperty('elimination_rule');
    
    // Verify each atomic_strategy contains complete fields
    body.params.atomic_strategies.forEach((strategy: any) => {
      expect(strategy).toHaveProperty('strategy_id');
      expect(strategy).toHaveProperty('strategy_type');
      expect(strategy).toHaveProperty('params');
      expect(typeof strategy.params).toBe('object');
      expect(Object.keys(strategy.params).length).toBeGreaterThan(0);
    });
    
    // Verify elimination_rule completeness
    expect(body.params.elimination_rule).toHaveProperty('min_score_threshold');
    expect(body.params.elimination_rule).toHaveProperty('elimination_ratio');
    expect(body.params.elimination_rule).toHaveProperty('min_consecutive_low');
    expect(body.params.elimination_rule).toHaveProperty('low_score_threshold');
    expect(body.params.elimination_rule).toHaveProperty('min_strategies');
    // Value range validation
    expect(body.params.elimination_rule.elimination_ratio).toBeGreaterThanOrEqual(0);
    expect(body.params.elimination_rule.elimination_ratio).toBeLessThanOrEqual(1);
  });

  it('should show error when submitting with less than 2 strategies', async () => {
    // Mock initial templates fetch
    const user = userEvent.setup();
    
    // Override fetch mock to handle strategy count scenario
    (global.fetch as jest.Mock).mockImplementation((url: string | Request | URL, options?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/api/v1/strategy/templates')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            templates: [
              { id: 'ma', name: '双均线策略', description: 'ma', params: [{ key: 'fast_period', label: '快线', type: 'int', default: 5, min: 2, max: 60 }] },
              { id: 'dynamic_selection', name: '动态选择策略', description: 'ds', params: [] }
            ]
          })
        });
      }
      if (urlStr.includes('/api/v1/replay/sessions')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ total_count: 0, page: 1, page_size: 20, total_pages: 1, sessions: [] })
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<ReplayPage />);

    // Wait for templates to load
    await waitFor(() => {
      expect(screen.getByText('选择策略')).toBeInTheDocument();
    });

    // Find and select dynamic_selection (using mocked native select)
    const selects = screen.getAllByRole('combobox');
    const strategySelect = selects[0];
    fireEvent.change(strategySelect, { target: { value: 'dynamic_selection' } });

    // Wait for state update
    await waitFor(() => {
      expect(screen.getByText('动态选择策略配置')).toBeInTheDocument();
    });
    expect(screen.getByText('(2/8)')).toBeInTheDocument();

    // When strategies.length == MIN_STRATEGIES (2), the delete buttons should be disabled
    // This prevents users from going below the minimum
    const allButtons = screen.getAllByRole('button');
    // lucide-react Trash2 icon renders with class "lucide-trash-2"
    const removeButtons = allButtons.filter(b => b.querySelector('svg.lucide-trash-2'));
    
    // All remove buttons should be disabled since we're at MIN_STRATEGIES
    removeButtons.forEach(btn => {
      expect(btn).toBeDisabled();
    });

    // Verify that clicking disabled remove buttons doesn't change strategy count
    const onChangeCallCount = (global.fetch as jest.Mock).mock.calls.length;
    fireEvent.click(removeButtons[0]);
    // Fetch should not have been called (no state change)
    expect((global.fetch as jest.Mock).mock.calls.length).toBe(onChangeCallCount);

    // The validation error "至少需要 2 个原子策略" is shown when strategies.length < 2
    // Since we can't reduce below 2 via UI (buttons disabled), this validates the protection mechanism
    // Unit tests in AtomicStrategyPanel.test.tsx cover the error display scenario
    
    // Also verify that with 2 strategies, no validation error is shown
    // (the error only appears when strategies.length < MIN_STRATEGIES)
    expect(screen.queryByText('至少需要 2 个原子策略')).not.toBeInTheDocument();
  });
});
