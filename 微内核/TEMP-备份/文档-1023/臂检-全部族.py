#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""六族臂检合一（M5 工具债 #113-1）：A/B(17) + C(9) + D(10) + E(5) + F(7) + G(相位表同源 6) = 54 根。

取代件：臂检-事件层-1022.py / 臂检-C族-E3.py / 臂检-D族-E4.py / 臂检-E族-E3补丁.py / 臂检-F族-结算牙.py。
旧件暂留盘上标了「已被取代」，逐根 verdict 对照（合并前后同一棵树现跑）落在
读数/合并前后对照-臂根.md，核完读数前不删旧件。「两套闸并存」从结构上不再可能，就是这一件的目的。

用法（工作目录 事件层-1022）：
    C:/Users/Admin/sdk/py314/python.exe 臂检-全部族.py <go.exe> <内核树根>

规矩（逐根，与合并前五件一致）：
    先跑未变异对照（必须绿）→ 落变异（必须红）→ 还原 → 下一根。
    编译崩不算红（mutant_build_broken 单列）；进程崩单列（E/G 族带 panic 观测）。

退出码：0 = 全部咬且对照全绿；3 = 有对照不绿（现场问题，这一族读数全作废）；
    5 = 有 NOT-WIRED（变异没接上，尺子自己漂了）；2 = 有 BLIND/BROKEN（判据没接住接上了的变异）。
    多种并存按 3 > 5 > 2 取先。

两个额外要求（都是本轮踩过的坑，写死在这里）：

① NOT-WIRED 与 BLIND 绝不并档。
   锚文本命中数不等于预期值 ⇒ verdict=NOT-WIRED：变异根本没接上，这根针这一趟**没被量过**，
   修法回到尺子（改锚文本）。BLIND ⇒ 变异接上了、测试却仍然绿：修法回到判据本体（加牙）。
   两种红法处置完全不同，并成一档就会互相冒充。
   实例：countsFor(r.turns) 改名成 countsFor(r.session, r.turnNo()) 之后，旧 C 件的锚命中 0 次，
   一度被报成 blind —— 那是尺子漂了，不是判据没牙。这一件把它单列成 NOT-WIRED，退出码 5。

② -run 隔离为什么必要（不许改成「整包跑」）。
   本树的 TestSameRulerAsShippedKernel（same_ruler_test.go:22）依赖**树外**的交付件 exe：
   findShippedKernel 往上找 构建-1017/agentkernel/bin/mcpkernel.exe（same_ruler_test.go:279），
   找不到就 t.Fatalf —— 臂检的树副本建在 %TEMP%，那里没有 构建-1017，所以这一支在任何副本里**恒红**。
   若去掉 -run 改跑整包：变异趟 rc!=0 恒成立（红来自那支恒红的针，不来自判据），
   「整包是否红」的变异读数会被污染成**全咬**——每一根都假绿成真咬。
   所以每根臂都必须用 -run '^TestX$|^TestY$' 只点自己那几支测试。

产物：读数/臂检-全部族.jsonl（逐根结构化读数）+ 臂检-全部族-读数.md。控制台只走 ASCII（GBK 会崩）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ANCHORS_ONLY = "--anchors-only" in sys.argv[1:]
_args = [a for a in sys.argv[1:] if a != "--anchors-only"]
GO = _args[0] if len(_args) > 0 else ""
SRC = _args[1] if len(_args) > 1 else ""
if not SRC or not os.path.isdir(SRC) or not GO or not os.path.isfile(GO):
    print("usage: python all-family-arms.py <go.exe> <tree-root> [--anchors-only]")
    sys.exit(4)

# broken 判定的谓词按族保留合并前原样 —— 逐根 verdict 要与合并前可比，谓词不许中途换。
BRK_AB = ("[build failed]", "cannot use", "undefined:", "expected")
BRK_STD = ("[build failed]", "cannot use", "undefined:", "declared and not used")

# 每根臂 = (族, 名称, 文件, [(锚, 变异, 预期命中数)], 测试 -run pattern, broken 谓词, 是否观测 panic)
ARMS = []


def add(fam, name, fname, pairs, pat, brk, panic_watch):
    ARMS.append((fam, name, fname, pairs, pat, brk, panic_watch))


# ---------------- A/B 族（原 臂检-事件层-1022.py，17 根） ----------------
add("AB", "A1 append 改回截断", "events.go",
    [("os.O_CREATE|os.O_WRONLY|os.O_APPEND", "os.O_CREATE|os.O_WRONLY|os.O_TRUNC", 1)],
    "^TestEventLogAppendsAcrossRuns$", BRK_AB, False)
