const fs=require('fs');
const F=[['L1018','C:/Users/Admin/Desktop/\u5fae\u5185\u6838/\u6784\u5efa-1017/\u5ba2\u670d\u9776\u573a/\u5bfc\u51fa/\u8d26\u672c-\u5168\u91cf-1018.jsonl'],['L8799','C:/Users/Admin/Desktop/\u5e97\u9762\u6e38\u620f/\u8d26\u672c-8799-\u7b2c\u4e8c\u6b21\u5feb\u7167-included.jsonl']];
const want=['model_input:folded','model_input:clipped','model_input:dropped','model_output:fail_kind','model_output:fail_detail'];
const acc={};
for(const [tag,p] of F){
  const raw=fs.readFileSync(p,'utf8').split('\n');
  raw.forEach((ln,i)=>{ const s=ln.trim(); if(!s||s[0]!=='{')return;
    let o; try{o=JSON.parse(s);}catch(e){return;}
    if(want.indexOf(o.kind)<0)return;
    const key=o.kind;
    acc[key]=acc[key]||{};
    let pay=''; try{pay=Buffer.from(o.payload_b64||'','base64').toString('utf8');}catch(e){pay='<b64err>';}
    const sig='basis='+o.basis+' payload='+pay;
    acc[key][tag]=acc[key][tag]||{};
    acc[key][tag][sig]=(acc[key][tag][sig]||0)+1;
    if(pay!=='[]'&&pay!=='""'&&pay!==''){ (acc[key].hits=acc[key].hits||[]).push(tag+' line'+(i+1)+' seq'+o.seq+' '+pay.slice(0,80)); }
  });
}
for(const k of want){ console.log('==',k); for(const t of ['L1018','L8799']) console.log('  ',t,JSON.stringify(acc[k][t])); console.log('   NON-EMPTY hits:',(acc[k].hits||[]).length); (acc[k].hits||[]).slice(0,4).forEach(h=>console.log('     ',h)); }
