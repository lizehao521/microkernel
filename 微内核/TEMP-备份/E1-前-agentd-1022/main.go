package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
)

// 退出码各管一种结束原因（这一条是收口那块的要求，不是给好看用的）：
//
//	0 跑完剧本 / 2 驱动这一路跑不了 / 3 轮次额度到 / 4 账上 fail_kind 指向「停」/ 5 这本账已到上限 / 6 外部打断
const (
	rcScript = 0
	rcNotRun = 2
	rcTurns  = 3
	rcPolicy = 4
	rcCapped = 5
	rcAbort  = 6
)

func main() {
	var (
		driverName = flag.String("driver", "scripted", "驱动：scripted（本地剧本，不开 socket）/ fake（本机假端点，真过网线）/ real / session")
		shotDelay  = flag.Duration("shot-delay", 0, "每发之前等多久（真端点本来就慢；也让外部打断来得及被看见）")
		script     = flag.String("script", "full", "剧本：full（跑到按账停）/ happy（跑到剧本完）")
		session    = flag.String("session", "agentd-"+strconv.Itoa(os.Getpid()), "session 轴：一发由 session+发号+侧三个轴定身份")
		maxTurns   = flag.Int("max-turns", 12, "最多发几发；到就停（这是「额度到」那一种结束原因）")
		ckptEvery  = flag.Int("checkpoint-every", 0, "每几发编一次账交出去；0 = 只在收口编")
		journal    = flag.String("journal-out", defaultJournalPath(), "宿主把编出的字节写到这个文件（内核不写盘）；空 = 只编不写")
		payload    = flag.String("payload", "included", "编账时带不带原像：included / omitted")
		readBack   = flag.Bool("read-back", true, "关掉它 = 那条回边断开（反臂：KPI 必须回到 0）")
		declare    = flag.Bool("declare-readers", true, "读到的格顺手声明读者（框架侧那一半）")
		entryCap   = flag.Int("entry-cap", 0, "这本账最多写多少条；0 = 不拦")
		traceOut   = flag.String("trace-out", filepath.Join(os.TempDir(), "agentd-轨迹.html"), "循环跑完吐一份能点开的轨迹解剖；空 = 不写")
		resumePath = flag.String("resume", "", "读回上一次 checkpoint 出来的账接着跑（先核链，不符就不往下写）")
		skipOut    = flag.Int("skip-outcomes", 0, "剧本：跳过前 N 个结局（配合 --resume 演「重启后接着跑」）")
	)
	flag.Parse()

	// 横幅只走 stderr：stdout 留给能被逐字比对的运行正文。
	fmt.Fprintf(os.Stderr, "agentd：驱动=%s（自主=%v）；session=%s；读回=%v；声明读者=%v\n",
		*driverName, driverAutonomous(*driverName, *script), *session, *readBack, *declare)
	if *driverName == "scripted" {
		fmt.Fprint(os.Stderr, "  注意：这一路是剧本走出来的绿，不是模型自主决定的绿。\n")
	}

	drv, err := buildDriver(*driverName, *script)
	if err != nil {
		fmt.Fprintln(os.Stderr, "agentd:", err)
		os.Exit(rcNotRun)
	}
	if s, ok := drv.(*scripted); ok && *skipOut > 0 {
		if *skipOut > len(s.q) {
			fmt.Fprintf(os.Stderr, "agentd: 剧本只有 %d 个结局，跳不过 %d 个\n", len(s.q), *skipOut)
			os.Exit(rcNotRun)
		}
		s.i = *skipOut
	}
	r := &run{
		rpc:             newKernelRPC(*entryCap, false),
		drv:             drv,
		session:         *session,
		maxTurns:        *maxTurns,
		checkpointEvery: *ckptEvery,
		readBack:        *readBack,
		declare:         *declare,
		journalPath:     *journal,
		payload:         *payload,
		log:             os.Stdout,
		declared:        map[string]bool{},
		tracePath:       *traceOut,
		caveat: "KPI 数的是「账驱动过几步决定」，不是「模型有多聪明」；" +
			"这一份是循环自己的轨迹解剖，不是 kaudit 那块只读面板（那三件决定还没圈）。",
	}
	abort := make(chan struct{})
	r.abort = abort
	r.shotDelay = *shotDelay
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, os.Interrupt)
	go func() {
		select {
		case <-sigs:
			fmt.Fprintln(os.Stderr, "agentd: 收到打断信号 —— 先把这一段已经落进账的东西交出去再走")
			close(abort)
		case <-abort:
		}
	}()
	r.say("任务：%s（只用一个两数相加的工具，一步步来）", userAsk)
	if *resumePath != "" {
		if !r.resume(*resumePath) {
			r.closeOut()
			if c, ok := drv.(Closer); ok {
				_ = c.Close()
			}
			os.Exit(exitOf(r.stop))
		}
	}
	r.loop()
	r.closeOut()
	if c, ok := drv.(Closer); ok {
		_ = c.Close() // 本机假端点收口：这一趟开的那只耳朵要关掉
	}
	os.Exit(exitOf(r.stop))
}

func exitOf(s stopReason) int {
	switch s {
	case stopScript:
		return rcScript
	case stopTurns:
		return rcTurns
	case stopPolicy:
		return rcPolicy
	case stopCapped:
		return rcCapped
	case stopAbort:
		return rcAbort
	default:
		return rcNotRun
	}
}

func defaultJournalPath() string {
	return filepath.Join(os.TempDir(), "agentd-journal.jsonl")
}

func driverAutonomous(name, script string) bool {
	d, err := buildDriver(name, script)
	if err != nil {
		return false
	}
	return d.Autonomous()
}
