#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漏洞挖掘进化引擎 · 元基因库 v3.0
================================

引擎自我进化的核心——元基因库 (Meta Gene Library)。

记录：
  - 策略级成功率（不是 Payload 级，是"联合查询 vs 盲注 vs OOB"哪种策略更有效）
  - 目标模式指纹（PHP+MySQL 的最佳策略是什么）
  - 自适应判定阈值（从历史误报/漏报率反推最优阈值）
  - 自适应收敛条件（动态判断何时挖透）

这是引擎的"元认知"——知道自己什么行、什么不行、什么时候该停。

用法：
  from meta_gene import MetaGeneLibrary

  mgl = MetaGeneLibrary()
  mgl.load()
  best = mgl.best_strategy("sqli", fingerprint={"framework": "PHP", "db": "mysql"})
  # → "sqli_union"
  mgl.record_strategy("sqli", "sqli_union", success=True, fingerprint={"framework": "PHP"})
  mgl.save()
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class StrategyGene:
    """单条策略基因"""
    strategy: str                        # "sqli_union" | "sqli_blind_time" | "sqli_oob" | ...
    success_count: int = 0
    total_count: int = 0
    success_rate: float = 0.0
    avg_confidence: float = 0.0
    first_seen: str = ""
    last_used: str = ""


@dataclass
class CognitiveStrategyGene:
    """L4 认知策略基因（v3.5 新增）

    记录「进化策略引擎」中每条认知策略（grafting / s_modify / enc_tunnel …）
    在历史进化中的有效度，用于反馈桥：
      - 初始化进化时按 success_rate 偏置变异/选择方向（读先验）
      - 每轮进化后把高适应度个体的认知策略血统写回（写回结晶）

    这是把「认知策略目录」与「攻击策略基因(L1)」打通的桥：
      L1 记 "哪种攻击有效"，L4 记 "哪种思考方式有效"。
    """
    strategy_id: str                     # "grafting" | "s_modify" | "enc_tunnel" | ...
    success_count: int = 0
    total_count: int = 0
    success_rate: float = 0.0
    avg_fitness_gain: float = 0.0        # 该策略带来的平均适应度提升
    first_seen: str = ""
    last_used: str = ""


@dataclass
class TargetPattern:
    """目标模式基因"""
    pattern_key: str                     # "php_mysql" | "java_spring" | ...
    framework_hints: List[str] = field(default_factory=list)
    best_strategies: Dict[str, str] = field(default_factory=dict)  # {vuln_type: best_strategy}
    avg_vulns_per_round: float = 0.0
    total_targets: int = 0


