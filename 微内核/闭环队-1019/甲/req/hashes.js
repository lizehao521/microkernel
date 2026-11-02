const fs=require('fs'),cr=require('crypto');
for(const f of ['tools_list.json','celltable.txt','peekB.txt','analyze_out.txt','census.txt','baseline.txt']){
  const b=fs.readFileSync(f);
  console.log(f+' bytes='+b.length+' sha256='+cr.createHash('sha256').update(b).digest('hex'));
}
