import json, re, hashlib, sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
project = Path(__file__).resolve().parents[4]
p = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'G2-SBOM-CycloneDX-草案.json'
raw = p.read_bytes()
bom = json.loads(raw.decode('utf-8'))

fails = []
ok = []

def chk(cond, msg):
    (ok if cond else fails).append(msg)

chk(bom.get('bomFormat') == 'CycloneDX', 'bomFormat=CycloneDX')
chk(bom.get('specVersion') == '1.5', 'specVersion=1.5')
serial = bom.get('serialNumber', '')
chk(bool(re.fullmatch(r'urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', serial)), 'serialNumber 为 UUID URN')
chk(isinstance(bom.get('version'), int), 'version 为整数')
ts = bom.get('metadata', {}).get('timestamp', '')
chk(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', ts)), 'metadata.timestamp RFC3339')

comps = bom.get('components', [])
chk(len(comps) == 16, f'components=16（实际 {len(comps)}）')
refs = [c.get('bom-ref') for c in comps]
chk(len(set(refs)) == len(refs), 'bom-ref 唯一')
chk(all(c.get('type') and c.get('name') and c.get('bom-ref') for c in comps), '每组件含 type/name/bom-ref')

allowed = {'measured', 'absent', 'not_run'}
bad_evidence = []
for c in comps:
    props = {x.get('name'): x.get('value') for x in c.get('properties', [])}
    ev = props.get('ak:evidence')
    if ev not in allowed:
        bad_evidence.append((c['bom-ref'], ev))
chk(not bad_evidence, f'每组件 ak:evidence ∈ {sorted(allowed)}' + ('' if not bad_evidence else f'（异常 {bad_evidence}）'))

# file components hash check
expected = {
    'ak-tool-slice-verify': root / '工具/切片与校验.js',
    'ak-tool-trial-zip': root / '工具/打非作者试读包.py',
    'ak-bin-kaudit': project / '构建-1017/agentkernel/bin/kaudit.exe',
    'ak-bin-kcheck': project / '构建-1017/agentkernel/bin/kcheck.exe',
    'ak-bin-kresearch': project / '构建-1017/agentkernel/bin/kresearch.exe',
    'ak-bin-mcphttp': project / '构建-1017/agentkernel/bin/mcphttp.exe',
    'ak-bin-mcpkernel': project / '构建-1017/agentkernel/bin/mcpkernel.exe',
}
by_ref = {c['bom-ref']: c for c in comps}
missing_actual = [r for r, f in expected.items() if not f.exists()]
chk(not missing_actual, '文件组件对应实体全部存在' + ('' if not missing_actual else f'（缺 {missing_actual}）'))
hash_bad = []
for r, f in expected.items():
    if not f.exists():
        continue
    c = by_ref.get(r)
    if not c:
        hash_bad.append((r, 'component missing'))
        continue
    hashes = c.get('hashes', [])
    sha = next((h.get('content') for h in hashes if h.get('alg') == 'SHA-256'), None)
    actual = hashlib.sha256(f.read_bytes()).hexdigest()
    if sha != actual:
        hash_bad.append((r, sha, actual))
chk(not hash_bad, '7 个文件组件 SHA-256 与实体一致' + ('' if not hash_bad else f'（不符 {hash_bad}）'))

# dependency graph
deps = bom.get('dependencies', [])
chk(len(deps) == 8, f'dependencies=8（实际 {len(deps)}）')
dangling = []
self_edges = []
for d in deps:
    if d.get('ref') not in by_ref:
        dangling.append(d.get('ref'))
    for t in d.get('dependsOn', []):
        if t not in by_ref:
            dangling.append(t)
        if t == d.get('ref'):
            self_edges.append(t)
chk(not dangling, '依赖边全部可解析' + ('' if not dangling else f'（悬空 {dangling}）'))
chk(not self_edges, '无自环')

# schema-validation status
meta_props = {x.get('name'): x.get('value') for x in bom.get('metadata', {}).get('properties', [])}
chk(meta_props.get('ak:sbom:schema-validation') == 'NOT_RUN', 'metadata 声明 schema-validation=NOT_RUN')
chk(meta_props.get('ak:sbom:completeness') == 'not-complete', 'metadata 声明 completeness=not-complete')

# secret scan
text = raw.decode('utf-8')
patterns = [
    r'sk-[A-Za-z0-9]{20,}',
    r'AKIA[0-9A-Z]{16}',
    r'ghp_[A-Za-z0-9]{30,}',
    r'Bearer\s+[A-Za-z0-9._-]{20,}',
    r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
]
hits = []
for pat in patterns:
    for m in re.finditer(pat, text):
        hits.append((pat, m.group(0)[:12]))
chk(not hits, '密钥正则 5 类 0 命中' + ('' if not hits else f'（命中 {hits}）'))

print('OK', len(ok), 'FAIL', len(fails))
for m in ok:
    print('OK  ', m)
for m in fails:
    print('FAIL', m)
print('components', len(comps), 'deps', len(deps), 'bytes', len(raw))
print('sha256', hashlib.sha256(raw).hexdigest())
sys.exit(1 if fails else 0)
