const fs=require('fs');
const F=[['L1018','C:/Users/Admin/Desktop/\u5fae\u5185\u6838/\u6784\u5efa-1017/\u5ba2\u670d\u9776\u573a/\u5bfc\u51fa/\u8d26\u672c-\u5168\u91cf-1018.jsonl'],['L8799','C:/Users/Admin/Desktop/\u5e97\u9762\u6e38\u620f/\u8d26\u672c-8799-\u7b2c\u4e8c\u6b21\u5feb\u7167-included.jsonl']];
const acc={};
for(const [tag,p] of F){
  for(const ln of fs.readFileSync(p,'utf8').split('\n')){
    const t=ln.trim(); if(!t||t[0]!=='{')continue;
    let o; try{o=JSON.parse(t);}catch(e){continue;}
    const k=o.kind; if(!acc[k])acc[k]={total:0,absent:0,measuredEmpty:0,measuredNonEmpty:0,perTag:{}};
    const a=acc[k]; a.total++;
    a.perTag[tag]=a.perTag[tag]||{empty:0,nonEmpty:0,absent:0};
    const cl=typeof o.claim==='string'?o.claim.trim():'';
    if(o.basis===5){a.absent++;a.perTag[tag].absent++;}
    else if(cl===''){a.measuredEmpty++;a.perTag[tag].empty++;}
    else {a.measuredNonEmpty++;a.perTag[tag].nonEmpty++;}
  }
}
const ks=Object.keys(acc).sort();
const strictNever=ks.filter(k=>acc[k].measuredNonEmpty===0);
console.log('kinds:',ks.length);
console.log('--- STRICT never-filled (no entry with basis!=5 AND non-empty claim) ---');
console.log('count:',strictNever.length);
for(const k of strictNever){const a=acc[k];console.log(k,'| total',a.total,'| absent',a.absent,'| measuredEmpty',a.measuredEmpty,'| measuredNonEmpty',a.measuredNonEmpty,'|',JSON.stringify(a.perTag));}
console.log('--- measured-but-empty totals across all kinds ---');
let te=0; for(const k of ks) te+=acc[k].measuredEmpty;
console.log('entries with basis!=5 and empty claim:',te);
