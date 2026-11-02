const fs=require('fs');
const L=[['A','C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl'],['B','C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl']];
const want=['model_output:sent','model_output:fail_kind','model_output:fail_detail','model_input:dropped','model_input:notice_text','model_output:cost_countable','model_output:downgrade','model_output:tool_calls','model_output:malformed_actions'];
for(const [tag,path] of L){
  const calls=new Set(),sess=new Set();
  const cens={};const ex={};
  let lineNo=0;
  for(const l of fs.readFileSync(path,'utf8').split('\n')){
    lineNo++;
    if(!l.startsWith('{'))continue;
    const o=JSON.parse(l);
    calls.add(o.session+'|'+o.step);sess.add(o.session);
    if(!want.includes(o.kind))continue;
    cens[o.kind]=cens[o.kind]||{};
    const p=Buffer.from(o.payload_b64,'base64').toString('utf8');
    const k=o.claim+' ||payload='+p.slice(0,120);
    cens[o.kind][k]=(cens[o.kind][k]||0)+1;
    ex[o.kind]=ex[o.kind]||[];
    if(ex[o.kind].length<8)ex[o.kind].push(lineNo);
  }
  console.log('### LEDGER '+tag+'  distinctCalls='+calls.size+' distinctSessions='+sess.size);
  for(const k of want){
    console.log('-- '+k+' lines(first8)='+JSON.stringify(ex[k]));
    for(const c in (cens[k]||{}))console.log('   x'+cens[k][c]+'  '+c);
  }
}
