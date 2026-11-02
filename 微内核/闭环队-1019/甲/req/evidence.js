const fs=require('fs');
const A='C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl'.split('\n');
const Al=fs.readFileSync('C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl','utf8').split('\n');
const Bl=fs.readFileSync('C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl','utf8').split('\n');
function show(tag,lines,ln){const o=JSON.parse(lines[ln-1]);const p=Buffer.from(o.payload_b64,'base64').toString('utf8');
  console.log(tag+' line'+ln+' seq='+o.seq+' session='+o.session+' step='+o.step+' kind='+o.kind+' basis='+o.basis);
  console.log('   claim='+o.claim);
  console.log('   payload='+p);}
for(const ln of [19,20,46,47]){show('A',Al,ln);}
console.log('');
for(const ln of [19,20,46,47]){show('B',Bl,ln);}
