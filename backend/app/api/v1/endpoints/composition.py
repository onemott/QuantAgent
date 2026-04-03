"""
策略组合API端点
提供策略组合创建、优化和管理的REST接口
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field, validator

from app.services.composition_optimizer import CompositionOptimizer
from app.strategies.composition.factory import CompositionFactory
from app.services.database import get_db
from app.models.db_models import CompositionResult
from app.services.strategy_templates import STRATEGY_TEMPLATES, ASYNC_STRATEGIES
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter()

# 初始化优化器
composition_optimizer = CompositionOptimizer()


# ─────────────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────────────────────────

class CompositionOptimizeRequest(BaseModel):
    """策略组合优化请求"""
    
    atomic_strategies: List[str] = Field(
        ...,
        description="原子策略列表，如 ['ma', 'rsi', 'boll']",
        example=["ma", "rsi", "boll"]
    )
    
    composition_type: str = Field(
        ...,
        description="组合类型: 'weighted' (加权组合) 或 'voting' (投票组合)",
        example="weighted"
    )
    
    symbol: str = Field(
        "BTCUSDT",
        description="交易标的",
        example="BTCUSDT"
    )
    
    interval: str = Field(
        "1d",
        description="时间周期: '1m', '5m', '15m', '1h', '4h', '1d'",
        example="1d"
    )
    
    data_limit: int = Field(
        500,
        description="数据量限制",
        ge=50,
        le=5000
    )
    
    initial_capital: float = Field(
        10000.0,
        description="初始资金",
        gt=0
    )
    
    param_grid: Optional[Dict[str, List[Any]]] = Field(
        None,
        description="自定义参数网格。如果为None则使用默认网格"
    )
    
    max_combinations: int = Field(
        50,
        description="最大参数组合数",
        ge=1,
        le=200
    )
    
    use_clickhouse: bool = Field(
        True,
        description="是否使用ClickHouse数据"
    )
    
    save_result: bool = Field(
        True,
        description="是否保存优化结果到数据库"
    )
    
    @validator('composition_type')
    def validate_composition_type(cls, v):
        allowed_types = ['weighted', 'voting']
        if v not in allowed_types:
            raise ValueError(f'组合类型必须是: {allowed_types}')
        return v
    
    @validator('atomic_strategies')
    def validate_atomic_strategies(cls, v):
        # 1. 非空检查
        if not v:
            raise ValueError('原子策略列表不能为空')
        
        # 2. 长度检查：组合至少需要2个策略
        if len(v) < 2:
            raise ValueError('组合策略至少需要2个原子策略')
        
        # 3. 最大长度检查
        if len(v) > 10:
            raise ValueError('原子策略数量不能超过10个')
        
        # 4. 检查重复策略名称
        seen = set()
        for strategy in v:
            if strategy in seen:
                raise ValueError(f'原子策略列表中存在重复的策略: {strategy}')
            seen.add(strategy)
        
        # 5. 验证策略名称是否为已知的合法策略
        valid_strategies = set(STRATEGY_TEMPLATES.keys())
        for strategy in v:
            if strategy not in valid_strategies:
                raise ValueError(f'未知的策略名称: {strategy}。可用策略: {list(valid_strategies)}')
        
        # 6. 检查是否包含异步策略（异步策略不支持历史回放和回测）
        async_in_list = [s for s in v if s in ASYNC_STRATEGIES]
        if async_in_list:
            raise ValueError(f'组合策略不支持异步策略: {async_in_list}。异步策略依赖实时数据，不支持历史回放。')
        
        return v


class CompositionPerformance(BaseModel):
    """组合策略性能指标"""
    
    total_return: float = Field(..., description="总收益率 (%)")
    annual_return: float = Field(..., description="年化收益率 (%)")
    max_drawdown: float = Field(..., description="最大回撤 (%)")
    sharpe_ratio: float = Field(..., description="夏普比率")
    win_rate: float = Field(..., description="胜率 (%)")
    profit_factor: float = Field(..., description="盈利因子")
    total_trades: int = Field(..., description="总交易次数")
    final_capital: float = Field(..., description="最终资金")


class CompositionOptimizeResponse(BaseModel):
    """策略组合优化响应"""
    
    success: bool = Field(..., description="优化是否成功")
    message: str = Field(..., description="结果消息")
    
    # 优化结果
    composition_type: str = Field(..., description="组合类型")
    atomic_strategies: List[str] = Field(..., description="原子策略列表")
    symbol: str = Field(..., description="交易标的")
    interval: str = Field(..., description="时间周期")
    
    # 最佳参数和性能
    best_params: Dict[str, Any] = Field(..., description="最佳参数")
    best_performance: CompositionPerformance = Field(..., description="最佳性能指标")
    best_sharpe: float = Field(..., description="最佳夏普比率")
    best_return: float = Field(..., description="最佳总收益率")
    best_drawdown: float = Field(..., description="最佳最大回撤")
    
    # 统计信息
    total_combinations_tested: int = Field(..., description="测试的参数组合总数")
    valid_results: int = Field(..., description="有效结果数量")
    
    # 数据库记录ID
    composition_id: Optional[int] = Field(None, description="数据库记录ID")
    
    # 时间戳
    optimization_time: str = Field(..., description="优化完成时间")
    data_points: int = Field(..., description="使用的数据点数")


class CompareCompositionRequest(BaseModel):
    """比较不同组合类型请求"""
    
    atomic_strategies: List[str] = Field(
        ...,
        description="原子策略列表",
        example=["ma", "rsi", "boll"]
    )
    
    symbol: str = Field("BTCUSDT", description="交易标的")
    interval: str = Field("1d", description="时间周期")
    data_limit: int = Field(500, description="数据量限制")
    initial_capital: float = Field(10000.0, description="初始资金")
    
    @validator('atomic_strategies')
    def validate_atomic_strategies(cls, v):
        # 1. 非空检查
        if not v:
            raise ValueError('原子策略列表不能为空')
        
        # 2. 长度检查：组合至少需要2个策略
        if len(v) < 2:
            raise ValueError('组合策略至少需要2个原子策略')
        
        # 3. 最大长度检查
        if len(v) > 10:
            raise ValueError('原子策略数量不能超过10个')
        
        # 4. 检查重复策略名称
        seen = set()
        for strategy in v:
            if strategy in seen:
                raise ValueError(f'原子策略列表中存在重复的策略: {strategy}')
            seen.add(strategy)
        
        # 5. 验证策略名称是否为已知的合法策略
        valid_strategies = set(STRATEGY_TEMPLATES.keys())
        for strategy in v:
            if strategy not in valid_strategies:
                raise ValueError(f'未知的策略名称: {strategy}。可用策略: {list(valid_strategies)}')
        
        # 6. 检查是否包含异步策略（异步策略不支持历史回放和回测）
        async_in_list = [s for s in v if s in ASYNC_STRATEGIES]
        if async_in_list:
            raise ValueError(f'组合策略不支持异步策略: {async_in_list}。异步策略依赖实时数据，不支持历史回放。')
        
        return v


class CompositionComparisonItem(BaseModel):
    """组合类型比较项"""
    
    composition_type: str = Field(..., description="组合类型")
    performance: Optional[CompositionPerformance] = Field(None, description="性能指标")
    composer_params: Dict[str, Any] = Field(..., description="组合器参数")
    error: Optional[str] = Field(None, description="错误信息")


class CompareCompositionResponse(BaseModel):
    """组合类型比较响应"""
    
    success: bool = Field(..., description="比较是否成功")
    message: str = Field(..., description="结果消息")
    
    comparisons: Dict[str, CompositionComparisonItem] = Field(
        ..., 
        description="各组合类型的比较结果"
    )
    
    atomic_strategies: Dict[str, CompositionPerformance] = Field(
        ...,
        description="原子策略的独立表现"
    )
    
    # 权益曲线数据（用于前端图表）
    equity_curves: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        None, 
        description="各策略权益曲线，格式: {strategy_name: [{t: ISO时间, v: 权益值}, ...]}"
    )
    
    # 权重分布（仅加权组合）
    weight_distribution: Optional[Dict[str, Dict[str, float]]] = Field(
        None, 
        description="加权组合权重分布，格式: {weighted: {strategy: weight, ...}}"
    )
    
    # 信号统计
    signal_stats: Optional[Dict[str, Dict[str, Any]]] = Field(
        None, 
        description="各策略信号统计，包含buy/sell/neutral信号数量和一致性"
    )
    
    # 时间戳
    comparison_time: str = Field(..., description="比较完成时间")


class GetCompositionsRequest(BaseModel):
    """获取组合策略列表请求"""
    
    composition_type: Optional[str] = Field(None, description="组合类型过滤")
    symbol: Optional[str] = Field(None, description="标的过滤")
    limit: int = Field(20, description="返回数量限制", ge=1, le=100)


class CompositionListItem(BaseModel):
    """组合策略列表项"""
    
    id: int = Field(..., description="记录ID")
    composition_type: str = Field(..., description="组合类型")
    atomic_strategies: List[str] = Field(..., description="原子策略列表")
    symbol: str = Field(..., description="交易标的")
    interval: str = Field(..., description="时间周期")
    best_sharpe: float = Field(..., description="最佳夏普比率")
    best_return: float = Field(..., description="最佳总收益率")
    created_at: str = Field(..., description="创建时间")


class GetCompositionsResponse(BaseModel):
    """获取组合策略列表响应"""
    
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    compositions: List[CompositionListItem] = Field(..., description="组合策略列表")
    total: int = Field(..., description="总数")


# ─────────────────────────────────────────────────────────────────────────────
# API端点
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/composition/optimize", response_model=CompositionOptimizeResponse)
async def optimize_composition(
    req: CompositionOptimizeRequest,
    background_tasks: BackgroundTasks
):
    """
    优化策略组合
    
    根据指定的原子策略和组合类型，在历史数据上寻找最优参数组合。
    支持加权组合(weighted)和投票组合(voting)。
    """
    
    try:
        # 运行组合优化
        optimization_result = await composition_optimizer.optimize_composition(
            atomic_strategies=req.atomic_strategies,
            composition_type=req.composition_type,
            symbol=req.symbol,
            interval=req.interval,
            data_limit=req.data_limit,
            initial_capital=req.initial_capital,
            param_grid=req.param_grid,
            max_combinations=req.max_combinations,
            use_clickhouse=req.use_clickhouse
        )
        
        # 保存结果到数据库
        composition_id = None
        if req.save_result:
            try:
                async with get_db() as session:
                    composition_record = CompositionResult(
                        composition_type=req.composition_type,
                        atomic_strategies=req.atomic_strategies,
                        symbol=req.symbol,
                        interval=req.interval,
                        best_params=optimization_result["best_params"],
                        best_performance=optimization_result["best_performance"],
                        best_sharpe=optimization_result["best_sharpe"],
                        best_return=optimization_result["best_return"],
                        total_combinations_tested=optimization_result["total_combinations_tested"],
                        valid_results=optimization_result["valid_results"],
                        all_results=optimization_result.get("all_results", [])[:10]  # 只保存前10个
                    )
                    session.add(composition_record)
                    await session.flush()
                    composition_id = composition_record.id
                    await session.commit()
                    
                    logger.info(f"组合优化结果已保存到数据库，ID: {composition_id}")
                    
            except Exception as e:
                logger.warning(f"保存组合优化结果失败: {e}")
                # 不因为保存失败而返回错误
        
        # 构建响应
        performance = optimization_result["best_performance"]
        
        response = CompositionOptimizeResponse(
            success=True,
            message="策略组合优化完成，找到最优参数组合",
            
            composition_type=optimization_result["composition_type"],
            atomic_strategies=optimization_result["atomic_strategies"],
            symbol=optimization_result["symbol"],
            interval=optimization_result["interval"],
            
            best_params=optimization_result["best_params"],
            best_performance=CompositionPerformance(**performance),
            best_sharpe=optimization_result["best_sharpe"],
            best_return=optimization_result["best_return"],
            best_drawdown=performance["max_drawdown"],
            
            total_combinations_tested=optimization_result["total_combinations_tested"],
            valid_results=optimization_result["valid_results"],
            
            composition_id=composition_id,
            optimization_time=optimization_result["optimization_time"],
            data_points=optimization_result["data_points"]
        )
        
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"组合优化失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"组合优化失败: {str(e)}")


@router.post("/composition/compare", response_model=CompareCompositionResponse)
async def compare_composition_types(req: CompareCompositionRequest):
    """
    比较不同组合类型的表现
    
    在同一组原子策略和历史数据上，比较加权组合和投票组合的表现。
    返回包含权益曲线、权重分布和信号统计的完整对比数据，支持前端多策略对比图表绘制。
    """
    
    try:
        # 运行组合类型比较
        comparison_result = await composition_optimizer.compare_composition_types(
            atomic_strategies=req.atomic_strategies,
            symbol=req.symbol,
            interval=req.interval,
            data_limit=req.data_limit,
            initial_capital=req.initial_capital
        )
        
        # 构建比较结果
        comparisons = {}
        for comp_type, result in comparison_result.items():
            # 跳过非组合类型的字段
            if comp_type in ["atomic_strategies", "equity_curves", "weight_distribution", "signal_stats"]:
                continue
                
            if result.get("error"):
                comparisons[comp_type] = CompositionComparisonItem(
                    composition_type=comp_type,
                    performance=None,
                    composer_params=result.get("composer_params", {}),
                    error=result["error"]
                )
            else:
                perf_data = result.get("performance")
                if perf_data:
                    comparisons[comp_type] = CompositionComparisonItem(
                        composition_type=comp_type,
                        performance=CompositionPerformance(**perf_data),
                        composer_params=result.get("composer_params", {}),
                        error=None
                    )
        
        # 原子策略表现
        atomic_performances = {}
        atomic_results = comparison_result.get("atomic_strategies", {})
        for strategy_name, perf_data in atomic_results.items():
            if perf_data:
                atomic_performances[strategy_name] = CompositionPerformance(**perf_data)
        
        # 提取新增的字段
        equity_curves = comparison_result.get("equity_curves")
        weight_distribution = comparison_result.get("weight_distribution")
        signal_stats = comparison_result.get("signal_stats")
        
        response = CompareCompositionResponse(
            success=True,
            message="组合类型比较完成",
            comparisons=comparisons,
            atomic_strategies=atomic_performances,
            equity_curves=equity_curves,
            weight_distribution=weight_distribution,
            signal_stats=signal_stats,
            comparison_time=datetime.utcnow().isoformat()
        )
        
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"组合类型比较失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"组合类型比较失败: {str(e)}")


@router.get("/composition/types")
async def get_composition_types():
    """
    获取可用的组合类型及其参数信息
    """
    
    try:
        composers_info = CompositionFactory.get_available_composers()
        
        return {
            "success": True,
            "message": "可用组合类型获取成功",
            "composition_types": composers_info,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取组合类型失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取组合类型失败: {str(e)}")


@router.get("/composition/history", response_model=GetCompositionsResponse)
async def get_composition_history(
    composition_type: Optional[str] = Query(None, description="组合类型过滤"),
    symbol: Optional[str] = Query(None, description="标的过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制")
):
    """
    获取历史组合优化结果
    
    返回之前保存的组合优化结果，按创建时间倒序排列。
    """
    
    try:
        async with get_db() as session:
            # 构建查询
            stmt = select(CompositionResult).order_by(CompositionResult.created_at.desc()).limit(limit)
            
            # 添加过滤条件
            if composition_type:
                stmt = stmt.where(CompositionResult.composition_type == composition_type)
            if symbol:
                stmt = stmt.where(CompositionResult.symbol == symbol.upper())
            
            # 执行查询
            result = await session.execute(stmt)
            rows = result.scalars().all()
            
            # 构建响应
            compositions = []
            for row in rows:
                compositions.append(CompositionListItem(
                    id=row.id,
                    composition_type=row.composition_type,
                    atomic_strategies=row.atomic_strategies,
                    symbol=row.symbol,
                    interval=row.interval,
                    best_sharpe=row.best_sharpe,
                    best_return=row.best_return,
                    created_at=row.created_at.isoformat() if row.created_at else None
                ))
            
            response = GetCompositionsResponse(
                success=True,
                message=f"获取到 {len(compositions)} 条组合策略记录",
                compositions=compositions,
                total=len(compositions)
            )
            
            return response
            
    except Exception as e:
        logger.error(f"获取组合历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取组合历史失败: {str(e)}")


@router.get("/composition/{composition_id}")
async def get_composition_detail(composition_id: int):
    """
    获取组合策略的详细结果
    """
    
    try:
        async with get_db() as session:
            from sqlalchemy import select
            stmt = select(CompositionResult).where(CompositionResult.id == composition_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            
            if not row:
                raise HTTPException(status_code=404, detail="组合策略记录不存在")
            
            # 构建详细响应
            detail = {
                "id": row.id,
                "composition_type": row.composition_type,
                "atomic_strategies": row.atomic_strategies,
                "symbol": row.symbol,
                "interval": row.interval,
                "best_params": row.best_params,
                "best_performance": row.best_performance,
                "best_sharpe": row.best_sharpe,
                "best_return": row.best_return,
                "total_combinations_tested": row.total_combinations_tested,
                "valid_results": row.valid_results,
                "all_results": row.all_results,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None
            }
            
            return {
                "success": True,
                "message": "组合策略详情获取成功",
                "composition": detail
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取组合详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取组合详情失败: {str(e)}")


@router.delete("/composition/{composition_id}")
async def delete_composition(composition_id: int):
    """
    删除组合策略记录
    """
    
    try:
        async with get_db() as session:
            from sqlalchemy import select, delete
            
            # 检查记录是否存在
            stmt = select(CompositionResult).where(CompositionResult.id == composition_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            
            if not record:
                raise HTTPException(status_code=404, detail="组合策略记录不存在")
            
            # 删除记录
            delete_stmt = delete(CompositionResult).where(CompositionResult.id == composition_id)
            await session.execute(delete_stmt)
            await session.commit()
            
            return {
                "success": True,
                "message": "组合策略记录已删除",
                "id": composition_id
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除组合策略失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除组合策略失败: {str(e)}")


@router.get("/composition/atomic-strategies")
async def get_available_atomic_strategies():
    """
    获取可用的原子策略列表
    """
    
    try:
        from app.services.strategy_templates import get_all_templates_meta
        
        templates_meta = get_all_templates_meta()
        atomic_strategies = []
        
        for template in templates_meta:
            atomic_strategies.append({
                "id": template["id"],
                "name": template["name"],
                "description": template.get("description", ""),
                "parameters": template.get("params", {}),
                "category": template.get("category", "trend")
            })
        
        return {
            "success": True,
            "message": "原子策略列表获取成功",
            "atomic_strategies": atomic_strategies,
            "total": len(atomic_strategies)
        }
        
    except Exception as e:
        logger.error(f"获取原子策略列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取原子策略列表失败: {str(e)}")