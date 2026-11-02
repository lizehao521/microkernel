import json, uuid, hashlib, pathlib

NS = uuid.UUID('6ba7b811-9dad-11d1-80b4-00c04fd430c8')
serial = 'urn:uuid:' + str(uuid.uuid5(NS, 'https://agentkernel.local/sbom/pilot-2026-10-20/v1'))
root = pathlib.Path(__file__).resolve().parents[4]
js = root / '市场报告-1020/试点-1020/工具/切片与校验.js'
py = root / '市场报告-1020/试点-1020/工具/打非作者试读包.py'

bins = {
    'kaudit': '3a9c863dfdc58c365cb2f850085a460d5c71c60060dfd5748f5f06c287c8ebf6',
    'kcheck': '1858e0892d2462b0bf5c32d169d1d4154fee1a831fb078c391d760a941c9c67c',
    'kresearch': '9dca0d37f39ee6761edd77ba729ab5fa9b8a6a9f5ea448c17107d1603260bb44',
    'mcphttp': 'f60617409932b57ce164007a1f56742ee2a731abf18451513b40b728524cd0a7',
    'mcpkernel': '468c6e322e59c899606dd45f2904b22cd5291e4ef9aa175c1c1b07bc5a0a7519',
}
sizes = {'kaudit': 10092032, 'kcheck': 6529024, 'kresearch': 11999744, 'mcphttp': 13125632, 'mcpkernel': 6090240}