add("AB", "A2 序号判据恒过", "events.go",
    [("func ValidateLog(evs []Event) error {\n\tlast := map[int]int{}",
      "func ValidateLog(evs []Event) error {\n\treturn nil\n}\n\nfunc ValidateLogX(evs []Event) error {\n\tlast := map[int]int{}", 1)],
    "^TestValidateLogArmRejectsDuplicateAndRegress$", BRK_AB, False)
add("AB", "A3 state 白名单拆掉", "events.go",
    [("\tcase !eventStates[e.State]:", "\tcase false:", 1)],
    "^TestAbsentWithoutWhyIsRefusedAndNotWritten$", BRK_AB, False)
add("AB", "A4 计数先于落盘", "events.go",
    [("\tif b.f != nil {\n\t\t// 先落盘（含 Sync）再算落了", "\tif false {\n\t\t// 先落盘（含 Sync）再算落了", 1)],
    "^TestEventSeqMonotonicWithinEachTurn$", BRK_AB, False)
add("AB", "A5 已关闭的守卫拆掉", "events.go",
    [("\tif b.closed {\n\t\treturn fmt.Errorf", "\tif false {\n\t\treturn fmt.Errorf", 1)],
    "^TestClosedBusRefusesNewEvents$", BRK_AB, False)
add("AB", "A6 拒收改回写 stdout", "events.go",
    [('r.errf("    事件层拒了', 'r.say("    事件层拒了', 1)],
    "^TestEmitFailureIsLoudOnStderr$", BRK_AB, False)
add("AB", "A7 撞车守卫拆掉", "main.go",
    [("if clean == j || filepath.Dir(clean) == j {", "if j == \"\" {", 1)],
    "^TestEventLogPathDerivationAndCollision$", BRK_AB, False)
add("AB", "A8 total 一律取额度", "loop.go",
    [("\t\ttotal = done", "\t\ttotal = r.maxTurns", 1)],
    "^TestEventSeqMonotonicWithinEachTurn$", BRK_AB, False)
add("AB", "A9 账满那一形与继续那一形混成一条", "loop.go",
    [('refusedWhy += " ｜ 容量栏挡下 "', 'refusedWhy += " ｜ "', 1)],
    "^TestRefusedEventsCarryTheirWhy$", BRK_AB, False)
add("AB", "A10 收口塞回发级坐标", "loop.go",
    [('settle := Event{Kind: "run_settled", State: "settled", Evidence: "measured"}',
      'settle := r.stepEv("run_settled", "settled", "measured", "", "closeOut", r.shot)', 1)],
    "^TestEventSeqMonotonicWithinEachTurn$", BRK_AB, False)
add("AB", "B1 回执挂点摘掉", "loop.go",
    [("\t\tr.emit(r.acceptedEv())\n", "", 1)],
    "^TestTurnAcceptedLeadsEveryTurn$", BRK_AB, False)
add("AB", "B2 ack 写成恒 0", "events.go",
    [("ms := time.Since(ne.enteredAt).Milliseconds()", "ms := int64(0)", 1)],
    "^TestLateReceiptGoesRed$", BRK_AB, False)
add("AB", "B3 上限调到永远够", "events.go",
    [("const ackLimitMS = 100", "const ackLimitMS = 1 << 40", 1)],
    "^TestLateReceiptGoesRed$", BRK_AB, False)
add("AB", "B4 否定式豁免拆掉", "events.go",
    [("regexp.MustCompile(`(^|[^不])可续`)", "regexp.MustCompile(`可续`)", 1)],
    "^TestAcceptArmsCatchEachBadShape$", BRK_AB, False)
add("AB", "B5 resumable 不落盘", "events.go",
    [('json:"resumable"', 'json:"-"', 1)],
    "^TestResumableFieldSurvivesFalse$", BRK_AB, False)
add("AB", "B6 入口时刻门禁拆掉", "events.go",
    [("case e.Accept != nil && e.enteredAt.IsZero():", "case false:", 1)],
    "^TestReceiptWithoutEntryInstantIsRefused$", BRK_AB, False)
add("AB", "B7 回执判据恒过", "events.go",
    [("func ValidateAccepts(evs []Event) error {",
      "func ValidateAccepts(evs []Event) error {\n\treturn nil\n}\n\nfunc ValidateAcceptsX(evs []Event) error {", 1)],
    "^TestAcceptArmsCatchEachBadShape$", BRK_AB, False)

# ---------------- C 族（原 臂检-C族-E3.py，9 根） ----------------
add("C", "C1 not_reached 恒空（没走到的步骤不交）", "loop.go",
    [("\t\t\tnot = append(not, p)", "\t\t\t_ = p", 1)],
    "^TestInterruptDoesNotFabricateSteps$", BRK_STD, False)
add("C", "C2 补步：所有相都算走过", "loop.go",
    [("\t\tif i <= at {", "\t\tif i <= at || i >= 0 {", 1)],
    "^TestInterruptSettlesWithinSecond$", BRK_STD, False)
