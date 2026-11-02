const fs=require('fs');
const L=[['A','C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl'],['B','C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl']];
const inp=['call','parts','part_totals','content_bytes','tokens','call_bytes_ceiling','transport_slack_pct','content_ceiling','effective_ceiling','clamp_rounds','leftover_pct','fixed_overhead','shares','notice_sent','notice_trimmed','notice_why','notice_text','folded','clipped','dropped'];
const outp=['call','streaming','finish','finish_said','endpoint_model','endpoint_model_said','wire_format','wire_format_said','model_says_bytes','model_says_kept','model_says_clipped','model_says_sha256','usage_in','usage_out','wire_bytes_out','wire_bytes_in','chunks','first_byte_ms','max_gap_ms','tool_calls','malformed_actions','malformed_streak','fail_kind','fail_detail','fail_status','retry_after_ms','downgrade','sent','cost_countable'];
const CELLS=[];for(const k of inp)CELLS.push(['input',k]);for(const k of outp)CELLS.push(['output',k]);
// state[key][tag] = {absent:[lines],empty:[lines],filled:[lines],total}
const st={};
for(const [side,key] of CELLS) st[side+':'+key]={A:{absent:[],empty:[],filled:[]},B:{absent:[],empty:[],filled:[]}};
const callCount={A:new Set(),B:new Set()};
for(const [tag,path] of L){
  let ln=0;
  for(const l of fs.readFileSync(path,'utf8').split('\n')){
    ln++;
    if(!l.startsWith('{'))continue;
    const o=JSON.parse(l);
    callCount[tag].add(o.session+'|'+o.step);
    const m=o.kind.match(/^model_(input|output):(.+)$/);
    const ck=m[1]+':'+m[2];
    const p=o.payload_b64===''?'':Buffer.from(o.payload_b64,'base64').toString('utf8');
    let pj;try{pj=JSON.parse(p);}catch(e){pj=undefined;}
    const s=st[ck][tag];
    if(pj&&typeof pj==='object'&&pj.Absent===true) s.absent.push(ln);
    else if(o.claim==='（这一格是空的）'||p===''||p==='null'||p==='[]') s.empty.push(ln);
    else s.filled.push(ln);
  }
}
console.log('CALLS: A='+callCount.A.size+' B='+callCount.B.size+' total='+(callCount.A.size+callCount.B.size));
console.log('');
const never=[];
for(const [side,key] of CELLS){
  const ck=side+':'+key;
  const a=st[ck].A,b=st[ck].B;
  const filledTot=a.filled.length+b.filled.length;
  const absentTot=a.absent.length+b.absent.length;
  const emptyTot=a.empty.length+b.empty.length;
  const tot=absentTot+emptyTot+filledTot;
  const verdict=filledTot===0?'NEVER-FILLED':'filled>='+filledTot;
  if(filledTot===0)never.push(ck);
  console.log(ck.padEnd(30)+' total='+String(tot).padStart(3)+' absent='+String(absentTot).padStart(3)+' empty='+String(emptyTot).padStart(3)+' filled='+String(filledTot).padStart(3)+'  '+verdict);
  if(filledTot===0){
    // subtype
    const isAbsent=absentTot>0&&emptyTot===0;
    const isEmpty=emptyTot>0&&absentTot===0;
    const sub=isAbsent?'ABSENT(缺席,basis=5)':isEmpty?'EMPTY(为空,空数组/空串)':'MIXED';
    console.log('     -> subtype='+sub);
    console.log('     -> A.absentLines(first5)='+JSON.stringify(a.absent.slice(0,5))+' A.emptyLines(first5)='+JSON.stringify(a.empty.slice(0,5)));
    console.log('     -> B.absentLines(first5)='+JSON.stringify(b.absent.slice(0,5))+' B.emptyLines(first5)='+JSON.stringify(b.empty.slice(0,5)));
    console.log('     -> A.count(absent+empty)='+(a.absent.length+a.empty.length)+'/60  B.count='+(b.absent.length+b.empty.length)+'/10');
  }
}
console.log('');
console.log('NEVER-FILLED CELLS ('+never.length+'): '+never.join(', '));