class MetaGeneLibrary:
    """元基因库 — 引擎自我进化的核心

    四层基因：
      L1 策略基因：每种攻击策略的历史成功率
      L2 目标模式：不同技术栈的最佳策略匹配
      L3 自适应参数：从历史数据反推的最优阈值
      L4 认知策略基因（v3.5 新增）：26 认知策略的进化有效度，支撑反馈桥
    """

    def __init__(self, data_dir: Optional[str] = None):
        home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
        data_dir = data_dir or os.path.join(home, "plugins-data", "vuln-hunter-engine")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._data_dir / "meta_gene_library.json"

        # L1: 策略基因 {vuln_type: {strategy: StrategyGene}}
        self.strategies: Dict[str, Dict[str, StrategyGene]] = {}

        # L2: 目标模式 {pattern_key: TargetPattern}
        self.target_patterns: Dict[str, TargetPattern] = {}

        # L3: 自适应参数
        self.thresholds: Dict[str, Dict] = {
            "time_blind": {"threshold": 2.0, "samples": 3, "false_positive_rate": 0.0},
            "boolean_blind": {"diff_threshold": 50, "content_threshold": 0.1, "false_positive_rate": 0.0},
            "oob_timeout": {"seconds": 30, "false_positive_rate": 0.0},
        }

        # 盲区记录：哪些漏洞类型/策略我们没有能力
        self.blind_spots: Dict[str, str] = {}

        # 能力声明：告诉 Agent 我们需要什么
        self.capability_requirements: Dict[str, bool] = {
            "dns_callback": False,       # 是否需要 DNS 回调服务
            "http_callback": False,      # 是否需要 HTTP 回调服务
            "browser_cdp": True,         # 是否需要浏览器 CDP
            "auth_session": False,       # 是否需要登录态
            "screenshot": True,          # 是否需要截图
        }

        # L4: 认知策略基因（v3.5 新增） {vuln_type: {strategy_id: CognitiveStrategyGene}}
        # 记录「进化策略引擎」26 认知策略在进化中的有效度，支撑反馈桥
        self.cognitive: Dict[str, Dict[str, CognitiveStrategyGene]] = {}

    # ---- 持久化 ----

    def load(self) -> "MetaGeneLibrary":
        """从 JSON 加载元基因库"""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._from_dict(data)
            except Exception:
                pass
        return self

    def save(self):
        """保存元基因库到 JSON"""
        self._path.write_text(
            json.dumps(self._to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _to_dict(self) -> Dict:
        return {
            "version": "3.0",
            "strategies": {
                vt: {s: {
                    "strategy": g.strategy, "success_count": g.success_count,
                    "total_count": g.total_count, "success_rate": g.success_rate,
                    "avg_confidence": g.avg_confidence, "first_seen": g.first_seen,
                    "last_used": g.last_used,
                } for s, g in vt_genes.items()}
                for vt, vt_genes in self.strategies.items()
            },
            "target_patterns": {
                k: {
                    "pattern_key": p.pattern_key, "framework_hints": p.framework_hints,
                    "best_strategies": p.best_strategies, "avg_vulns_per_round": p.avg_vulns_per_round,
                    "total_targets": p.total_targets,
                } for k, p in self.target_patterns.items()
            },
            "thresholds": self.thresholds,
            "blind_spots": self.blind_spots,
            "capability_requirements": self.capability_requirements,
            "cognitive": {
                vt: {sid: {
                    "strategy_id": g.strategy_id, "success_count": g.success_count,
                    "total_count": g.total_count, "success_rate": g.success_rate,
                    "avg_fitness_gain": g.avg_fitness_gain, "first_seen": g.first_seen,
                    "last_used": g.last_used,
                } for sid, g in vt_genes.items()}
                for vt, vt_genes in self.cognitive.items()
            },
        }

    def _from_dict(self, data: Dict):
        strategies = data.get("strategies", {})
        for vt, vt_genes in strategies.items():
            self.strategies[vt] = {}
            for s, g in vt_genes.items():
                sg = StrategyGene(strategy=g["strategy"])
                sg.success_count = g.get("success_count", 0)
                sg.total_count = g.get("total_count", 0)
                sg.success_rate = g.get("success_rate", 0.0)
                sg.avg_confidence = g.get("avg_confidence", 0.0)
                sg.first_seen = g.get("first_seen", "")
                sg.last_used = g.get("last_used", "")
                self.strategies[vt][s] = sg

        patterns = data.get("target_patterns", {})
        for k, p in patterns.items():
            tp = TargetPattern(pattern_key=p["pattern_key"])
            tp.framework_hints = p.get("framework_hints", [])
            tp.best_strategies = p.get("best_strategies", {})
            tp.avg_vulns_per_round = p.get("avg_vulns_per_round", 0.0)
            tp.total_targets = p.get("total_targets", 0)
            self.target_patterns[k] = tp

        self.thresholds = data.get("thresholds", self.thresholds)
        self.blind_spots = data.get("blind_spots", {})
        self.capability_requirements = data.get("capability_requirements", self.capability_requirements)

        # L4: 认知策略基因反序列化
        self.cognitive = {}
        for vt, vt_genes in data.get("cognitive", {}).items():
            self.cognitive[vt] = {}
            for sid, g in vt_genes.items():
                cg = CognitiveStrategyGene(strategy_id=g["strategy_id"])
                cg.success_count = g.get("success_count", 0)
                cg.total_count = g.get("total_count", 0)
                cg.success_rate = g.get("success_rate", 0.0)
                cg.avg_fitness_gain = g.get("avg_fitness_gain", 0.0)
                cg.first_seen = g.get("first_seen", "")
                cg.last_used = g.get("last_used", "")
                self.cognitive[vt][sid] = cg

    # ---- L1: 策略基因 ----

    def record_strategy(self, vuln_type: str, strategy: str, success: bool,
                        confidence: float = 0.0, fingerprint: Optional[Dict] = None,
                        timestamp: str = "") -> StrategyGene:
        """记录一次策略执行结果

        Args:
            vuln_type: 漏洞类型
            strategy: 策略名（sqli_union / sqli_blind_time / sqli_oob / xss_tag / ...）
            success: 是否成功
            confidence: 判定置信度
            fingerprint: 目标指纹（用于 L2 目标模式更新）
            timestamp: 时间戳
        """
        if vuln_type not in self.strategies:
            self.strategies[vuln_type] = {}

        if strategy not in self.strategies[vuln_type]:
            self.strategies[vuln_type][strategy] = StrategyGene(
                strategy=strategy, first_seen=timestamp
            )

        gene = self.strategies[vuln_type][strategy]
        gene.total_count += 1
        if success:
            gene.success_count += 1
        gene.success_rate = round(gene.success_count / max(gene.total_count, 1), 3)
        gene.avg_confidence = round(
            (gene.avg_confidence * (gene.total_count - 1) + confidence) / gene.total_count, 3
        )
        gene.last_used = timestamp

        # L2: 更新目标模式
        if fingerprint:
            self._update_target_pattern(vuln_type, strategy, success, fingerprint)

        return gene

    def best_strategy(self, vuln_type: str, fingerprint: Optional[Dict] = None) -> str:
        """获取最佳策略（优先目标模式匹配，其次全局成功率排序）

        Args:
            vuln_type: 漏洞类型
            fingerprint: 目标指纹 {"framework": "PHP", "db": "mysql", ...}

        Returns:
            最佳策略名
        """
        # 1. 目标模式匹配
        if fingerprint:
            pattern_key = self._fingerprint_to_pattern(fingerprint)
            if pattern_key in self.target_patterns:
                tp = self.target_patterns[pattern_key]
                if vuln_type in tp.best_strategies:
                    return tp.best_strategies[vuln_type]

        # 2. 全局成功率排序
        genes = self.strategies.get(vuln_type, {})
        if genes:
            # 按 success_rate 降序，success_rate 相同时按 total_count 降序
            sorted_genes = sorted(
                genes.values(),
                key=lambda g: (g.success_rate, g.total_count),
                reverse=True
            )
            # 至少要有 3 次尝试才信任
            if sorted_genes[0].total_count >= 3:
                return sorted_genes[0].strategy
            # 不够样本量，返回成功率最高的但标记为探索
            return sorted_genes[0].strategy

        # 3. 无历史数据，默认策略
        return "default"

    def strategy_ranking(self, vuln_type: str) -> List[Dict]:
        """获取该漏洞类型的所有策略排名"""
        genes = self.strategies.get(vuln_type, {})
        ranking = sorted(
            [{"strategy": g.strategy, "rate": g.success_rate, "count": g.total_count}
             for g in genes.values()],
            key=lambda x: (x["rate"], x["count"]), reverse=True
        )
        return ranking

    # ---- L4: 认知策略基因（v3.5 新增，反馈桥核心）----

    def record_cognitive_strategy(self, vuln_type: str, strategy_id: str,
                                  success: bool, fitness_gain: float = 0.0,
                                  timestamp: str = "") -> CognitiveStrategyGene:
        """记录一次认知策略在进化中的表现（反馈桥「写回」侧）

        每条认知策略（grafting / s_modify / enc_tunnel …）若促成高适应度个体，
        则在此累积其有效度，供后续进化初始化时按 success_rate 偏置选择。

        Args:
            vuln_type: 漏洞类型
            strategy_id: 认知策略 id（26 认知策略之一）
            success: 该策略是否促成了有效变异（产生更高适应度个体）
            fitness_gain: 相对父代的适应度提升量
            timestamp: 时间戳

        Returns:
            更新后的 CognitiveStrategyGene
        """
        if vuln_type not in self.cognitive:
            self.cognitive[vuln_type] = {}
        if strategy_id not in self.cognitive[vuln_type]:
            self.cognitive[vuln_type][strategy_id] = CognitiveStrategyGene(
                strategy_id=strategy_id, first_seen=timestamp
            )

        gene = self.cognitive[vuln_type][strategy_id]
        gene.total_count += 1
        if success:
            gene.success_count += 1
        gene.success_rate = round(gene.success_count / max(gene.total_count, 1), 3)
        gene.avg_fitness_gain = round(
            (gene.avg_fitness_gain * (gene.total_count - 1) + fitness_gain) / gene.total_count, 4
        )
        gene.last_used = timestamp
        return gene

    def cognitive_bias(self, vuln_type: str, strategy_ids: List[str]) -> Dict[str, float]:
        """为进化器提供认知策略选择权重（反馈桥「读先验」侧）

        基于历史 success_rate 做平滑偏置：
          - 有历史数据的策略按 success_rate 升权；
          - 无数据的策略给基础权重 1.0，保证探索空间不被堵死。

        Returns:
            {strategy_id: weight}，权重均为正，可直接用于 random.choices。
        """
        weights = {}
        for sid in strategy_ids:
            gene = self.cognitive.get(vuln_type, {}).get(sid)
            if gene and gene.total_count >= 2:
                # 平滑：0.5 ~ 2.0 之间按 success_rate 映射
                w = 0.5 + gene.success_rate * 1.5
            else:
                w = 1.0  # 冷启动：公平探索
            weights[sid] = round(w, 3)
        return weights

    def best_cognitive_strategy(self, vuln_type: str) -> Optional[str]:
        """返回该漏洞类型历史上最有效（success_rate 最高且样本足够）的认知策略"""
        genes = self.cognitive.get(vuln_type, {})
        if not genes:
            return None
        ranked = sorted(
            genes.values(),
            key=lambda g: (g.success_rate, g.total_count),
            reverse=True
        )
        if ranked[0].total_count >= 2:
            return ranked[0].strategy_id
        return None

    # ---- L2: 目标模式 ----

    def _fingerprint_to_pattern(self, fp: Dict) -> str:
        """指纹 → 模式 key"""
        parts = []
        fw = fp.get("framework", "").lower()
        db = fp.get("db", "").lower()
        if "php" in fw:
            parts.append("php")
        elif "asp" in fw:
            parts.append("asp")
        elif "java" in fw or "spring" in fw or "jsp" in fw:
            parts.append("java")
        elif "python" in fw or "django" in fw or "flask" in fw:
            parts.append("python")
        elif "node" in fw or "express" in fw:
            parts.append("nodejs")
        else:
            parts.append("unknown")

        if "mysql" in db:
            parts.append("mysql")
        elif "mssql" in db:
            parts.append("mssql")
        elif "postgresql" in db or "postgres" in db:
            parts.append("postgresql")
        elif "oracle" in db:
            parts.append("oracle")
        else:
            parts.append("unknown_db")

        return "_".join(parts)

    def _update_target_pattern(self, vuln_type: str, strategy: str,
                                success: bool, fingerprint: Dict):
        """更新目标模式基因"""
        pattern_key = self._fingerprint_to_pattern(fingerprint)

        if pattern_key not in self.target_patterns:
            self.target_patterns[pattern_key] = TargetPattern(
                pattern_key=pattern_key,
                framework_hints=[fingerprint.get("framework", ""), fingerprint.get("db", "")]
            )

        tp = self.target_patterns[pattern_key]

        # 如果当前策略成功率高，更新最佳策略
        genes = self.strategies.get(vuln_type, {})
        if strategy in genes:
            current_best = tp.best_strategies.get(vuln_type)
            if current_best:
                current_gene = genes.get(current_best)
                new_gene = genes[strategy]
                if current_gene and new_gene.success_rate > current_gene.success_rate:
                    tp.best_strategies[vuln_type] = strategy
            else:
                tp.best_strategies[vuln_type] = strategy

        if success:
            tp.total_targets += 1

    def match_target(self, fingerprint: Dict) -> Optional[Dict]:
        """匹配目标模式，返回最佳策略建议"""
        pattern_key = self._fingerprint_to_pattern(fingerprint)
        if pattern_key in self.target_patterns:
            tp = self.target_patterns[pattern_key]
            if tp.total_targets >= 2:  # 至少挖过 2 个同类目标才信任
                return {
                    "pattern": pattern_key,
                    "similar_targets": tp.total_targets,
                    "best_strategies": dict(tp.best_strategies),
                    "avg_vulns_per_round": tp.avg_vulns_per_round,
                }
        return None

    # ---- L3: 自适应参数 ----

    def adaptive_threshold(self, param_name: str, default: float = 2.0) -> float:
        """获取自适应阈值（从历史数据反推）"""
        if param_name in self.thresholds:
            return self.thresholds[param_name].get("threshold", default)
        return default

    def update_threshold(self, param_name: str, new_value: float,
                         false_positive: bool = False):
        """更新自适应阈值"""
        if param_name not in self.thresholds:
            self.thresholds[param_name] = {"threshold": new_value, "false_positive_rate": 0.0}

        t = self.thresholds[param_name]
        old = t["threshold"]

        if false_positive:
            # 误报 → 收紧阈值（提高）
            t["threshold"] = round(old * 1.1, 2)
            t["false_positive_rate"] = round(t.get("false_positive_rate", 0) + 0.01, 3)
        else:
            # 成功 → 微调（向最优靠近）
            t["threshold"] = round(old * 0.98 + new_value * 0.02, 2)

    # ---- 自适应收敛 ----

    def should_converge(self, round_num: int, vulns_this_round: int,
                        new_surfaces: bool, total_vulns: int,
                        fingerprint: Optional[Dict] = None) -> Tuple[bool, str]:
        """动态判断是否应该收敛（停止本轮）

        Args:
            round_num: 当前轮次
            vulns_this_round: 本轮发现漏洞数
            new_surfaces: 是否发现新攻击面
            total_vulns: 累计漏洞数
            fingerprint: 目标指纹

        Returns:
            (should_stop: bool, reason: str)
        """
        # 1. 无新攻击面 → 收敛
        if not new_surfaces:
            return True, "无新攻击面，收敛"

        # 2. 目标模式匹配：同类目标平均产出已达标
        if fingerprint:
            pattern_key = self._fingerprint_to_pattern(fingerprint)
            if pattern_key in self.target_patterns:
                tp = self.target_patterns[pattern_key]
                if tp.total_targets >= 2 and tp.avg_vulns_per_round > 0:
                    if total_vulns >= tp.avg_vulns_per_round * 1.5:
                        return True, f"产出已达同类目标均值 {tp.avg_vulns_per_round:.1f} 的 1.5 倍，收敛"

        # 3. 连续 2 轮产出递减且最后一轮 < 2 条 → 收敛
        # （由外部调用方追踪）

        # 4. 已经跑了 8 轮以上 → 强制收敛
        if round_num >= 8:
            return True, f"已进行 {round_num} 轮，强制收敛"

        # 5. 本轮 0 产出但有新面 → 再给一轮
        if vulns_this_round == 0 and new_surfaces:
            if round_num <= 3:
                return False, "本轮无产出但有新面，继续探索"
            else:
                return True, f"已 {round_num} 轮，本轮无产出，收敛"

        return False, "继续下一轮"

    # ---- 盲区自知 + 能力声明 + 求助机制 ----

    def register_blind_spot(self, vuln_type: str, reason: str):
        """注册盲区：某种漏洞类型我们没有能力"""
        self.blind_spots[vuln_type] = reason

    def get_blind_spots(self) -> Dict[str, str]:
        """获取所有盲区"""
        return dict(self.blind_spots)

    def has_capability(self, vuln_type: str) -> Tuple[bool, str]:
        """检查是否有能力处理某漏洞类型"""
        if vuln_type in self.blind_spots:
            return False, self.blind_spots[vuln_type]
        return True, "ok"

    def declare_requirements(self, vuln_type: str, strategy: str) -> Dict[str, bool]:
        """声明当前策略需要的 Agent 能力

        Returns:
            {"dns_callback": True, "browser_cdp": False, ...}
        """
        reqs = dict(self.capability_requirements)

        if strategy in ("sqli_oob", "xxe_blind"):
            reqs["dns_callback"] = True
            reqs["http_callback"] = True

        if vuln_type in ("xss_reflected", "xss_stored", "xss_dom"):
            reqs["browser_cdp"] = True
            reqs["screenshot"] = True

        if vuln_type in ("idor", "auth_bypass"):
            reqs["auth_session"] = True

        return reqs

    def request_help(self, context: str, detail: str = "") -> Dict:
        """求助机制：遇到未知情况时生成求助信息"""
        return {
            "type": "help_request",
            "context": context,
            "detail": detail,
            "suggested_action": "请补充指纹信息或手动指定策略",
            "auto_fallback": "将使用通用 Payload 继续尝试",
        }

    # ---- 流程自适应 ----

    def should_skip_phase(self, phase: str, fingerprint: Dict,
                          surfaces: List[Dict]) -> Tuple[bool, str]:
        """判断是否应跳过某五环阶段

        Args:
            phase: "sentinel" | "reflect" | "genepool" | "population" | "arena"
            fingerprint: 目标指纹
            surfaces: 漏洞面列表

        Returns:
            (skip: bool, reason: str)
        """
        vuln_types = [s.get("vuln_type", "") for s in surfaces]

        if phase == "genepool":
            # 静态站点：跳过 XSS
            if fingerprint.get("static", False):
                if all(vt.startswith("xss") for vt in vuln_types):
                    return True, "静态站点，跳过 XSS Payload 生成"

            # 纯 API 站点：跳过文件上传
            if fingerprint.get("api_only", False):
                if "file_upload" in vuln_types:
                    return True, "纯 API 站点，跳过文件上传 Payload 生成"

        return False, ""

    def suggest_team_scale(self, fingerprint: Dict, target_count: int) -> Dict:
        """建议团队规模（弹性伸缩）

        Returns:
            {"agents": 3, "sub_agents": 0, "parallel_targets": 1, "reason": "..."}
        """
        # 大站（多子域名）→ 扩展
        if fingerprint.get("subdomain_count", 0) > 10 or target_count > 5:
            return {
                "agents": 3,
                "sub_agents": 2,
                "parallel_targets": 2,
                "reason": f"大站（{fingerprint.get('subdomain_count', 0)} 子域名），建议并行挖 2 个子域名",
            }

        # 中等站点
        if fingerprint.get("subdomain_count", 0) > 3:
            return {
                "agents": 3,
                "sub_agents": 1,
                "parallel_targets": 1,
                "reason": "中等站点，标准 3 Agent 团队",
            }

        # 小站
        return {
            "agents": 3,
            "sub_agents": 0,
            "parallel_targets": 1,
            "reason": "小站，标准 3 Agent 团队，快速过",
        }

    # ---- 统计 ----

    def get_stats(self) -> Dict:
        """获取元基因库统计摘要"""
        total_strategies = sum(len(v) for v in self.strategies.values())
        total_executions = sum(g.total_count for v in self.strategies.values() for g in v.values())
        total_patterns = len(self.target_patterns)
        total_cognitive = sum(len(v) for v in self.cognitive.values())

        # 最成功的策略
        best_overall = None
        best_rate = 0.0
        for vt, genes in self.strategies.items():
            for s, g in genes.items():
                if g.total_count >= 5 and g.success_rate > best_rate:
                    best_rate = g.success_rate
                    best_overall = f"{vt}:{s}"

        return {
            "total_vuln_types": len(self.strategies),
            "total_strategies": total_strategies,
            "total_executions": total_executions,
            "total_target_patterns": total_patterns,
            "total_cognitive_strategies": total_cognitive,
            "best_strategy": best_overall,
            "best_rate": best_rate,
            "blind_spots": len(self.blind_spots),
        }
