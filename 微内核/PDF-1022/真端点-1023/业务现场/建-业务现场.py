"""Build the 13-task business fixture under this directory.

Deterministic content; no trailing newline on app.log so text.stats reports
lines=12 / blank=2. Prints ASCII only (GBK console contract).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = {
    "财务/发票-2026-031.txt": """云杉科技 2026 年 3 月服务发票
发票号：INV-2026-0317
项目：
1. 服务器托管 2 台 × 600 元/台 = 1200 元
2. 域名续费 1 个 × 80 元/个 = 80 元
合计：1280 元
""",
    "财务/预算-2026-Q3.txt": """2026 年 Q3 预算：50000 元
已发生：
- 云资源 21800 元
- 外包 15600 元
- 差旅 9400 元
- 软件订阅 4700 元
""",
    "财务/报价/A-云杉科技.txt": """供应商：云杉科技
报价单 Q-2026-0412-A
1. 云主机 8 核 16G × 3 台 × 4200 元 = 12600 元
2. 对象存储 2TB × 1 年 = 3600 元
3. 技术支持 1 年 = 2400 元
总价：18600 元
""",
    "财务/报价/B-北辰云服.txt": """供应商：北辰云服
报价单 Q-2026-0412-B
1. 云主机 8 核 16G × 3 台 × 3900 元 = 11700 元
2. 对象存储 2TB × 1 年 = 3300 元
3. 技术支持 1 年 = 2200 元
总价：17200 元
""",
    "财务/报价/C-海岳数据.txt": """供应商：海岳数据
报价单 Q-2026-0412-C
1. 云主机 8 核 16G × 3 台 × 4500 元 = 13500 元
2. 对象存储 2TB × 1 年 = 3800 元
3. 技术支持 1 年 = 2500 元
总价：19800 元
""",
    "运维/app.log": "\n".join([
        "2026-04-12 09:58:01 INFO  service started",
        "2026-04-12 09:59:12 WARN  cache miss rate 0.42",
        "",
        "2026-04-12 10:00:03 INFO  request id=8812 path=/api/health 200 12ms",
        "2026-04-12 10:00:44 ERROR upstream timeout id=8813",
        "2026-04-12 10:01:02 ERROR retry failed id=8813",
        "2026-04-12 10:01:30 WARN  circuit open",
        "",
        "2026-04-12 10:02:00 INFO  fallback to cache",
        "2026-04-12 10:03:10 INFO  request id=8814 path=/api/tools 200 9ms",
        "2026-04-12 10:04:00 ERROR upstream timeout id=8815",
        "2026-04-12 10:05:00 INFO  recovered",
    ]),
    "运维/incident-0412.txt": """故障编号：INC-2026-0412
开始：2026-04-12 10:00
恢复：2026-04-12 10:45
影响：订单查询接口 5xx，持续期间无法下单
""",
    "运维/SLA.md": """# 服务等级协议（2026 版）

1. 月度可用率不低于 99.9%。
2. 4 月按 30 天计，共 43,200 分钟。
3. 可用率 =（43,200 - 不可用分钟）/ 43,200。
4. 低于 99.9% 视为违约，需在 5 个工作日内提交事故报告。
""",
    "人事/入职清单.txt": """新员工入职材料清单（共 4 项）
1. 身份证复印件
2. 学历证明
3. 体检报告
4. 离职证明（上一家单位）
""",
    "人事/入职材料/身份证复印件.txt": "张伟的身份证复印件（正反面）\n",
    "人事/入职材料/学历证明.txt": "张伟的本科毕业证书与学位证书复印件\n",
    "人事/入职材料/体检报告.txt": "张伟的入职体检报告，结论：合格\n",
    "客户/投诉.csv": """工单号,客户,金额,渠道
T-1038,华东制造,3200,电话
T-1042,北方物流,8800,邮件
T-1045,南方零售,1500,在线
T-1049,西部能源,6400,电话
T-1051,中部传媒,900,在线
""",
    "客户/客户名单.csv": """客户编号,姓名,邮箱
C001,张伟,zhang@example.com
C002,李娜,li@example.com
C003,王强,wang@example.com
C004,赵敏,zhao@example.com
C005,陈晨,chen@example.com
C006,刘洋,liu@example.com
C007,孙悦,sun@example.com
C008,张伟,zhang@example.com
""",
    "报表/4月营收-销售部.txt": """部门：销售部
月份：2026-04
营收：1,250,000 元
口径：含税
""",
    "报表/4月营收-财务部.txt": """部门：财务部
月份：2026-04
营收：1,184,000 元
口径：含税
""",
    "发布/VERSION.txt": "2.4.1\n",
    "发布/CHANGELOG.md": """# 变更日志

## 2.4.0 - 2026-04-10
- 增加批量导出
- 修复登录超时
""",
    "库存/库存.csv": """商品,库存
机械键盘,4
显示器,25
无线鼠标,7
扩展坞,2
USB-C 线,40
""",
}


def main():
    for rel, body in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")
    log = (ROOT / "运维/app.log").read_text(encoding="utf-8")
    lines = log.split("\n")
    blank = sum(1 for x in lines if not x.strip())
    assert len(lines) == 12 and blank == 2, (len(lines), blank)
    manifest = []
    for rel in sorted(FILES):
        p = ROOT / rel
        b = p.read_bytes()
        manifest.append({"path": rel, "bytes": len(b),
                         "sha256": hashlib.sha256(b).hexdigest()})
    (ROOT / "现场清单.json").write_text(
        json.dumps({"files": manifest}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print("files=%d total_bytes=%d log_lines=%d log_blank=%d" %
          (len(manifest), sum(x["bytes"] for x in manifest), len(lines), blank))


if __name__ == "__main__":
    main()
