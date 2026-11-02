package main

// calc.eval 用的表达式求值：递归下降，只认数字、+ - * / % **、括号与一元负号。
// 为什么不直接借 shell 或 go 解释器：那等于给用户一个"能跑任意代码"的工具，
// 而这个工具的说明书里只承诺了"算一个算式"。

import (
	"fmt"
	"strconv"
	"strings"
)

type exprNode struct {
	kind  byte // 'num' 'bin' 'neg'
	val   float64
	op    byte
	a, b  *exprNode
	input string
}

func evalExpr(s string) (float64, error) {
	p := &exprParser{src: s}
	p.skip()
	n, err := p.parseAdd()
	if err != nil {
		return 0, err
	}
	p.skip()
	if p.pos != len(p.src) {
		return 0, fmt.Errorf("第 %d 个字符附近有多余的东西：%q", p.pos, string(p.src[p.pos]))
	}
	v, err := runNode(n)
	if err != nil {
		return 0, err
	}
	return v, nil
}

type exprParser struct {
	src string
	pos int
}

func (p *exprParser) skip() {
	for p.pos < len(p.src) && (p.src[p.pos] == ' ' || p.src[p.pos] == '\t') {
		p.pos++
	}
}

func (p *exprParser) peek() byte {
	p.skip()
	if p.pos >= len(p.src) {
		return 0
	}
	return p.src[p.pos]
}

func (p *exprParser) parseAdd() (*exprNode, error) {
	left, err := p.parseMul()
	if err != nil {
		return nil, err
	}
	for {
		op := p.peek()
		if op != '+' && op != '-' {
			return left, nil
		}
		p.pos++
		right, err := p.parseMul()
		if err != nil {
			return nil, err
		}
		left = &exprNode{kind: 'b', op: op, a: left, b: right, input: p.src}
	}
}

func (p *exprParser) parseMul() (*exprNode, error) {
	left, err := p.parsePow()
	if err != nil {
		return nil, err
	}
	for {
		op := p.peek()
		if op != '*' && op != '/' && op != '%' {
			return left, nil
		}
		p.pos++
		right, err := p.parsePow()
		if err != nil {
			return nil, err
		}
		left = &exprNode{kind: 'b', op: op, a: left, b: right, input: p.src}
	}
}

// 幂：`a ** b` 与 `a ^ b` 都认，右结合（2**3**2 = 512，不是 64）。
// 之所以在 parseMul 之外单开一层，是因为把 ** 当"两个乘号"就地吃掉会让它左结合，
// 那种写法在这里被发现过一次：2**3**2 出来是 64。
func (p *exprParser) parsePow() (*exprNode, error) {
	base, err := p.parseUnary()
	if err != nil {
		return nil, err
	}
	p.skip()
	if p.pos+1 < len(p.src) && p.src[p.pos] == '*' && p.src[p.pos+1] == '*' {
		p.pos += 2
		exp, err := p.parsePow()
		if err != nil {
			return nil, err
		}
		return &exprNode{kind: 'b', op: '^', a: base, b: exp, input: p.src}, nil
	}
	if p.peek() == '^' {
		p.pos++
		exp, err := p.parsePow()
		if err != nil {
			return nil, err
		}
		return &exprNode{kind: 'b', op: '^', a: base, b: exp, input: p.src}, nil
	}
	return base, nil
}

func (p *exprParser) parseUnary() (*exprNode, error) {
	if p.peek() == '-' {
		p.pos++
		n, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		return &exprNode{kind: 'n', a: n, input: p.src}, nil
	}
	return p.parseAtom()
}

func (p *exprParser) parseAtom() (*exprNode, error) {
	switch c := p.peek(); {
	case c == '(':
		p.pos++
		n, err := p.parseAdd()
		if err != nil {
			return nil, err
		}
		if p.peek() != ')' {
			return nil, fmt.Errorf("括号没闭合（第 %d 个字符附近）", p.pos)
		}
		p.pos++
		return n, nil
	case c == 0:
		return nil, fmt.Errorf("算式在结尾处断了一个数")
	case c >= '0' && c <= '9' || c == '.':
		st := p.pos
		dots := 0
		for p.pos < len(p.src) {
			ch := p.src[p.pos]
			if ch >= '0' && ch <= '9' {
				p.pos++
				continue
			}
			if ch == '.' {
				dots++
				if dots > 1 {
					return nil, fmt.Errorf("第 %d 个字符附近一个数里有两个小数点", p.pos)
				}
				p.pos++
				continue
			}
			break
		}
		f, err := strconv.ParseFloat(p.src[st:p.pos], 64)
		if err != nil {
			return nil, fmt.Errorf("%q 不是数：%v", p.src[st:p.pos], err)
		}
		return &exprNode{kind: 'u', val: f, input: p.src}, nil
	default:
		return nil, fmt.Errorf("第 %d 个字符 %q 这里没法往下读（只认数字 + - * / %% ** 和括号）", p.pos, string(c))
	}
}

func runNode(n *exprNode) (float64, error) {
	switch n.kind {
	case 'u':
		return n.val, nil
	case 'n':
		v, err := runNode(n.a)
		return -v, err
	case 'b':
		a, err := runNode(n.a)
		if err != nil {
			return 0, err
		}
		b, err := runNode(n.b)
		if err != nil {
			return 0, err
		}
		switch n.op {
		case '+':
			return a + b, nil
		case '-':
			return a - b, nil
		case '*':
			return a * b, nil
		case '/':
			if b == 0 {
				return 0, fmt.Errorf("除以 0（%s）", strings.TrimSpace(n.input))
			}
			return a / b, nil
		case '%':
			if b == 0 {
				return 0, fmt.Errorf("模 0（%s）", strings.TrimSpace(n.input))
			}
			return float64(int64(a) % int64(b)), nil
		case '^':
			if a == 0 && b < 0 {
				return 0, fmt.Errorf("0 的负次幂")
			}
			out := 1.0
			exp := int64(b)
			if float64(exp) != b {
				return 0, fmt.Errorf("指数只认整数，给的是 %v", b)
			}
			base := a
			if exp < 0 {
				if base == 0 {
					return 0, fmt.Errorf("0 的负次幂")
				}
				base, exp = 1/base, -exp
			}
			for i := int64(0); i < exp; i++ {
				out *= base
			}
			return out, nil
		}
	}
	return 0, fmt.Errorf("内部错误：没法读的节点")
}