add("C", "C3 counts 不现数（人手打空表）", "loop.go",
    [("Counts: r.events.countsFor(r.session, r.turnNo())", "Counts: map[string]int{}", 1)],
    "^TestEveryTurnSettlesExactlyOnce$", BRK_STD, False)
add("C", "C4 幂等守卫拆掉（一发可结多次）", "loop.go",
    [("if r.events == nil || r.settled || r.turns == 0 {", "if r.events == nil || r.turns == 0 {", 1)],
    "^TestSettleTurnIsIdempotent$", BRK_STD, False)
add("C", "C5 打断不结算", "loop.go",
    [('r.settleTurn("interrupted", "等待端点回话时被叫停（-shot-delay 期间）")', "r.settled = true", 1)],
    "^TestInterruptSettlesWithinSecond$", BRK_STD, False)
add("C", "C6 叫停原因被后发的覆盖", "loop.go",
    [("if r.stopWhy == \"\" {", "if true {", 1)],
    "^TestStopEntryIsSingleAndIdempotent$", BRK_STD, False)
add("C", "C7 run 级 stop 写回散文", "loop.go",
    [("\tsettle.Stop = r.stop.Token()", "\tsettle.Stop = string(r.stop)", 1)],
    "^TestEventSeqMonotonicWithinEachTurn$", BRK_STD, False)
add("C", "C8 结算类别散写没门禁", "events.go",
    [('case "completed", "refused", "failed", "interrupted":',
      'case "completed", "refused", "failed", "interrupted", "done":', 1)],
    "^TestSettlementArmsCatchEachBadShape$", BRK_STD, False)
add("C", "C9 被打断也标成 completed", "loop.go",
    [('\tif kind == "interrupted" {\n\t\te.Kind = "turn_interrupted"\n\t\te.State = "interrupted"\n\t}',
      "\tif false {\n\t\te.Kind = \"turn_interrupted\"\n\t\te.State = \"interrupted\"\n\t}", 1)],
    "^TestInterruptDoesNotFabricateSteps$", BRK_STD, False)

# ---------------- D 族（原 臂检-D族-E4.py，10 根） ----------------
add("D", "D1 游标丢 run 轴（退回 session:turn:seq）", "sse.go",
    [('return fmt.Sprintf("%s%s%s%s%d%s%d", e.Session, sseCursorSep, e.Run, sseCursorSep, e.Turn, sseCursorSep, e.Seq)',
      'return fmt.Sprintf("%s%s%d%s%d", e.Session, sseCursorSep, e.Turn, sseCursorSep, e.Seq)', 1)],
    "^TestReplayTwiceGivesSameSequence$|^TestCursorCarriesRunAxis$", BRK_STD, False)
add("D", "D2 坏游标当首连（跳过续传判断）", "sse.go",
    [("if err := ValidateReplay(log, c); err != nil {", "if err := ValidateReplay(log, \"\"); err != nil {", 1)],
    "^TestBadCursorIsNotTreatedAsHead$|^TestReplayJudgeAndHandlerAgreeOnBadCursor$", BRK_STD, False)
add("D", "D3 游标那条被重播（log[idx:]）", "sse.go",
    [("\treturn log[idx+1:]", "\treturn log[idx:]", 1)],
    "^TestReplayTwiceGivesSameSequence$", BRK_STD, False)
add("D", "D4 resumable 恒 false（约定冒充度量）", "events.go",
    [('\treturn true, "断开可续：游标就是日志里的身份四元组，投送层按日志行序取游标之后的尾部"',
      '\treturn false, "断开不能续：写死的约定，没看落点"', 1)],
    "^TestReceiptPayloadIsHonest$|^TestResumableIsMeasuredNotAssumed$", BRK_STD, False)
add("D", "D5 内存模式冒充可续", "events.go",
    [('\t\treturn false, "断开不能续：没有落点，这一趟只在内存数序"',
      '\t\treturn true, "断开可续：内存里也数得着"', 1)],
    "^TestResumableIsMeasuredNotAssumed$", BRK_STD, False)
add("D", "D6 resumable=true 却接不上不判", "sse.go",
    [("\tif *acc.Accept.Resumable {", "\tif false {", 1)],
    "^TestReplayArmsCatchEachBadShape$", BRK_STD, False)
add("D", "D7 同身份多条不判（hits>2）", "sse.go",
    [("\tif hits > 1 {", "\tif hits > 2 {", 1)],
    "^TestReplayArmsCatchEachBadShape$", BRK_STD, False)
