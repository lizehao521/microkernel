const fs=require('fs');
const Bl=fs.readFileSync('C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl','utf8').split('\n');
const Al=fs.readFileSync('C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl','utf8').split('\n');
function show(tag,lines,ln){const o=JSON.parse(lines[ln-1]);const p=Buffer.from(o.payload_b64,'base64').toString('utf8');
  console.log(tag+' line'+ln+' seq='+o.seq+' step='+o.step+' kind='+o.kind+' basis='+o.basis+' claim='+o.claim.slice(0,80)+' payload='+p.slice(0,120));}
show('B',Bl,240); // fail_kind filled once
show('B',Bl,241); // fail_detail filled once
show('A',Al,413); // dropped filled once
