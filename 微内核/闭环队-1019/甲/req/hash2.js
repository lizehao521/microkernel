const fs=require('fs'),cr=require('crypto');
for(const f of ['decode.js','analyze.js','census.js','dump1.js','peekB.txt','peekA.js']){
  try{const b=fs.readFileSync(f);console.log(f+' bytes='+b.length+' sha256='+cr.createHash('sha256').update(b).digest('hex'));}catch(e){console.log(f+' ERR '+e.message);}
}