def h(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

def prop(n, v):
    return {'name': n, 'value': str(v)}

def comp(t, ref, name, version=None, **kw):
    c = {'type': t, 'bom-ref': ref, 'name': name}
    if version is not None:
        c['version'] = version
    for k, v in kw.items():
        if v is not None:
            c[k] = v
    return c

comps = []
comps.append(comp('file', 'ak-tool-slice-verify', '工具/切片与校验.js', 'v2',
    hashes=[{'alg': 'SHA-256', 'content': h(js)}],
    properties=[prop('ak:domain', 'tools'), prop('ak:distribution', 'trial-pack'),
                prop('ak:bytes', js.stat().st_size),
                prop('ak:path', '市场报告-1020/试点-1020/工具/切片与校验.js'),
                prop('ak:runtime', 'ak-node-runtime'), prop('ak:evidence', 'measured')]))
comps.append(comp('file', 'ak-tool-trial-zip', '工具/打非作者试读包.py', 'v1',
    hashes=[{'alg': 'SHA-256', 'content': h(py)}],
    properties=[prop('ak:domain', 'tools'), prop('ak:distribution', 'build-only'),
                prop('ak:bytes', py.stat().st_size),
                prop('ak:path', '市场报告-1020/试点-1020/工具/打非作者试读包.py'),
                prop('ak:build-runtime', 'ak-python-runtime'), prop('ak:evidence', 'measured')]))
comps.append(comp('application', 'ak-kernel-src', 'agentkernel', '(devel)',
    properties=[
        prop('ak:domain', 'kernel'),
        prop('ak:source-manifest-sha256', '049af7f6ac0395e77e1d7d34fd9486ecf59ec66f576383531b623877a729c856'),
        prop('ak:source-files', '35 .go + go.mod (release fingerprint 35/35)'),
        prop('ak:source-tree', '35 .go + go.mod; tasks/probe/omitjournal/main.go excluded from release fingerprint'),
        prop('ak:go-mod-sha256', 'aee4a04c2108218c26f18c4f86e61f761791c2d74bdb96c60814dd3b5d173407'),
        prop('ak:external-modules', '0'), prop('ak:vcs', 'absent'),
        prop('ak:build-tool', 'ak-go-stdlib'),
        prop('ak:build-outputs', 'ak-bin-kaudit, ak-bin-kcheck, ak-bin-kresearch, ak-bin-mcphttp, ak-bin-mcpkernel'),
        prop('ak:evidence', 'measured')]))
for n, sha in bins.items():
    comps.append(comp('file', 'ak-bin-' + n, n + '.exe', '(devel)',
        hashes=[{'alg': 'SHA-256', 'content': sha}],
        properties=[prop('ak:domain', 'kernel'), prop('ak:bytes', sizes[n]),
                    prop('ak:path', '构建-1017/agentkernel/bin/' + n + '.exe'),
                    prop('ak:goos', 'windows'), prop('ak:goarch', 'amd64'), prop('ak:cgo', '0'),
                    prop('ak:module', 'agentkernel'),
                    prop('ak:go-buildinfo', 'go1.27.2; path=agentkernel/cmd/' + n + '; CGO_ENABLED=0; GOOS=windows; GOARCH=amd64; GOAMD64=v1; module-deps=0; trimpath=absent; vcs=absent'),
                    prop('ak:reproducibility', '5/5 same-host byte-identical'),
                    prop('ak:evidence', 'measured')]))
comps.append(comp('framework', 'ak-go-stdlib', 'Go standard library', '1.27.2',
    properties=[prop('ak:domain', 'toolchain'),
                prop('ak:license-sha256', '911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad'),
                prop('ak:cgo', '0'), prop('ak:toolchain', 'go1.27.2 windows/amd64'),
                prop('ak:evidence', 'measured')]))
for name, ver in [('crypto', 'v0.52.1-0.20260526024921-9beb694f9766'),
                  ('net', 'v0.55.1-0.20260731170536-c1d18010be90'),
                  ('sys', 'v0.45.0'), ('text', 'v0.37.0')]:
    comps.append(comp('library', 'ak-go-x-' + name, name, ver, group='golang.org/x',
        properties=[prop('ak:domain', 'toolchain'), prop('ak:embedded-in', 'GOROOT/src/vendor'),
                    prop('ak:license-sha256', '911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad'),
                    prop('ak:patents-sha256', '96f408bfae65bf137fc2525d3ecb030271c50c1e90799f87abf8846d8dd505cc'),
                    prop('ak:evidence', 'measured')]))
comps.append(comp('platform', 'ak-node-runtime', 'Node.js', '22.23.2',
    hashes=[{'alg': 'SHA-256', 'content': '0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4'}],
    properties=[prop('ak:domain', 'runtime'), prop('ak:distribution', 'not-distributed'),
                prop('ak:scope', 'runtime'), prop('ak:bytes', '86997320'),
                prop('ak:host-path', 'C:/Users/Admin/.codearts/runtimes/node/node.exe'),
                prop('ak:version-output', 'v22.23.2'), prop('ak:evidence', 'measured')]))
comps.append(comp('platform', 'ak-python-runtime', 'Python', '3.14.1',
    hashes=[{'alg': 'SHA-256', 'content': '3179d8b7d28ccc7547e59c3080bf2f715442b692c33798e928fd311f2c97f57b'}],
    properties=[prop('ak:domain', 'runtime'), prop('ak:distribution', 'not-distributed'),
                prop('ak:scope', 'build'), prop('ak:bytes', '106328'),
                prop('ak:host-path', 'C:/Users/Admin/sdk/py314/python.exe'),
                prop('ak:core-dll', 'python314.dll; 6757720 B; SHA-256 ac1223782497ad05c80d34c2216818eb16a25d7687bf1f2596b0b2eb25ca7b5d'),
                prop('ak:abi-dll', 'python3.dll; 74072 B; SHA-256 1fe883c6123a0485af1789c1fc56d7e7bb27eb465f65b154d48d1181c8ca5465'),
                prop('ak:version-output', 'Python 3.14.1'), prop('ak:evidence', 'measured')]))
comps.append(comp('operating-system', 'ak-os-windows', 'Windows',
    properties=[prop('ak:domain', 'os'),
                prop('ak:version-inventory', 'deployment absent; build-host 10.0.22631.6936'),
                prop('ak:build-host-os', '10.0.22631.6936; DisplayVersion=23H2; registry ProductName=Windows 10 Enterprise'),
                prop('ak:build-host-kernel32', '10.0.22621.6931 (WinBuild.160101.0800); 815584 B; SHA-256 C8088D514F1A6F7421CF00534CF9EC7AF6F1E9D1AF186417F2B23934606C5AD7'),
                prop('ak:imports', 'kernel32.dll (5/5 binaries)'),
                prop('ak:forwarders', 'absent'),
                prop('ak:evidence', 'absent'),
                prop('ak:reason', 'deployment OS/DLL versions not inventoried; build-host readings recorded; target machine decides')]))

deps = [
    {'ref': 'ak-tool-slice-verify', 'dependsOn': ['ak-node-runtime']},
    {'ref': 'ak-tool-trial-zip', 'dependsOn': ['ak-python-runtime']},
    {'ref': 'ak-go-stdlib', 'dependsOn': ['ak-go-x-crypto', 'ak-go-x-net', 'ak-go-x-sys', 'ak-go-x-text']},
]
for n in bins:
    deps.append({'ref': 'ak-bin-' + n, 'dependsOn': ['ak-go-stdlib', 'ak-os-windows']})

bom = {
    'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'serialNumber': serial, 'version': 1,
    'metadata': {
        'timestamp': '2026-10-20T00:00:00Z',
        'tools': {'components': [{'type': 'application', 'name': 'agentkernel-sbom-handbuilt', 'version': '0.1.0'}]},
        'component': {'type': 'application', 'bom-ref': 'ak-pilot-service',
                      'name': 'agentkernel evidence package pilot', 'version': '2026-10-20-draft',
                      'description': 'Author-side draft export of two domain SBOM drafts; not a complete product SBOM.'},
        'properties': [
            prop('ak:sbom:status', 'draft'),
            prop('ak:sbom:completeness', 'not-complete'),
            prop('ak:sbom:schema-validation', 'NOT_RUN'),
            prop('ak:sbom:scope', 'pilot tools + kernel source/binaries'),
            prop('ak:sbom:source-documents', 'G2-SBOM-试点工具.md; G2-SBOM-内核模块.md'),
            prop('ak:sbom:dependency-semantics', 'runtime edges only; build relations are recorded in ak:build-* properties'),
            prop('ak:sbom:nonclaim', 'not complete; not a security review; vulnerability scan NOT_RUN; no schema validation'),
            prop('ak:sbom:generated-by', 'author-side manual export; no network'),
        ]
    },
    'components': comps,
    'dependencies': deps,
}

out = root / '市场报告-1020/试点-1020/G2-SBOM-CycloneDX-草案.json'
out.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print('serial', serial)
print('components', len(comps), 'deps', len(deps), 'bytes', out.stat().st_size)
print('sha256', hashlib.sha256(out.read_bytes()).hexdigest())
