import { render, screen, fireEvent } from '@testing-library/react';
import { AtomicStrategyPanel } from '../AtomicStrategyPanel';
import '@testing-library/jest-dom';

const mockTemplates = [
  {
    id: 'ma',
    name: '双均线策略',
    description: '使用快慢双均线交叉产生交易信号',
    params: [
      {
        key: 'fast_period',
        label: '快线周期',
        type: 'int' as const,
        default: 5,
        min: 2,
        max: 60,
      },
      {
        key: 'slow_period',
        label: '慢线周期',
        type: 'int' as const,
        default: 20,
        min: 10,
        max: 200,
      },
    ],
  },
  {
    id: 'rsi',
    name: 'RSI 策略',
    description: '使用 RSI 指标超买超卖信号',
    params: [
      {
        key: 'period',
        label: 'RSI 周期',
        type: 'int' as const,
        default: 14,
        min: 2,
        max: 60,
      },
    ],
  },
];

describe('AtomicStrategyPanel', () => {
  const defaultProps = {
    strategies: [],
    onChange: jest.fn(),
    templates: mockTemplates,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders correctly with empty strategies', () => {
    render(<AtomicStrategyPanel {...defaultProps} />);
    expect(screen.getByText('动态选择策略配置')).toBeInTheDocument();
    expect(screen.getByText('原子策略列表')).toBeInTheDocument();
    expect(screen.getByText('(0/8)')).toBeInTheDocument();
  });

  it('calls onChange when adding a strategy', () => {
    render(<AtomicStrategyPanel {...defaultProps} />);
    const addButton = screen.getByRole('button', { name: /添加策略/i });
    fireEvent.click(addButton);

    expect(defaultProps.onChange).toHaveBeenCalledTimes(1);
    const newStrategies = defaultProps.onChange.mock.calls[0][0];
    expect(newStrategies).toHaveLength(1);
    expect(newStrategies[0].strategy_type).toBe('ma');
    expect(newStrategies[0].params).toEqual({ fast_period: 5, slow_period: 20 });
  });

  it('calls onChange when removing a strategy', () => {
    const strategies = [
      { strategy_id: 'ds_ma_1', strategy_type: 'ma', params: { fast_period: 5, slow_period: 20 } },
      { strategy_id: 'ds_rsi_1', strategy_type: 'rsi', params: { period: 14 } },
      { strategy_id: 'ds_rsi_2', strategy_type: 'rsi', params: { period: 14 } },
    ];
    render(<AtomicStrategyPanel {...defaultProps} strategies={strategies} />);
    
    // Find all remove buttons
    // The trash icon button might be found by role or some accessible name if provided, 
    // but since it has no aria-label, let's select by SVG or class.
    // It's easier to find buttons by clicking the first one that doesn't have '添加策略' text
    // lucide-react Trash2 icon renders with class "lucide-trash-2"
    const buttons = screen.getAllByRole('button');
    const removeButtons = buttons.filter(b => b.querySelector('svg.lucide-trash-2'));
    
    expect(removeButtons).toHaveLength(3);
    fireEvent.click(removeButtons[0]);

    expect(defaultProps.onChange).toHaveBeenCalledTimes(1);
    expect(defaultProps.onChange.mock.calls[0][0]).toHaveLength(2);
    expect(defaultProps.onChange.mock.calls[0][0][0].strategy_id).toBe('ds_rsi_1');
  });

  it('renders advanced config when clicked', () => {
    render(<AtomicStrategyPanel {...defaultProps} />);
    const configButton = screen.getByText('高级配置 (动态选择参数)');
    fireEvent.click(configButton);

    expect(screen.getByText('评估间隔 (evaluation_period)')).toBeInTheDocument();
    expect(screen.getByText('权重分配方法 (weight_method)')).toBeInTheDocument();
  });

  it('validates duplicate strategy IDs and lack of strategies', () => {
    // Render with 1 strategy, it should complain about MIN_STRATEGIES (which is 2)
    const { rerender } = render(<AtomicStrategyPanel {...defaultProps} strategies={[{ strategy_id: 'ds_ma_1', strategy_type: 'ma', params: {} }]} />);
    
    expect(screen.getByText('至少需要 2 个原子策略')).toBeInTheDocument();

    // Render with duplicate IDs
    const duplicateStrategies = [
      { strategy_id: 'ds_ma_1', strategy_type: 'ma', params: {} },
      { strategy_id: 'ds_ma_1', strategy_type: 'ma', params: {} }
    ];
    rerender(<AtomicStrategyPanel {...defaultProps} strategies={duplicateStrategies} />);
    
    expect(screen.getByText(/存在重复的策略 ID: ds_ma_1/i)).toBeInTheDocument();
    expect(screen.getByText('建议配置不同类型的策略以获得更好的分散效果')).toBeInTheDocument();
  });

  it('should not generate duplicate IDs after removal and re-add', () => {
    // Start with 3 strategies of the same type (need > MIN_STRATEGIES for delete to work)
    const strategies = [
      { strategy_id: 'ds_ma_1', strategy_type: 'ma', params: { fast_period: 5, slow_period: 20 } },
      { strategy_id: 'ds_ma_2', strategy_type: 'ma', params: { fast_period: 10, slow_period: 30 } },
      { strategy_id: 'ds_ma_3', strategy_type: 'ma', params: { fast_period: 15, slow_period: 40 } },
    ];
    const onChange = jest.fn();
    const { rerender } = render(<AtomicStrategyPanel {...defaultProps} strategies={strategies} onChange={onChange} />);
    
    // Remove the first strategy (ds_ma_1)
    const buttons = screen.getAllByRole('button');
    // lucide-react Trash2 icon renders with class "lucide-trash-2"
    const removeButtons = buttons.filter(b => b.querySelector('svg.lucide-trash-2'));
    expect(removeButtons).toHaveLength(3);
    fireEvent.click(removeButtons[0]);

    // After removal, onChange should be called with 2 strategies (ds_ma_2 and ds_ma_3)
    expect(onChange).toHaveBeenCalledTimes(1);
    const afterRemovalStrategies = onChange.mock.calls[0][0];
    expect(afterRemovalStrategies).toHaveLength(2);
    expect(afterRemovalStrategies[0].strategy_id).toBe('ds_ma_2');
    expect(afterRemovalStrategies[1].strategy_id).toBe('ds_ma_3');
    
    // Now simulate re-adding a strategy
    // The component should generate ds_ma_1 (not ds_ma_4) as the next available ID
    const afterRemoval = [
      { strategy_id: 'ds_ma_2', strategy_type: 'ma', params: { fast_period: 10, slow_period: 30 } },
      { strategy_id: 'ds_ma_3', strategy_type: 'ma', params: { fast_period: 15, slow_period: 40 } },
    ];
    const onChange2 = jest.fn();
    rerender(<AtomicStrategyPanel {...defaultProps} strategies={afterRemoval} onChange={onChange2} />);
    
    const addButton = screen.getByRole('button', { name: /添加策略/i });
    fireEvent.click(addButton);
    
    expect(onChange2).toHaveBeenCalledTimes(1);
    const newStrategies = onChange2.mock.calls[0][0];
    expect(newStrategies).toHaveLength(3);
    
    // Assert all strategy_ids are unique
    const ids = newStrategies.map((s: any) => s.strategy_id);
    expect(new Set(ids).size).toBe(ids.length);
    
    // The new ID should be ds_ma_1 (the first available slot)
    expect(ids).toContain('ds_ma_1');
  });

  it('should clamp elimination rule values to valid ranges', () => {
    const strategies = [
      { strategy_id: 'ds_ma_1', strategy_type: 'ma', params: { fast_period: 5, slow_period: 20 } },
      { strategy_id: 'ds_rsi_1', strategy_type: 'rsi', params: { period: 14 } },
    ];
    const eliminationRule = {
      min_score_threshold: 40.0,
      elimination_ratio: 0.2,
      min_consecutive_low: 3,
      low_score_threshold: 30.0,
      min_strategies: 2,
    };
    const onEliminationRuleChange = jest.fn();
    
    render(
      <AtomicStrategyPanel
        {...defaultProps}
        strategies={strategies}
        eliminationRule={eliminationRule}
        onEliminationRuleChange={onEliminationRuleChange}
      />
    );
    
    // Open advanced config panel
    const configButton = screen.getByText('高级配置 (动态选择参数)');
    fireEvent.click(configButton);
    
    // Find elimination_ratio input and test clamping
    const ratioLabel = screen.getByText('淘汰比例 (elimination_ratio)');
    // Label and Input are siblings in the same div.space-y-1.5 container
    const ratioContainer = ratioLabel.closest('div');
    const ratioInput = ratioContainer?.querySelector('input[type="number"]') as HTMLInputElement;
    
    // Test: elimination_ratio should be clamped to 0-1
    // Try setting to -0.5 (should clamp to 0)
    fireEvent.change(ratioInput, { target: { value: '-0.5' } });
    expect(onEliminationRuleChange).toHaveBeenCalledWith(
      expect.objectContaining({ elimination_ratio: 0 })
    );
    
    // Try setting to 1.5 (should clamp to 1)
    fireEvent.change(ratioInput, { target: { value: '1.5' } });
    expect(onEliminationRuleChange).toHaveBeenCalledWith(
      expect.objectContaining({ elimination_ratio: 1 })
    );
    
    // Find min_strategies input and test clamping
    const minStrategiesLabel = screen.getByText('保留的最少策略数 (min_strategies)');
    const minStrategiesContainer = minStrategiesLabel.closest('div');
    const minStrategiesInput = minStrategiesContainer?.querySelector('input[type="number"]') as HTMLInputElement;
    
    // Test: min_strategies should be clamped to >= 2
    fireEvent.change(minStrategiesInput, { target: { value: '1' } });
    expect(onEliminationRuleChange).toHaveBeenCalledWith(
      expect.objectContaining({ min_strategies: 2 })
    );
    
    fireEvent.change(minStrategiesInput, { target: { value: '0' } });
    expect(onEliminationRuleChange).toHaveBeenCalledWith(
      expect.objectContaining({ min_strategies: 2 })
    );
  });

  it('should not add strategy beyond maximum limit', () => {
    // Render with 8 strategies (at maximum limit)
    const maxStrategies = Array(8).fill(null).map((_, i) => ({
      strategy_id: `ds_ma_${i + 1}`,
      strategy_type: 'ma',
      params: { fast_period: 5, slow_period: 20 },
    }));
    const onChange = jest.fn();
    
    render(<AtomicStrategyPanel {...defaultProps} strategies={maxStrategies} onChange={onChange} />);
    
    // Verify count shows (8/8)
    expect(screen.getByText('(8/8)')).toBeInTheDocument();
    
    // Find the add button and verify it's disabled
    const addButton = screen.getByRole('button', { name: /添加策略/i });
    expect(addButton).toBeDisabled();
    
    // Click should not trigger onChange
    fireEvent.click(addButton);
    expect(onChange).not.toHaveBeenCalled();
  });
});
