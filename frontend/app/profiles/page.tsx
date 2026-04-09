"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  TrendingUp, TrendingDown, BarChart3, Shield, Zap, 
  Target, Activity, ArrowUpRight, ArrowDownRight,
  CheckCircle2, XCircle, Info, Play, GitCompare,
  ChevronDown, ChevronUp, Eye, BarChart2
} from "lucide-react";
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, 
  ResponsiveContainer, Legend, RadarChart, Radar, PolarGrid, 
  PolarAngleAxis, PolarRadiusAxis
} from 'recharts';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProfileParams {
  key: string;
  label: string;
  value: string | number;
}

interface Profile {
  id: number;
  profile_id: string;
  strategy_type: string;
  strategy_type_name: string;
  symbol: string;
  interval: string;
  params: Record<string, number>;
  params_display: ProfileParams[];
  risk_level: string;
  risk_level_name: string;
  risk_level_color: string;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  initial_capital: number;
  final_capital: number;
  created_at: string;
}

interface RiskLevelGroup {
  risk_level: string;
  risk_level_name: string;
  risk_level_color: string;
  profiles: Profile[];
}

interface ProfilesResponse {
  profiles: Profile[];
  grouped: RiskLevelGroup[];
  total: number;
  risk_levels: { value: string; label: string; color: string }[];
  strategy_types: { value: string; label: string }[];
}

// ─── Constants ────────────────────────────────────────────────────────────────

const RISK_LEVEL_DESCRIPTIONS: Record<string, string> = {
  conservative: "追求稳定收益，回撤控制严格，适合风险厌恶型投资者",
  moderate: "平衡收益与风险，适合稳健型投资者",
  balanced: "较高收益潜力，中等回撤，适合平衡型投资者",
  aggressive: "高收益高风险，适合激进型投资者",
  ultra_aggressive: "追求最大收益，风险最高，适合风险承受能力强的投资者",
};

const RISK_LEVEL_ICONS: Record<string, React.ReactNode> = {
  conservative: <Shield className="w-4 h-4" />,
  moderate: <Activity className="w-4 h-4" />,
  balanced: <BarChart2 className="w-4 h-4" />,
  aggressive: <Zap className="w-4 h-4" />,
  ultra_aggressive: <Target className="w-4 h-4" />,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || isNaN(v)) return "—";
  return v.toFixed(digits);
}

