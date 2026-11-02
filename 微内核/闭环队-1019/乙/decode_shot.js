const fs=require('fs');
const lines=fs.readFileSync(process.argv[2],'utf8').split('\n').filter(l=>l.trim());
const want=process.argv[3]||'1';
for(const l of lines){
  let o; try{o=JSON.parse(l);}catch(e){continue;}
  if(o.seq===undefined) continue;
  if(String(o.step)===want){
    let dec='';
    try{dec=Buffer.from(o.payload_b64||'','base64').toString('utf8');}catch(e){}
    console.log(o.kind+'\tbasis='+o.basis+'\tpayload='+dec);
  }
}
