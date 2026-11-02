const fs=require('fs');
const d=JSON.parse(fs.readFileSync('cells_result.json','utf8'));
const F=Object.keys(d.files);
for(const c of d.cells){
  const parts=[];
  for(const f of F){
    const p=c.perFile[f];
    if(!p){parts.push('NO_ENTRIES');continue;}
    parts.push(`n=${p.entries} filled=${p.filled} b5=${p.basis['5']||0} emptyStr=${p.emptyStrPayload} emptyP=${p.emptyPayload} nullP=${p.nullPayload}`);
  }
  console.log(`${c.kind}\t${parts.join(' | ')}`);
}
console.log('=== detail for never-filled or partially-empty cells ===');
for(const c of d.cells){
  const interesting = !c.everFilled || F.some(f=>{const p=c.perFile[f];return p&&(p.emptyStrPayload>0||p.basis['5']>0);});
  if(!interesting) continue;
  console.log('---', c.kind);
  for(const f of F){
    const p=c.perFile[f]; if(!p){console.log('  ',f,'NO_ENTRIES');continue;}
    console.log('  ', f.split(/[\\/]/).pop(), `n=${p.entries} filled=${p.filled}`, 'basis='+JSON.stringify(p.basis), `emptyStr=${p.emptyStrPayload}`);
    for(const s of p.samplesFilled) console.log('     FILLED:', JSON.stringify(s));
    for(const s of p.samples) console.log('     EMPTY/ABSENT:', JSON.stringify(s));
  }
}