function fmtCurrency(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function colorReturn(v: number): string {
  return v >= 0 ? "text-green-400" : "text-red-400";
}

function colorRiskLevel(level: string): string {
  const colors: Record<string, string> = {
    conservative: "bg-green-500/20 text-green-400 border-green-500/30",
    moderate: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    balanced: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    aggressive: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    ultra_aggressive: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  return colors[level] || "bg-slate-500/20 text-slate-400 border-slate-500/30";
}

// ─── Profile Card Component ──────────────────────────────────────────────────

interface ProfileCardProps {
  profile: Profile;
  onSelect: (profile: Profile) => void;
  onCompare: (profile: Profile) => void;
  isSelected: boolean;
}

function ProfileCard({ profile, onSelect, onCompare, isSelected }: ProfileCardProps) {
  return (
    <div 
      className={`relative bg-slate-800/50 border rounded-xl p-4 transition-all hover:border-slate-600 hover:bg-slate-800/70 ${
        isSelected ? 'border-blue-500 ring-1 ring-blue-500' : 'border-slate-700'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Badge className={colorRiskLevel(profile.risk_level)}>
              {RISK_LEVEL_ICONS[profile.risk_level]}
              <span className="ml-1">{profile.risk_level_name}</span>
            </Badge>
          </div>
          <h4 className="text-slate-100 font-semibold text-sm">
            {profile.strategy_type_name}
          </h4>
          <p className="text-slate-400 text-xs">{profile.profile_id}</p>
        </div>
        <div className="text-right">
          <div className={`text-lg font-bold ${colorReturn(profile.total_return)}`}>
            {profile.total_return >= 0 ? '+' : ''}{fmt(profile.total_return)}%
          </div>
          <div className="text-slate-500 text-xs">总收益</div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-2 mb-3 text-xs">
        <div className="bg-slate-900/50 rounded-lg p-2">
          <div className="text-slate-400">年化收益</div>
          <div className={`font-semibold ${colorReturn(profile.annual_return)}`}>
            {profile.annual_return >= 0 ? '+' : ''}{fmt(profile.annual_return)}%
          </div>
        </div>
        <div className="bg-slate-900/50 rounded-lg p-2">
          <div className="text-slate-400">最大回撤</div>
          <div className="text-red-400 font-semibold">-{fmt(profile.max_drawdown)}%</div>
        </div>
        <div className="bg-slate-900/50 rounded-lg p-2">
          <div className="text-slate-400">夏普比率</div>
          <div className="text-blue-400 font-semibold">{fmt(profile.sharpe_ratio)}</div>
        </div>
        <div className="bg-slate-900/50 rounded-lg p-2">
          <div className="text-slate-400">胜率</div>
          <div className="text-cyan-400 font-semibold">{fmt(profile.win_rate)}%</div>
        </div>
      </div>

      {/* Params Preview */}
      <div className="text-xs text-slate-400 mb-3">
        <span className="text-slate-500">参数:</span> {profile.params_display.map(p => `${p.label}=${p.value}`).join(", ")}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <Button 
          size="sm" 
          variant="default"
          className="flex-1 bg-blue-600 hover:bg-blue-700"
          onClick={() => onSelect(profile)}
        >
          <Play className="w-3 h-3 mr-1" />
          一键回测
        </Button>
        <Button 
          size="sm" 
          variant="outline"
          onClick={() => onCompare(profile)}
          className="border-slate-600 hover:bg-slate-700"
        >
          <GitCompare className="w-3 h-3" />
        </Button>
      </div>
    </div>
  );
}

// ─── Comparison Modal Component ────────────────────────────────────────────────

interface CompareModalProps {
  profiles: Profile[];
  onClose: () => void;
}

function CompareModal({ profiles, onClose }: CompareModalProps) {
  const chartData = profiles.map(p => ({
    name: p.profile_id.split('_').slice(0, 2).join(' '),
    总收益: p.total_return,
    年化收益: p.annual_return,
    最大回撤: -p.max_drawdown,
    夏普比率: p.sharpe_ratio,
    胜率: p.win_rate,
  }));

  const radarData = profiles.map(p => ({
    name: p.profile_id.split('_').slice(0, 2).join(' '),
    收益: Math.min(p.total_return / 20, 100),
    稳定性: Math.max(100 - p.max_drawdown, 0),
    风险调整: p.sharpe_ratio * 20,
    胜率: p.win_rate,
    交易数: Math.min(p.total_trades / 2, 100),
  }));

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl max-h-[90vh] overflow-auto">
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 p-4 flex items-center justify-between">
          <h2 className="text-xl font-bold text-slate-100">策略方案对比</h2>
          <Button variant="ghost" onClick={onClose} className="text-slate-400 hover:text-slate-100">
            <XCircle className="w-5 h-5" />
          </Button>
        </div>
        
        <div className="p-6 space-y-6">
          {/* Comparison Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-2 px-3 text-slate-400">指标</th>
                  {profiles.map(p => (
                    <th key={p.profile_id} className="text-right py-2 px-3 text-slate-100">
                      {p.profile_id.split('_').slice(0, 2).join(' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: '风险等级', key: 'risk_level_name' },
                  { label: '总收益', key: 'total_return', suffix: '%', color: true },
                  { label: '年化收益', key: 'annual_return', suffix: '%', color: true },
                  { label: '最大回撤', key: 'max_drawdown', suffix: '%', negative: true },
                  { label: '夏普比率', key: 'sharpe_ratio' },
                  { label: '胜率', key: 'win_rate', suffix: '%' },
                  { label: '盈亏比', key: 'profit_factor' },
                  { label: '交易次数', key: 'total_trades' },
                ].map(row => (
                  <tr key={row.key} className="border-b border-slate-800">
                    <td className="py-2 px-3 text-slate-400">{row.label}</td>
                    {profiles.map(p => {
                      const val = p[row.key as keyof Profile] as number | string;
                      const display = row.suffix ? `${val}${row.suffix}` : val;
                      const isPositive = typeof val === 'number' && val > 0;
                      return (
                        <td key={p.profile_id} className={`py-2 px-3 text-right font-medium ${
                          row.color ? colorReturn(val as number) : 
                          row.negative && isPositive ? 'text-red-400' : 
                          'text-slate-100'
                        }`}>
                          {display}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bar Chart */}
          <div className="bg-slate-800/50 rounded-xl p-4">
            <h3 className="text-slate-100 font-semibold mb-4">收益与风险对比</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
                  <YAxis stroke="#94a3b8" fontSize={12} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                    labelStyle={{ color: '#e2e8f0' }}
                  />
                  <Legend />
                  <Bar dataKey="总收益" fill="#22c55e" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="年化收益" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="最大回撤" fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Radar Chart */}
          <div className="bg-slate-800/50 rounded-xl p-4">
            <h3 className="text-slate-100 font-semibold mb-4">综合能力雷达图</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#334155" />
                  <PolarAngleAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
                  <PolarRadiusAxis stroke="#334155" fontSize={10} />
                  <Radar name={profiles[0]?.profile_id.split('_').slice(0, 2).join(' ') || ''} dataKey="收益" stroke="#22c55e" fill="#22c55e" fillOpacity={0.3} />
                  <Radar name={profiles[1]?.profile_id.split('_').slice(0, 2).join(' ') || ''} dataKey="稳定性" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.3} />
                  <Radar name={profiles[2]?.profile_id.split('_').slice(0, 2).join(' ') || ''} dataKey="风险调整" stroke="#eab308" fill="#eab308" fillOpacity={0.3} />
                  <Legend />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StrategyProfilesPage() {
  const [profilesResponse, setProfilesResponse] = useState<ProfilesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRiskLevel, setSelectedRiskLevel] = useState<string>("all");
  const [selectedStrategy, setSelectedStrategy] = useState<string>("all");
  const [compareProfiles, setCompareProfiles] = useState<Profile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<Profile | null>(null);

  // Fetch profiles
  useEffect(() => {
    const fetchProfiles = async () => {
      try {
        setLoading(true);
        const res = await fetch("/api/v1/profiles?limit=50");
        if (!res.ok) throw new Error("Failed to fetch profiles");
        const data = await res.json();
        setProfilesResponse(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };
    fetchProfiles();
  }, []);

  // Filter profiles
  const filteredProfiles = useMemo(() => {
    if (!profilesResponse) return [];
    return profilesResponse.profiles.filter(p => {
      if (selectedRiskLevel !== "all" && p.risk_level !== selectedRiskLevel) return false;
      if (selectedStrategy !== "all" && p.strategy_type !== selectedStrategy) return false;
      return true;
    });
  }, [profilesResponse, selectedRiskLevel, selectedStrategy]);

  // Group by risk level
  const groupedProfiles = useMemo(() => {
    const groups: Record<string, Profile[]> = {};
    filteredProfiles.forEach(p => {
      if (!groups[p.risk_level]) groups[p.risk_level] = [];
      groups[p.risk_level].push(p);
    });
    return groups;
  }, [filteredProfiles]);

  const handleSelectProfile = (profile: Profile) => {
    setSelectedProfile(profile);
    // Navigate to backtest page with pre-filled params
    const params = new URLSearchParams({
      strategy: profile.strategy_type,
      symbol: profile.symbol,
      interval: profile.interval,
    });
    Object.entries(profile.params).forEach(([key, value]) => {
      params.append(key, String(value));
    });
    window.location.href = `/backtest?${params.toString()}`;
  };

  const handleCompare = (profile: Profile) => {
    if (compareProfiles.length >= 4) {
      setCompareProfiles([profile]);
    } else if (compareProfiles.find(p => p.profile_id === profile.profile_id)) {
      setCompareProfiles(compareProfiles.filter(p => p.profile_id !== profile.profile_id));
    } else {
      setCompareProfiles([...compareProfiles, profile]);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400">加载策略配置方案中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-red-400">错误: {error}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      <div className="bg-slate-900/80 border-b border-slate-800 sticky top-0 z-10 backdrop-blur-md">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-slate-100">策略配置方案库</h1>
              <p className="text-slate-400 text-sm mt-1">
                预设 {profilesResponse?.total || 0} 个策略方案，覆盖 5 种风险等级
              </p>
            </div>
            
            {/* Filters */}
            <div className="flex items-center gap-3">
              <Select value={selectedRiskLevel} onValueChange={setSelectedRiskLevel}>
                <SelectTrigger className="w-36 bg-slate-800 border-slate-700">
                  <SelectValue placeholder="风险等级" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部风险</SelectItem>
                  {profilesResponse?.risk_levels.map(rl => (
                    <SelectItem key={rl.value} value={rl.value}>
                      <span style={{ color: rl.color }}>{rl.label}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              
              <Select value={selectedStrategy} onValueChange={setSelectedStrategy}>
                <SelectTrigger className="w-40 bg-slate-800 border-slate-700">
                  <SelectValue placeholder="策略类型" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部策略</SelectItem>
                  {profilesResponse?.strategy_types.map(st => (
                    <SelectItem key={st.value} value={st.value}>{st.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>

      {/* Compare Bar */}
      {compareProfiles.length > 0 && (
        <div className="bg-blue-900/30 border-b border-blue-800/50 px-4 py-3">
          <div className="container mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-blue-300 text-sm">已选择 {compareProfiles.length} 个方案进行对比:</span>
              {compareProfiles.map(p => (
                <Badge key={p.profile_id} variant="outline" className="border-blue-500/50 text-blue-300">
                  {p.profile_id.split('_').slice(0, 2).join(' ')}
                </Badge>
              ))}
            </div>
            <div className="flex gap-2">
              <Button 
                size="sm" 
                variant="outline"
                onClick={() => setCompareProfiles([])}
                className="border-slate-600"
              >
                清除
              </Button>
              {compareProfiles.length >= 2 && (
                <Button 
                  size="sm"
                  onClick={() => {}}
                  className="bg-blue-600 hover:bg-blue-700"
                >
                  <GitCompare className="w-4 h-4 mr-1" />
                  查看对比
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="container mx-auto px-4 py-6">
        {selectedRiskLevel === "all" ? (
          // Group by Risk Level
          <div className="space-y-8">
            {profilesResponse?.grouped.map(group => (
              <div key={group.risk_level}>
                {/* Risk Level Header */}
                <div className="flex items-center gap-3 mb-4">
                  <Badge className={`${colorRiskLevel(group.risk_level)} px-3 py-1`}>
                    {RISK_LEVEL_ICONS[group.risk_level]}
                    <span className="ml-1 font-semibold">{group.risk_level_name}</span>
                  </Badge>
                  <span className="text-slate-400 text-sm">{RISK_LEVEL_DESCRIPTIONS[group.risk_level]}</span>
                </div>
                
                {/* Profiles Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                  {group.profiles.map(profile => (
                    <ProfileCard
                      key={profile.profile_id}
                      profile={profile}
                      onSelect={handleSelectProfile}
                      onCompare={handleCompare}
                      isSelected={compareProfiles.some(p => p.profile_id === profile.profile_id)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          // Single Risk Level
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredProfiles.map(profile => (
              <ProfileCard
                key={profile.profile_id}
                profile={profile}
                onSelect={handleSelectProfile}
                onCompare={handleCompare}
                isSelected={compareProfiles.some(p => p.profile_id === profile.profile_id)}
              />
            ))}
          </div>
        )}

        {filteredProfiles.length === 0 && (
          <div className="text-center py-12 text-slate-400">
            没有找到匹配的策略配置方案
          </div>
        )}
      </div>

      {/* Compare Modal */}
      {compareProfiles.length >= 2 && (
        <CompareModal 
          profiles={compareProfiles} 
          onClose={() => setCompareProfiles([])} 
        />
      )}
    </div>
  );
}