add("D", "D8 帧不写 id 行", "sse.go",
    [('fmt.Fprintf(w, "id: %s\\ndata: %s\\n\\n", formatCursor(e), b)',
      'fmt.Fprintf(w, "data: %s\\n\\n", b)', 1)],
    "^TestServedFramesAreLogRows$|^TestReplayTwiceGivesSameSequence$", BRK_STD, False)
add("D", "D9 不分路径都播事件（mux 摘掉）", "sse.go",
    [("srv := &http.Server{Handler: eventsMux(sseHandler(path)), ReadHeaderTimeout: 5 * time.Second}",
      "srv := &http.Server{Handler: sseHandler(path), ReadHeaderTimeout: 5 * time.Second}", 1)],
    "^TestOtherPathGives404$", BRK_STD, False)
add("D", "D10 尾部按 seq 定序（旧写法）", "sse.go",
    [("\treturn log[idx+1:]",
      "\tout := []Event{}\n\tfor _, e := range log {\n\t\tif e.Seq > log[idx].Seq {\n\t\t\tout = append(out, e)\n\t\t}\n\t}\n\treturn out", 1)],
    "^TestCrossRunReplayKeepsLogOrder$", BRK_STD, False)

# ---------------- E 族（原 臂检-E族-E3补丁.py，5 根；保留多站点 pairs 与 panic 观测） ----------------
K = "b.states[blockOf(e)]"
add("E", "E1 counts 键抹掉 run+session 轴（路 A 的 P0 复发）", "events.go",
    [(K, "b.states[blockOf(Event{Turn: e.Turn})]", 6),
     ("blockOf(Event{Session: session, Run: b.run, Turn: turn})", "blockOf(Event{Turn: turn})", 3)],
    "^TestCrossRunCountsArePerRun$", BRK_STD, True)
add("E", "E2 打断时 KPI 清零（计划 E3 点名的反臂）", "loop.go",
    [("DoneBefore: r.shot, KPI: r.kpi},", "DoneBefore: r.shot, KPI: 0},", 1)],
    "^TestInterruptSettlesWithinSecond$", BRK_STD, True)
add("E", "E3 打断时 DoneBefore 归零", "loop.go",
    [("DoneBefore: r.shot, KPI: r.kpi},", "DoneBefore: 0, KPI: r.kpi},", 1)],
    "^TestInterruptSettlesWithinSecond$", BRK_STD, True)
add("E", "E4 打断负载退回空载（针4 变 0==0）", "events_settle_test.go",
    [('if !waitForKind(path, "turn_accepted", 2, 6*time.Second) {',
      'if !waitForEvent(path, "turn_accepted", 3*time.Second) {', 2)],
    "^TestInterruptSettlesWithinSecond$", BRK_STD, True)
add("E", "E5 叫停不查「关过没有」", "loop.go",
    [("if r.abort == nil || r.abortClosed {", "if r.abort == nil || false {", 1)],
    "^TestConcurrentStopClosesAbortExactlyOnce$", BRK_STD, True)

# ---------------- F 族（原 臂检-F族-结算牙.py，7 根） ----------------
F_PAT = "^TestSettlementJudgeCatchesEachBadShape$"
for name, old, new in [
    ("F1 半结算不判（回到 continue）",
     'return fmt.Errorf("第 %d 发有 %d 条事件却没有结算 —— 半结算：循环进去了没收口", t, len(group))', 'continue'),
    ("F2 相位名散写不判", 'if !inPhaseTable(s.Settle.Phase) {', 'if false {'),
    ("F3 结算不带 why 不判", 'if s.Settle.Why == "" {', 'if false {'),
    ("F4 done_before 大于发号不判", 'if s.Settle.DoneBefore < 0 || s.Settle.DoneBefore > t {', 'if false {'),
    ("F5 同趟计数倒退不判", 'if prev, has := prevDone[runKey]; has && s.Settle.DoneBefore < prev {',
     'if prev, has := prevDone[runKey]; has && false {'),
    ("F6 counts 逐名比整条摘掉（只剩加总）", 'if s.Settle.Counts[st] != want[st] {', 'if false {'),
]:
    add("F", name, "events.go", [(old, new, 1)], F_PAT, BRK_STD, False)

# F7 原来指在 reached 循环里那句「表外相名」（events.go 的 `if !has`）。这轮加了 checkPhaseShape 之后，
# 表外名在它前面就被拦下，那句 guard 变成走不到的第二层保险 —— 臂指在冗余层上必然恒绿（假牙），
# 所以把靶搬到**真会开火的那一层**：前缀比对。同一形（条数对、名字表外/顺序错）由这里唯一 owning。
add("F", "F7 reached 前缀比对坏掉（表外名与顺序一起放过）", "events.go",
    [('if i >= len(turnPhases) || turnPhases[i] != p {',
      'if i >= len(turnPhases) || turnPhases[i] != p && false {', 1)],
     "^TestSettlementPhaseShapeJudges$", BRK_STD, False)

