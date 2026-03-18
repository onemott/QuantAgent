"""
性能分析 API 测试脚本
Test Performance Analytics API endpoints

使用方法:
    python scripts/test_analytics_api.py

测试内容:
    - 性能指标 API
    - 权益曲线 API
    - 持仓分析 API
    - 收益归因 API
    - 策略对比 API
    - 交易对列表 API
"""

import asyncio
import httpx
import sys
from typing import Dict, List, Any


class AnalyticsAPITester:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.results: List[Dict[str, Any]] = []
    
    async def check_server_health(self) -> bool:
        """Check if the server is reachable"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/")
                return response.status_code == 200
        except Exception as e:
            print(f"⚠️  后端服务不可用: {e}")
            print(f"   请确保后端服务正在运行: uvicorn main:app --reload --host 0.0.0.0 --port 8000")
            return False
    
    async def test_endpoint(self, name: str, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Test a single API endpoint"""
        url = f"{self.base_url}{path}"
        result = {
            "name": name,
            "url": url,
            "method": method,
            "status_code": None,
            "success": False,
            "data": None,
            "error": None,
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(url, **kwargs)
                elif method.upper() == "POST":
                    response = await client.post(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                result["status_code"] = response.status_code
                
                if response.status_code == 200:
                    result["data"] = response.json()
                    result["success"] = True
                else:
                    result["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
                    
        except httpx.TimeoutException:
            result["error"] = "请求超时"
        except httpx.ConnectError:
            result["error"] = "连接失败 - 后端服务可能未运行"
        except Exception as e:
            result["error"] = str(e)
        
        self.results.append(result)
        return result
    
    async def test_all(self):
        """Test all analytics endpoints"""
        print("=" * 70)
        print("性能分析 API 测试")
        print("=" * 70)
        
        # First check if server is available
        if not await self.check_server_health():
            print("\n❌ 无法连接到后端服务，测试终止。")
            return False
        
        endpoints = [
            ("性能指标 (Performance Metrics)", "GET", "/api/v1/analytics/performance?period=all_time"),
            ("权益曲线 (Equity Curve)", "GET", "/api/v1/analytics/equity-curve?period=all_time"),
            ("持仓分析 (Positions Analysis)", "GET", "/api/v1/analytics/positions/analysis"),
            ("收益归因 (Attribution)", "GET", "/api/v1/analytics/attribution?period=all_time"),
            ("策略对比 (Strategy Comparison)", "GET", "/api/v1/analytics/strategy-comparison"),
            ("交易对列表 (Trade Pairs)", "GET", "/api/v1/analytics/trade-pairs?limit=10"),
            ("性能指标 - 今日 (Daily)", "GET", "/api/v1/analytics/performance?period=daily"),
            ("性能指标 - 本周 (Weekly)", "GET", "/api/v1/analytics/performance?period=weekly"),
            ("性能指标 - 本月 (Monthly)", "GET", "/api/v1/analytics/performance?period=monthly"),
            ("权益曲线 - 4h间隔", "GET", "/api/v1/analytics/equity-curve?period=all_time&interval=4h"),
            ("权益曲线 - 1d间隔", "GET", "/api/v1/analytics/equity-curve?period=all_time&interval=1d"),
        ]
        
        for name, method, path in endpoints:
            result = await self.test_endpoint(name, method, path)
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"\n{status} | {name}")
            print(f"     URL: {result['url']}")
            if result["success"]:
                print(f"     Status: {result['status_code']}")
                if result["data"]:
                    data_preview = str(result["data"])[:150]
                    print(f"     Data: {data_preview}...")
            else:
                print(f"     Error: {result['error']}")
        
        print("\n" + "=" * 70)
        print("测试汇总")
        print("=" * 70)
        
        passed = sum(1 for r in self.results if r["success"])
        total = len(self.results)
        print(f"通过: {passed}/{total}")
        
        if passed < total:
            print("\n失败的测试:")
            for r in self.results:
                if not r["success"]:
                    print(f"  - {r['name']}: {r['error']}")
        
        return passed == total
    
    def print_report(self):
        """Generate detailed test report"""
        print("\n" + "=" * 70)
        print("详细测试报告")
        print("=" * 70)
        
        for r in self.results:
            print(f"\n【{r['name']}】")
            print(f"  URL: {r['url']}")
            print(f"  Method: {r['method']}")
            print(f"  Status: {r['status_code'] or 'N/A'}")
            print(f"  Success: {r['success']}")
            if r["error"]:
                print(f"  Error: {r['error']}")
            if r["data"]:
                print(f"  Data Keys: {list(r['data'].keys()) if isinstance(r['data'], dict) else type(r['data'])}")


async def main():
    tester = AnalyticsAPITester()
    success = await tester.test_all()
    tester.print_report()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
