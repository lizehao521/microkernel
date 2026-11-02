const fs=require('fs');
const lines=fs.readFileSync('C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl','utf8').split('\n').filter(l=>l.startsWith('{'));
// first call = seq 1..49 (session step1). Dump full payload for each kind.
for(const l of lines.slice(0,49)){
  const o=JSON.parse(l);
  const p=Buffer.from(o.payload_b64,'base64').toString('utf8');
  console.log(o.kind+'  [basis='+o.basis+']  '+p);
}