# ---------------- G 族（新：相位表同源判据 ValidatePhaseTables 的变异，6 根） ----------------
PHASE_PAT = "^TestPhaseTablesAreSelfConsistent$|^TestPhaseTablesMatchShippedNames$"
TP_OLD = 'var turnPhases = []string{"accept", "work", "check_call", "record_call"}'
add("G", "G1 相位改名只改 turnPhases（phaseKind 没跟上）", "events.go",
    [(TP_OLD, 'var turnPhases = []string{"accept", "work", "check_call", "record_call_v2"}', 1)],
    PHASE_PAT, BRK_STD, False)
add("G", "G2 加相（给没事件对的相硬配一个名）", "events.go",
    [(TP_OLD, 'var turnPhases = []string{"accept", "work", "check_call", "record_call", "read_back"}', 1)],
    PHASE_PAT, BRK_STD, False)
add("G", "G3 删项（phaseKind 里删掉 record_call 一项）", "events.go",
    [('\t"record_call": "recorded",\n', "", 1)],
    PHASE_PAT, BRK_STD, False)
add("G", "G4 stopTokens 改名（script 写成 scrit）", "events.go",
    [('"script": true', '"scrit": true', 1)],
    PHASE_PAT, BRK_STD, False)
add("G", "G5 stopTokens 删项（abort 从词表里掉出去）", "events.go",
    [('"abort": true,', '', 1)],
    PHASE_PAT, BRK_STD, False)
add("G", "G6 多站点同步改名（两表一起改：自洽判据绿、独立期望值必须红）", "events.go",
    [(TP_OLD, 'var turnPhases = []string{"accept", "work_v2", "check_call", "record_call"}', 1),
     ('"work":', '"work_v2":', 1)],

    PHASE_PAT, BRK_STD, False)

# H 族：跨进程续跑那一族（M5 扫端抓到、本轮修）。修之前这三根不会红 —— 因为
# 「resume × 事件日志 × 结算」这个组合今天才有负载（events_resume_axis_test.go）。
RESUME_PAT = "^TestResumedRunContinuesTurnAxis$"
add("H", "H1 发号轴退回不接续（turnFloor 恒 0）", "loop.go",
    [(chr(9)+"r.turnFloor = shots", chr(9)+"r.turnFloor = 0", 1)],
    RESUME_PAT, BRK_STD, False)
add("H", "H2 每发进度额度没跟着接续", "loop.go",
    [("Limit: intp(r.turnFloor + r.maxTurns)},", "Limit: intp(r.maxTurns)},", 1)],
    RESUME_PAT, BRK_STD, False)
add("H", "H3 run 级额度退回本进程绝对分母", "loop.go",
    [("Limit: intp(r.turnFloor + r.maxTurns)}", "Limit: intp(r.maxTurns)}", 2)],
    RESUME_PAT, BRK_STD, False)

# I 族：M5 那五条 P1 的新判据（每条一支臂；针在 events_m5_p1_test.go，红-first 已在改前代码上验过）
P_READ = "^TestReadPathRejectsTamperedRows$"
P_PHASE = "^TestSettlementPhaseShapeJudges$"
P_RUNSET = "^TestRunSettledPresence$"
P_LOST = "^TestResumeLostIsDistinguishable$"
P_LIM = "^TestCheckLogEveryLineCarriesTheLimit$"
add("I", "I1 读回路径不查状态白名单", "events.go",
    [('if !eventStates[e.State] {', 'if false {', 1)], P_READ, BRK_STD, False)
add("I", "I2 读回路径不查出处五档", "events.go",
    [('if !evidenceTiers[e.Evidence] {', 'if false {', 1)], P_READ, BRK_STD, False)
add("I", "I3 读回路径的 absent-why 那一查是空转", "events.go",
    [('return fmt.Errorf("第 %d 条写着 absent 却没带为什么量不到 —— 三态在盘上塌成了一态", i+1)', 'return nil', 1)],
    P_READ, BRK_STD, False)
# I4/I5 第一跑是 BROKEN 不是 BLIND：`if false {` 把 `err :=` 的声明和 range 键 k 的引用一起拆了，
# 编译崩（崩不算红）。改成保留声明与引用、只把条件恒置假的写法 —— 牙还是同一颗，臂才真的接得上。
add("I", "I4 相位形状（前缀与 phase）不判", "events.go",
    [('if err := checkPhaseShape(t, s.Settle); err != nil {',
      'if err := checkPhaseShape(t, s.Settle); err != nil && false {', 1)], P_PHASE, BRK_STD, False)
add("I", "I5 开了账不查 run_settled 存在", "events.go",
    [('if startedRun[k] && !seenRun[k] {', 'if startedRun[k] && false {', 1)], P_RUNSET, BRK_STD, False)
