const fs=require('fs');
const d=JSON.parse(fs.readFileSync('cells_result.json','utf8'));
const F=Object.keys(d.files);
for(const c of d.cells){
  const parts=[];
  for(const f of F){
    const p=c.perFile[f];
    if(!p){parts.push('ABSENT_FILE');continue;}
    parts.push(`n=${p.entries} filled=${p.filled} b5=${p.basis['5']||0} b0=${p.basis['0']||0} nullP=${p.nullPayload} emptyP=${p.emptyPayload} nonE=${p.nonEmptyPayload}`);
  }
  console.log(`${c.kind}\t${parts.join(' | ')}`);
}
console.log('=== samples for fail_status / retry_after_ms / fail_detail ===');
for(const c of d.cells){
  if(['fail_status','retry_after_ms','fail_detail'].includes(c.key)&&c.side==='output'){
    for(const f of F){
      const p=c.perFile[f]; if(!p)continue;
      console.log(c.kind, f.replace(/\\/g,'/').split('/').pop(), JSON.stringify(p.basis));
      for(const s of p.samples) console.log('   ', JSON.stringify(s));
    }
  }
}
