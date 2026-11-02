const fs=require('fs');
const inp=['call','parts','part_totals','content_bytes','tokens','call_bytes_ceiling','transport_slack_pct','content_ceiling','effective_ceiling','clamp_rounds','leftover_pct','fixed_overhead','shares','notice_sent','notice_trimmed','notice_why','notice_text','folded','clipped','dropped'];
const outp=['call','streaming','finish','finish_said','endpoint_model','endpoint_model_said','wire_format','wire_format_said','model_says_bytes','model_says_kept','model_says_clipped','model_says_sha256','usage_in','usage_out','wire_bytes_out','wire_bytes_in','chunks','first_byte_ms','max_gap_ms','tool_calls','malformed_actions','malformed_streak','fail_kind','fail_detail','fail_status','retry_after_ms','downgrade','sent','cost_countable'];
let id=200;const list=[];
for(const k of inp){list.push(['input',k]);}
for(const k of outp){list.push(['output',k]);}
for(const [side,key] of list){
  id++;
  const req={jsonrpc:"2.0",id:id,method:"tools/call",params:{name:"kernel.declare_reader",arguments:{reader:"调用方甲(闭环队-1019)",key:key,side:side}}};
  const fn='decl/d_'+side+'_'+key+'.json';
  fs.writeFileSync(fn,JSON.stringify(req));
  console.log(fn);
}
