
import numpy as np
from typing import List, Dict

class MockPerformanceService:
    RISK_FREE_RATE = 0.03

    def _calculate_volatility(self, returns: List[float]) -> float:
        """Calculate annualized volatility."""
        if not returns:
            return 0.0
        # The line we fixed:
        return float(np.std(returns) * np.sqrt(252))

    def calculate_metrics_mock(self, returns: List[float], annualized: float) -> Dict:
        volatility = self._calculate_volatility(returns)
        metrics = {}
        metrics["volatility"] = round(float(volatility * 100), 2)
        
        # Sortino ratio (downside volatility)
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_vol = float(np.std(downside_returns) * np.sqrt(252))
        else:
            downside_vol = 0.0

        if downside_vol > 0:
            metrics["sortino_ratio"] = round(
                float((annualized / 100 - self.RISK_FREE_RATE) / downside_vol), 2
            )
        else:
            metrics["sortino_ratio"] = 0.0
            
        return metrics, volatility, downside_vol

def test():
    service = MockPerformanceService()
    returns = [0.01, -0.02, 0.015, -0.005, 0.01]
    annualized = 15.5
    
    metrics, vol, downside_vol = service.calculate_metrics_mock(returns, annualized)
    
    print(f"Volatility: {vol}, Type: {type(vol)}")
    print(f"Downside Volatility: {downside_vol}, Type: {type(downside_vol)}")
    print(f"Metrics: {metrics}")
    
    for k, v in metrics.items():
        print(f"Metric {k}: {v}, Type: {type(v)}")
        assert isinstance(v, (float, int)), f"Metric {k} is not a standard float/int, it is {type(v)}"

    assert isinstance(vol, float), f"vol is not a float, it is {type(vol)}"
    assert isinstance(downside_vol, float), f"downside_vol is not a float, it is {type(downside_vol)}"
    
    print("Verification successful!")

if __name__ == "__main__":
    test()
