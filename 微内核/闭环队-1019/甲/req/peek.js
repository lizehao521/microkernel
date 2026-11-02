const fs=require('fs');
const lines=fs.readFileSync(process.argv[2],'utf8').split('\n').filter(l=>l.startsWith('{'));
const seen=new Set();
for(const l of lines){
  const o=JSON.parse(l);
  if(seen.has(o.kind))continue;
  seen.add(o.kind);
  let p='';
  try{p=Buffer.from(o.payload_b64,'base64').toString('utf8');}catch(e){p='ERR';}
  console.log(o.kind+' | claim='+JSON.stringify(o.claim)+' | basis='+o.basis+' | payload='+p.slice(0,300));
}
