const fs=require('fs');
const lines=fs.readFileSync('C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl','utf8').split('\n');
const want={6:'tokens',132:'usage_in',36:'wire_bytes_out',124:'endpoint_model',122:'finish',185:'chunks',13:'fixed_overhead',49:'sent',18:'notice_text'};
for(const ln of [6,13,18,36,49,122,124,132,185,413,240]){
  const o=JSON.parse(lines[ln-1]);
  const p=Buffer.from(o.payload_b64,'base64').toString('utf8');
  console.log('line'+ln+' '+o.kind+' basis='+o.basis+' claim='+o.claim.slice(0,60)+' payload='+p.slice(0,220));
}
