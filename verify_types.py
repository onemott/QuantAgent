
import numpy as np
from typing import List

def old_logic(returns: List[float]) -> float:
    return float(np.std(returns)) * np.sqrt(252)

def new_logic(returns: List[float]) -> float:
    return float(np.std(returns) * np.sqrt(252))

returns = [0.01, -0.02, 0.015, -0.005, 0.01]
res_old = old_logic(returns)
res_new = new_logic(returns)

print(f"Old Result Type: {type(res_old)}")
print(f"New Result Type: {type(res_new)}")

if type(res_old) != float:
    print("Confirmed: Old logic returns numpy type")
if type(res_new) == float:
    print("Confirmed: New logic returns standard float")