add("I", "I6 接不上不报 resume-lost（与追平同形）", "sse.go",
    [('if lost != "" {', 'if false {', 1)], P_LOST, BRK_STD, False)
add("I", "I7 每行不带上限身份", "checklog.go",
    [('absent 带理由；" + lim},', 'absent 带理由"},', 1)], P_LIM, BRK_STD, False)

# ---------------- J 族（新：E5 的 10s 兜底进度，6 根） ----------------
# 看门狗这条路的坏法分三层：闸门（够不够静默）、冻结（结算后别再补）、说的话（total 有没有）。
# 每层单独一根，红了才知道是哪一层；把三层一起坏掉的写法不作数。
P_TICK = "^TestIdleTickCarriesCheckableProgress$"
P_LATE = "^TestWhyLateWhenTotalIsNotComputable$"
P_FREEZE = "^TestSettleFreezesIdleTicks$"
P_IDLE2 = P_TICK + "|" + P_LATE
add("J", "J1 静默闸门永不够（阈值乘一千，等 60s 才补）", "loop.go",
    [('if !seen || idle < r.tickIdle {', 'if !seen || idle < r.tickIdle*1000 {', 1)], P_IDLE2, BRK_STD, False)
add("J", "J2 冻结的读取端拆掉（结算后照收补位）", "events.go",
    [('if e.idleOnly && b.quiet[blockOf(e)] {', 'if e.idleOnly && false {', 1)], P_FREEZE, BRK_STD, False)
add("J", "J3 冻结的写入端拆掉（countsFor 不再标 quiet）", "events.go",
    [('\tb.quiet[blockOf(Event{Session: session, Run: b.run, Turn: turn})] = true\n', '', 1)], P_FREEZE, BRK_STD, False)
add("J", "J4 算不出也当算得出（why_late 那支不走）", "loop.go",
    [('if total == nil {', 'if false {', 1)], P_LATE, BRK_STD, False)
add("J", "J5 把算不出的 total 编成 0", "loop.go",
    [('Progress: &Progress{Done: done, Total: total, Limit: intp(limit)},',
      'Progress: &Progress{Done: done, Total: intp(0), Limit: intp(limit)},', 1)], P_IDLE2, BRK_STD, False)
add("J", "J6 落盘不盖时刻（静默永远量不到，补位不来）", "events.go",
    [('\tb.last = time.Now()', '\t_ = time.Now()', 1)], P_IDLE2, BRK_STD, False)

add("J", "J7 落点不夹额度（照抄计划，出现 1/6/2 三个数并存）", "loop.go",
    [('if total != nil && *total > limit {', 'if total != nil && false {', 1)], P_TICK, BRK_STD, False)

# ---------------- K 族（新：E8 轨迹页与事件日志同源，4 根） ----------------
# 同源这件事有四种坏法：发数退回内存那份 / 数不到也照印（把没量过写成有数）/
# 只数这一趟的过滤器拆掉（跨趟混列）/ 那句乘法偷偷用 shot 数。各打一根，红了就知道是哪一处。
P_E8A = "^TestTraceTurnCountComesFromEventLog$"
P_E8B = "^TestTraceWithoutEventLogSaysNotMeasured$"
P_E8C = "^TestTraceTurnCountIsPerRun$"
add("K", "K1 发数退回内存里的 shot（不再从日志读）", "trace.go",
    [('shotNote := fmt.Sprintf("事件日志数出来的这一趟共 %d 发", turns)',
      'shotNote := fmt.Sprintf("事件日志数出来的这一趟共 %d 发", r.shot)', 1)], P_E8A, BRK_STD, False)
add("K", "K2 数不到也照印（没量过被写成 0 发）", "trace.go",
    [('\tif !ledgerOK {\n\t\tshotNote = ', '\tif false {\n\t\tshotNote = ', 1)], P_E8B, BRK_STD, False)
add("K", "K3 只数这一趟的过滤器拆掉（上一趟混进来）", "trace.go",
    [('if e.Session != r.session || (rid != "" && e.Run != rid) {',
      'if e.Session != r.session || (rid != "" && e.Run != rid && false) {', 1)], P_E8C, BRK_STD, False)
add("K", "K4 那句「× 49」偷偷用 shot 数（两个投影又分家）", "trace.go",
    [(', turns, turns*49)', ', turns, r.shot*49)', 1)], P_E8A, BRK_STD, False)

