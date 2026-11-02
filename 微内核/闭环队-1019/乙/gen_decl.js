const fs=require('fs');
const inp=['call','parts','part_totals','content_bytes','tokens','call_bytes_ceiling','transport_slack_pct','content_ceiling','effective_ceiling','clamp_rounds','leftover_pct','fixed_overhead','shares','notice_sent','notice_trimmed','notice_why','notice_text','folded','clipped','dropped'];
const outp=['call','streaming','finish','finish_said','endpoint_model','endpoint_model_said','wire_format','wire_format_said','model_says_bytes','model_says_kept','model_says_clipped','model_says_sha256','usage_in','usage_out','wire_bytes_out','wire_bytes_in','chunks','first_byte_ms','max_gap_ms','tool_calls','malformed_actions','malformed_streak','fail_kind','fail_detail','fail_status','retry_after_ms','downgrade','sent','cost_countable'];
let id=300; const rows=[];
for(const k of inp) rows.push({side:'input',key:k});
for(const k of outp) rows.push({side:'output',key:k});
for(const r of rows){
  id++;
  const body={jsonrpc:'2.0',id,method:'tools/call',params:{name:'kernel.declare_reader',arguments:{reader:'cell-auditor-yi',key:r.key,side:r.side}}};
  fs.writeFileSync(`decl_${r.side}_${r.key}.json`,JSON.stringify(body));
}
console.log('generated',rows.length,'declare bodies');
