const fs=require('fs');
const F=[['L1018','C:/Users/Admin/Desktop/\u5fae\u5185\u6838/\u6784\u5efa-1017/\u5ba2\u670d\u9776\u573a/\u5bfc\u51fa/\u8d26\u672c-\u5168\u91cf-1018.jsonl'],['L8799','C:/Users/Admin/Desktop/\u5e97\u9762\u6e38\u620f/\u8d26\u672c-8799-\u7b2c\u4e8c\u6b21\u5feb\u7167-included.jsonl']];
function realVal(o){
  if(o.basis===5) return false;
  let s='';
  if(typeof o.payload_b64==='string'){ try{ s=Buffer.from(o.payload_b64,'base64').toString('utf8'); }catch(e){ return true; } }
  const t=s.trim();
  return !(t===''||t==='""'||t==='null');
}
const per={};
for(const [tag,p] of F){ per[tag]={};
  for(const ln of fs.readFileSync(p,'utf8').split('\n')){
    const s=ln.trim(); if(!s||s[0]!=='{')continue;
    let o; try{o=JSON.parse(s);}catch(e){continue;}
    if(!per[tag][o.kind]) per[tag][o.kind]={total:0,real:0};
    per[tag][o.kind].total++; if(realVal(o)) per[tag][o.kind].real++;
  }
}
const kinds=Object.keys(Object.assign({},per.L1018,per.L8799)).sort();
function never(tag){return kinds.filter(k=>!(per[tag][k]&&per[tag][k].real>0));}
const nA=never('L1018'), nB=never('L8799');
const nBoth=kinds.filter(k=>!(per.L1018[k]&&per.L1018[k].real>0) && !(per.L8799[k]&&per.L8799[k].real>0));
console.log('kinds:',kinds.length);
console.log('');
console.log('L1018 never-really-filled:',nA.length); console.log('  '+nA.join('\n  '));
console.log('');
console.log('L8799 never-really-filled:',nB.length); console.log('  '+nB.join('\n  '));
console.log('');
console.log('BOTH never-really-filled:',nBoth.length); console.log('  '+nBoth.join('\n  '));
