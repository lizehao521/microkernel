import json, copy, subprocess, sys, tempfile, hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[2]
src = root / 'G2-SBOM-CycloneDX-草案.json'
checker = Path(__file__).with_name('check_cyclonedx.py')
tmpdir = Path(tempfile.gettempdir()) / 'ak-sbom'
tmpdir.mkdir(parents=True, exist_ok=True)
base = json.loads(src.read_text(encoding='utf-8'))

arms = {}

# A1: tamper sha256 of kaudit binary component
b = copy.deepcopy(base)
for c in b['components']:
    if c['bom-ref'] == 'ak-bin-kaudit':
        for h in c['hashes']:
            if h['alg'] == 'SHA-256':
                h['content'] = ('0' if h['content'][0] != '0' else '1') + h['content'][1:]
arms['A1 改二进制哈希'] = b

# A2: dangling dependency edge
b = copy.deepcopy(base)
b['dependencies'][0]['dependsOn'].append('ak-nonexistent')
arms['A2 悬空依赖边'] = b

# A3: remove ak:evidence from one component
b = copy.deepcopy(base)
c = next(x for x in b['components'] if x['bom-ref'] == 'ak-kernel-src')
c['properties'] = [p for p in c.get('properties', []) if p.get('name') != 'ak:evidence']
arms['A3 去掉 evidence'] = b

# A4: duplicate bom-ref
b = copy.deepcopy(base)
b['components'].append(copy.deepcopy(b['components'][0]))
arms['A4 重复 bom-ref'] = b

results = []
for name, obj in arms.items():
    tmp = tmpdir / ('arm-' + hashlib.md5(name.encode()).hexdigest()[:8] + '.json')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    r = subprocess.run([sys.executable, str(checker), str(tmp)], capture_output=True, text=True, encoding='utf-8')
    fails = [ln for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
    results.append((name, r.returncode, fails))

for name, rc, fails in results:
    print(('RED  ' if rc != 0 else 'GREEN'), name, 'rc=' + str(rc))
    for f in fails[:3]:
        print('     ', f)
print('arms', len(results), 'red', sum(1 for _, rc, _ in results if rc != 0))