# ---------------- L 族（新：E7 三行界面，4 根） ----------------
# 页面的坏法各有专属针：前端自己算口径 / 「没量过」的闸拆掉 / 路由没接 / 列表不设界。
P_PAGE_A = "^TestPageDoesNotComputeAnything$"
P_PAGE_B = "^TestPageRendersWithStubDOM$"
P_PAGE_C = "^TestPageServesThreeRows$"
add("L", "L1 前端开始算口径（塞一个 += 进去）", "web.go",
    [("function cell(k, v) { return k + '=' + txt(v); }",
      "function cell(k, v) { var n = 0; n += 1; return k + '=' + txt(v); }", 1)], P_PAGE_A, BRK_STD, False)
add("L", "L2 「没量过」那道闸拆掉（undefined 直接上屏）", "web.go",
    [("if (v === null || v === undefined || v === '') { return '没量过'; }",
      "if (false) { return '没量过'; }", 1)], P_PAGE_B, BRK_STD, False)
add("L", "L3 页面路由没接（/ 出 404）", "sse.go",
    [('\tmux.Handle("/", pageHandler())\n', '', 1)], P_PAGE_C, BRK_STD, False)
add("L", "L4 日志列不设界（截断那一步不走）", "web.go",
    [("while (ul.children.length > KEEP) { ul.removeChild(ul.lastChild); }",
      "if (false) { ul.removeChild(ul.lastChild); }", 1)], P_PAGE_B, BRK_STD, False)

add("L", "L5 断流时把最后一帧抹了（屏上只剩一句断了）", "web.go",
    [("es.onerror = function () { stream = '断了，重连由浏览器做'; renderNow(); };",
      "es.onerror = function () { stream = '断了，重连由浏览器做'; put('now', stream); };", 1)], P_PAGE_B, BRK_STD, False)
add("L", "L6 后端交过的数被下一帧抹成没量过", "web.go",
    [("if (d.progress) { lastP = d.progress; }", "if (false) { lastP = d.progress; }", 1)], P_PAGE_B, BRK_STD, False)

add("L", "L7 帧回来了但屏上还挂着「断了」（浏览器实测抓到过的假话）", "web.go",
    [("    stream = '在进';", "    stream = '没量过';", 1)], P_PAGE_B, BRK_STD, False)

if ANCHORS_ONLY:
    # 预检模式：不对副本动手，只把每根臂的锚文本在现树上数一遍。
    # NOT-WIRED 的成因（锚漂了 / 签名改了）在这一档几分钟就能定位，不用等整轮臂跑完。
    _files = {}
    _bad = 0
    for _f in sorted({a[2] for a in ARMS}):
        _files[_f] = open(os.path.join(SRC, "cmd", "agentd", _f), encoding="utf-8").read()
    for _fam, _name, _fname, _pairs, _pat, _brk, _pw in ARMS:
        for _old, _new, _want in _pairs:
            _got = _files[_fname].count(_old)
            if _got != _want:
                _bad += 1
                print("%s | %s | %s | anchor hit %d want %d -- NOT WIRED" %
                      (_fam, _name.split()[0], _fname, _got, _want))
    print("arms %d | anchor mismatches %d" % (len(ARMS), _bad))
    sys.exit(5 if _bad else 0)

work = os.path.join(tempfile.gettempdir(), "allfam-" + str(os.getpid()))
# mcpsrv 必须一起拷：cmd/agentd 的 rpc.go 直接 import 它（漏了就是「对照不绿」的假红）。
shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("报告", "tasks"))
keep = {}
for f in sorted({a[2] for a in ARMS}):
    keep[f] = open(os.path.join(work, "cmd", "agentd", f), encoding="utf-8").read()

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "读数")
os.makedirs(out_dir, exist_ok=True)
jsonl_path = os.path.join(out_dir, "臂检-全部族.jsonl")
log = open(jsonl_path, "w", encoding="utf-8", newline="\n")


