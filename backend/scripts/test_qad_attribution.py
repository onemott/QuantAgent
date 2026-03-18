import pandas as pd
import numpy as np
import sys
import os

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.attribution_service import AttributionService

def test_qad_attribution():
    service = AttributionService()
    
    # 1. Prepare test data from SPEC 7.1
    # 信号表
    df_signals = pd.DataFrame([{
        'signal_id': 'SIG_001',
        'timestamp': pd.Timestamp('2026-03-17 09:35:00'),
        'symbol': '600519.SH',
        'direction': 1,
        'target_qty': 100,
        'trigger_price': 1800.0
    }])

    # 回测成交表（1笔成交）
    df_bt_exec = pd.DataFrame([{
        'signal_id': 'SIG_001',
        'exec_id': 'BT_001',
        'exec_ts': pd.Timestamp('2026-03-17 09:35:01'),
        'exec_price': 1800.0,
        'exec_qty': 100,
        'fee': 5.0
    }])

    # 模拟盘成交表（2笔成交，需聚合）
    df_sim_exec = pd.DataFrame([
        {
            'signal_id': 'SIG_001',
            'exec_id': 'SIM_001',
            'exec_ts': pd.Timestamp('2026-03-17 09:35:02'),
            'exec_price': 1800.5,
            'exec_qty': 50,
            'fee': 2.5
        },
        {
            'signal_id': 'SIG_001',
            'exec_id': 'SIM_002',
            'exec_ts': pd.Timestamp('2026-03-17 09:35:03'),
            'exec_price': 1801.0,
            'exec_qty': 30,
            'fee': 1.5
        }
    ])

    print("Step 1: Aggregating executions...")
    df_bt_agg = service.aggregate_executions(df_bt_exec, 'bt')
    df_sim_agg = service.aggregate_executions(df_sim_exec, 'sim')
    
    print(f"Aggregated BT: \n{df_bt_agg}")
    print(f"Aggregated SIM: \n{df_sim_agg}")
    
    # Expected values for SIM
    expected_sim_price = (1800.5 * 50 + 1801.0 * 30) / 80
    assert abs(df_sim_agg.loc[0, 'sim_price'] - expected_sim_price) < 0.0001
    assert df_sim_agg.loc[0, 'sim_qty'] == 80
    assert df_sim_agg.loc[0, 'sim_fee'] == 4.0
    print("Aggregation check passed.")

    print("\nStep 2: Merging data...")
    df_combined = service.merge_data(df_signals, df_bt_agg, df_sim_agg)
    print(f"Combined data: \n{df_combined}")
    assert df_combined.loc[0, 'bt_qty'] == 100
    assert df_combined.loc[0, 'sim_qty'] == 80
    print("Merge check passed.")

    print("\nStep 3: Calculating attribution...")
    df_attribution = service.calculate_attribution(df_combined)
    print(f"Attribution results: \n{df_attribution}")
    
    # Expected results from SPEC
    # 3. delta_price = (1800.6875 - 1800.0) * 80 * 1 = 55.0
    # 4. delta_fill = (-20) * 1800.0 * 1 = -36000.0
    # 5. delta_fees = 5.0 - 4.0 = 1.0
    # 6. delta_total = 55.0 - 36000.0 + 1.0 = -35944.0
    
    assert abs(df_attribution.loc[0, 'delta_price'] - 55.0) < 0.01
    assert abs(df_attribution.loc[0, 'delta_fill'] - (-36000.0)) < 0.01
    assert abs(df_attribution.loc[0, 'delta_fees'] - 1.0) < 0.01
    assert abs(df_attribution.loc[0, 'delta_total'] - (-35944.0)) < 0.01
    print("Attribution calculation check passed.")

    print("\nStep 4: Aggregating results...")
    results = service.aggregate_results(df_attribution)
    print(f"Global Aggregation: {results['global']}")
    
    assert abs(results['global']['delta_total'] - (-35944.0)) < 0.01
    print("Global aggregation check passed.")
    
    print("\nAll tests passed successfully!")

if __name__ == "__main__":
    test_qad_attribution()
