const fs=require('fs');
const LEDGERS=[
 ['A','C:/Users/Admin/Desktop/微内核/构建-1017/客服靶场/导出/账本-全量-1018.jsonl'],
 ['B','C:/Users/Admin/Desktop/店面游戏/账本-8799-第二次快照-included.jsonl']
];
const CELLS=[]; // [side,key]
for(const k of ['call','parts','part_totals','content_bytes','tokens','call_bytes_ceiling','transport_slack_pct','content_ceiling','effective_ceiling','clamp_rounds','leftover_pct','fixed_overhead','shares','notice_sent','notice_trimmed','notice_why','notice_text','folded','clipped','dropped']) CELLS.push(['input',k]);
for(const k of ['call','streaming','finish','finish_said','endpoint_model','endpoint_model_said','wire_format','wire_format_said','model_says_bytes','model_says_kept','model_says_clipped','model_says_sha256','usage_in','usage_out','wire_bytes_out','wire_bytes_in','chunks','first_byte_ms','max_gap_ms','tool_calls','malformed_actions','malformed_streak','fail_kind','fail_detail','fail_status','retry_after_ms','downgrade','sent','cost_countable']) CELLS.push(['output',k]);

const stats={}; // cellKey -> per ledger stats
for(const [side,key] of CELLS) stats[side+':'+key]={A:{total:0,absent:0,emptyClaim:0,emptyPayload:0,emptyArr:0,filled:0,filledLines:[],emptyArrLines:[],absentLines:[],emptyLines:[],basisSet:{},claims:{}},B:{total:0,absent:0,emptyClaim:0,emptyPayload:0,emptyArr:0,filled:0,filledLines:[],emptyArrLines:[],absentLines:[],emptyLines:[],basisSet:{},claims:{}}};

const calls={A:new Set(),B:new Set()};
const sessions={A:new Set(),B:new Set()};

for(const [tag,path] of LEDGERS){
  const lines=fs.readFileSync(path,'utf8').split('\n');
  let lineNo=0;
  for(const l of lines){
    lineNo++;
    if(!l.startsWith('{'))continue;
    let o; try{o=JSON.parse(l);}catch(e){console.log('PARSE_FAIL '+tag+' line '+lineNo);continue;}
    calls[tag].add(o.session+'|'+o.step);
    sessions[tag].add(o.session);
    const m=o.kind.match(/^model_(input|output):(.+)$/);
    if(!m){console.log('ODD_KIND '+tag+' line '+lineNo+' kind='+o.kind);continue;}
    const ck=m[1]+':'+m[2];
    if(!stats[ck]){console.log('UNKNOWN_CELL '+tag+' line '+lineNo+' kind='+o.kind);continue;}
    const s=stats[ck][tag];
    s.total++;
    s.basisSet[o.basis]=(s.basisSet[o.basis]||0)+1;
    s.claims[o.claim]=(s.claims[o.claim]||0)+1;
    let payload=null,perr=false;
    try{payload=o.payload_b64===''?'':Buffer.from(o.payload_b64,'base64').toString('utf8');}catch(e){perr=true;}
    let pj; try{pj=JSON.parse(payload);}catch(e){pj=undefined;}
    const isAbsent=(pj&&typeof pj==='object'&&pj.Absent===true);
    const isEmptyClaim=(o.claim==='（这一格是空的）');
    const isEmptyStr=(payload==='');
    const isEmptyArr=(payload==='[]');
    const isEmptyObjNull=(payload==='null');
    if(isAbsent){s.absent++;if(s.absentLines.length<3)s.absentLines.push(lineNo);}
    else if(isEmptyClaim||isEmptyStr||isEmptyObjNull){s.emptyClaim++;s.emptyPayload++;if(s.emptyLines.length<3)s.emptyLines.push(lineNo);}
    else if(isEmptyArr){s.emptyArr++;if(s.emptyArrLines.length<3)s.emptyArrLines.push(lineNo);}
    else{s.filled++;if(s.filledLines.length<5)s.filledLines.push(lineNo);}
  }
}
console.log('CALLS A='+calls.size+' B='+calls.size+'  SESSIONS A='+sessions.size+' B='+sessions.size);
console.log('');
const out=[];
for(const [side,key] of CELLS){
  const ck=side+':'+key;
  const a=stats[ck].A,b=stats[ck].B;
  const filledBoth=a.filled+b.filled;
  out.push({cell:ck,
    A:{total:a.total,absent:a.absent,empty:a.emptyClaim,emptyArr:a.emptyArr,filled:a.filled,fLines:a.filledLines,eLines:a.emptyLines,eaLines:a.emptyArrLines,aLines:a.absentLines,basis:a.basisSet},
    B:{total:b.total,absent:b.absent,empty:b.emptyClaim,emptyArr:b.emptyArr,filled:b.filled,fLines:b.filledLines,eLines:b.emptyLines,eaLines:b.emptyArrLines,aLines:b.absentLines,basis:b.basisSet},
    filledBoth});
}
out.sort((x,y)=>x.filledBoth-y.filledBoth);
for(const r of out){
  console.log(JSON.stringify(r));
}
// claim census for never-filled candidates
console.log('');
console.log('=== CLAIM CENSUS (never-or-rarely filled cells) ===');
for(const r of out){
  if(r.filledBoth<=r.A.total*0+r.B.total*0+ (r.A.total+r.B.total) ){
    if(r.filledBoth===0){
      const ck=r.cell;
      console.log(ck+' A.claims='+JSON.stringify(stats[ck].A.claims));
      console.log(ck+' B.claims='+JSON.stringify(stats[ck].B.claims));
    }
  }
}