def run(pat, brk_keys, panic_watch):
    r = subprocess.run([GO, "test", "./cmd/agentd/", "-count=1", "-run", pat],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    # 编译不过 != 判据红：崩不算红（内核老规矩），单列 mutant_build_broken。
    broken = any(k in out for k in brk_keys)
    return r.returncode, out, broken, ("panic:" in out) if panic_watch else False


blind, notwired, ctrl_red, broken_rows = [], [], [], []
rows = []
# 控制台只用 ASCII：GBK 下打 `checkmark / RightArrow` 一类符号会崩，崩掉的是退出码契约。
print("fam | arm | file | test | control_rc | mutant_rc | verdict")
for fam, name, fname, pairs, pat, brk, panic_watch in ARMS:
    aid = name.split()[0]
    src = keep[fname]
    cpath = os.path.join(work, "cmd", "agentd", fname)
    # 锚文本预检：命中数不等于预期值 => NOT-WIRED（变异没接上），不与 BLIND 并档（见文件头 ①）。
    wired, why_nowire = True, []
    for old, _new, want in pairs:
        got = src.count(old)
        if got != want:
            wired = False
            why_nowire.append("hit %d want %d" % (got, want))
    if not wired:
        print("%s | %s | %s | snippet not wired (%s)" % (fam, aid, fname, "; ".join(why_nowire)))
        notwired.append(name)
        log.write(json.dumps({"arm": name, "family": fam, "file": "cmd/agentd/" + fname, "test": pat,
                              "control_rc": None, "mutant_rc": None, "mutant_build_broken": False,
                              "verdict": "NOT-WIRED", "note": "; ".join(why_nowire)}, ensure_ascii=False) + "\n")
        rows.append({"family": fam, "arm": name, "file": "cmd/agentd/" + fname, "test": pat.strip("^$"),
                     "control_rc": "-", "mutant_rc": "-", "verdict": "NOT-WIRED"})
        continue
    # 先跑对照（未变异必须绿），再落变异跑第二遍，最后还原 —— 顺序反了就是拿变异自己当对照。
    rc0, _, b0, _ = run(pat, brk, panic_watch)
    mut = src
    for old, new, _want in pairs:
        mut = mut.replace(old, new)
    open(cpath, "w", encoding="utf-8", newline="\n").write(mut)
    rc1, tail, b1, cr1 = run(pat, brk, panic_watch)
    open(cpath, "w", encoding="utf-8", newline="\n").write(src)
    if rc0 != 0 or b0:
        v = "CONTROL-NOT-GREEN"
        ctrl_red.append(name)
    elif b1:
        v = "BROKEN"
        broken_rows.append(name)
    elif rc1 == 0:
        v = "BLIND"
    elif cr1:
        v = "BIT(进程崩，症状可见)"
    else:
        v = "BIT"
    if v in ("BLIND", "BROKEN"):
        blind.append(name)
    note = "" if v == "BIT" or v.startswith("BIT(") else tail.strip().splitlines()[-1][:140]
    log.write(json.dumps({"arm": name, "family": fam, "file": "cmd/agentd/" + fname, "test": pat,
                          "control_rc": rc0, "mutant_rc": rc1, "mutant_build_broken": b1,
                          "mutant_panicked": cr1, "verdict": v, "note": note}, ensure_ascii=False) + "\n")
    rows.append({"family": fam, "arm": name, "file": "cmd/agentd/" + fname, "test": pat.strip("^$"),
                 "control_rc": rc0, "mutant_rc": rc1, "verdict": v})
    print("%s | %s | cmd/agentd/%s | %s | %d | %d | %s" % (fam, aid, fname, pat.strip("^$"), rc0, rc1, v))
log.close()
shutil.rmtree(work, ignore_errors=True)

n_bit = sum(1 for r in rows if r["verdict"].startswith("BIT"))
md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "臂检-全部族-读数.md")
with open(md, "w", encoding="utf-8", newline="\n") as f:
    f.write("# 六族臂检合一读数（臂检-全部族.py 现跑，勿手抄）\n\n")
    f.write("- 树根：%s\n- 臂 %d 根（按族 A/B %d ｜ C %d ｜ D %d ｜ E %d ｜ F %d ｜ G %d）：咬 %d，BLIND/BROKEN %d，NOT-WIRED %d，对照不绿 %d\n\n" % (
        SRC, len(ARMS),
        sum(1 for a in ARMS if a[0] == "AB"), sum(1 for a in ARMS if a[0] == "C"),
        sum(1 for a in ARMS if a[0] == "D"), sum(1 for a in ARMS if a[0] == "E"),
        sum(1 for a in ARMS if a[0] == "F"), sum(1 for a in ARMS if a[0] == "G"),
        n_bit, len(blind), len(notwired), len(ctrl_red)))
    f.write("| 族 | 编号 | 变异（把修好的那一处改回坏法） | 文件 | 该红的测试 | 对照 rc | 变异 rc | 判定 |\n")
    f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
    for row in rows:
        f.write("| %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
            row["family"], row["arm"].split()[0], row["arm"].split(" ", 1)[1], row["file"],
            row["test"], row["control_rc"], row["mutant_rc"], row["verdict"]))
print("markdown: %s" % md)
print("total %d | bit %d | blind+broken %d | not-wired %d | control-red %d" %
      (len(ARMS), n_bit, len(blind), len(notwired), len(ctrl_red)))
print("readings: %s" % jsonl_path)
for label, lst in (("control not green", ctrl_red), ("not wired", notwired), ("blind/broken", blind)):
    if lst:
        print("%s: %s" % (label, ", ".join(b.split()[0] for b in lst)))
if ctrl_red:
    sys.exit(3)
if notwired:
    sys.exit(5)
if blind:
    sys.exit(2)
print("conclusion: all arms bite, all controls green")
sys.exit(0)
