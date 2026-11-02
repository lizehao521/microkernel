package main

// 内置考卷。dirty 那份是"该红"的样本 —— 尺子量不到它就是尺子坏，不是代码好。
// clean 那份是反臂：干净样本如果被编出 critical，说明判据在凭空红。

const fixtureDirty = `package main

import (
	"fmt"
	"os"
	"strings"
)

func load(p string) string {
	data, _ := os.ReadFile(p)
	seed := len(data)
	seed := seed + 1
	if strings.Contains(string(data), "x") {
		for i := 0; i < 3; i++ {
			switch i {
			case 0:
				fmt.Println("a")
			case 1:
				fmt.Printf("b%d", i)
			}
		}
	}
	return string(data)
}

func helper() int { return 1 }

func helper() int { return 2 }

func main() {
	err := fmt.Errorf("boom")
	if err != nil {
	}
	fmt.Print(load("a.txt"))
}
`

const fixtureClean = `package main

import (
	"fmt"
	"os"
)

func main() {
	data, err := os.ReadFile(os.Args[0])
	if err != nil {
		fmt.Fprintln(os.Stderr, "读不动：", err)
		return
	}
	fmt.Printf("读到 %d 字节\n", len(data))
}
`

const fixturePy = `def go():
    try:
        x = int("2")
    except ValueError:
        pass
    print(x)

# TODO: 之后换成日志
`

// fixtureStack 是"该定位"的考卷：两帧都该落进 fixtureDirty 的行范围里。
const fixtureStack = "panic: runtime error: invalid memory address or nil pointer dereference\n" +
	"[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x47e07f]\n\n" +
	"goroutine 1 [running]:\nmain.load({0x4a1b20, 0x7})\n\t/tmp/demo/main.go:16 +0x42\n" +
	"main.main()\n\t/tmp/demo/main.go:31 +0x1f\nexit status 2\n"

// —— W7：非 Go 的考卷。每族判据都要有一条"该红"的形状在里面 ——

const fixturePyRich = `import json
import os

def load(path, cache=[]):
    try:
        data = open(path).read()
        cache.append(data)
    except:
        pass
    if cache == None:
        print("没有缓存")
    return json.loads(data)

def pick(d):
    return d.get("k")
`

const fixturePyClean = `import json

def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.loads(f.read())
    except FileNotFoundError as e:
        raise RuntimeError("读不到配置") from e
`

const fixtureJSRich = `const fs = require("fs");
var count = 0;

function pick(row) {
  if (row.id == 3) {
    eval(row.formula);
  }
  try {
    fs.readFileSync("a");
  } catch (e) {}
  debugger;
  console.log(row);
  return count;
}
`

// fixtureSecret 里那个值是**哨兵串，不是口令**：它专门用来验证"命中的字面量不许被抄进读数"。
const fixtureSecret = `# 演示件：这不是真口令
api_key = "SENTINEL-VALUE-DO-NOT-USE-0123456789"
`
