const taskNames={collect:'采集资料',analyse:'分析资料',publish:'发布结果',reference:'整理参考资料',verify:'补充核验',wait:'等待前置交付'};
const taskName=value=>taskNames[value]||String(value??'未指定工作');
function eventJob(event){return event.data.task_id||event.data.action?.task_id||event.data.receipt?.task_id}
function sequenceItems(records){
 const plans=new Map(),items=[],states={};
 for(const event of records){
  const data=event.data,message=data.message||{},sender=String(event.agent),peer=String(event.peer),key=String(message.proposal??'');
  let title='',detail='',type='note';
  if(event.kind==='model_decision'){
   let decision={};try{decision=JSON.parse(data.content)}catch{}
   if(decision.job){plans.set(sender,decision.job);title='决定：'+taskName(decision.job);detail='模型根据当前真实完成状态选择本人下一步工作';const context=data.context||{},completed=context.observation?.completed||[];const dependencies=context.jobs?.[decision.job]?.requires||[];if(dependencies.length)detail+='；需要交付：'+dependencies.map(taskName).join('、');if(decision.job==='wait'){const missing=Object.values(context.jobs||{}).filter(job=>String(job.owner)===sender).flatMap(job=>job.requires||[]).filter(job=>!completed.includes(job));detail=missing.length?'仍缺少上游交付：'+[...new Set(missing)].map(taskName).join('、'):'当前没有可启动的新工作（可能执行中或本人工作已完成）'}states[sender]=title+'；'+detail}
   else{title='评估是否需要重新协调';detail='模型请求发起本轮协作'}
  }else if(event.kind==='message_send'){
   type='message';const payload=message.payload||{};
   const jobs=[];
   function find(value){if(!value||typeof value!=='object')return;if(typeof value.job==='string')jobs.push(value.job);for(const child of Object.values(value))if(child&&typeof child==='object')find(child)}find(payload);
   const own=jobs.length?jobs.map(taskName).join('、'):'响应未携带具体工作名（查看原文）';
   const summaries={propose:['请求协商下一步分工','请评估你当前能做什么、需要等待哪些交付'],respond:['反馈本人安排：'+own,'此处是方案反馈，尚未实际执行'],respond_full:['反馈本人安排：'+own,'发送完整的公开响应'],respond_delta:['更新本人配合条件','仅传输相对上次响应发生变化的字段'],prepare:['准备共同确认','请检查方案及版本，确认本人承诺可执行'],ready:['确认准备就绪','本人已完成提交前检查'],commit:['共同提交已确认方案','相关成员安装各自确认的安排，之后才开始执行'],abort:['取消当前协商','当前方案未提交，不能视为任务完成'],revoke:['撤销失效安排','原承诺条件已变化，需要重新协调']};
   [title,detail]=summaries[message.kind]||['发送 '+message.kind,'实际协议消息'];
   if(message.kind==='commit')detail+='。此消息确认提交，不代表工作已经完成';
   detail+=' · 提案 '+(key||'未知');
   if(sender===peer)detail+=' · 本地协议处理（非跨成员通信）';
  }else if(event.kind==='tool'){
   title=({running:'开始执行：',completed:'完成交付：',blocked:'依赖未满足：',failed:'执行失败：'}[data.status]||'工具状态：')+taskName(eventJob(event));
   const requires=data.action?.requires||[];detail=requires.length?'依赖已完成的交付：'+requires.map(taskName).join('、'):'执行层实际回执，而非模型口头声明';states[sender]=title;
  }else if(event.kind==='dependency_change'){
   title='依赖发生变化';detail=Object.entries(data.jobs||{}).map(([job,value])=>taskName(job)+' ← '+(value[1]?.map(taskName).join('、')||'无前置依赖')).join('；');type='system';
  }else if(event.kind==='error'){title='发生异常';detail=data.error||data.traceback||'请查看诊断日志';type='system'}
  else if(event.kind==='run_start'){title='任务开始';detail='各成员评估本人的能力与交付依赖';type='system'}
  else if(event.kind==='run_end'){title=data.success?'全部任务完成':'任务未完成';detail=data.error||'以执行回执为准';type='system'}
  if(title)items.push({event,title,detail,type,sender,peer});
 }
 return {items,states};
}
function renderSequence(records){
 const {items,states}=sequenceItems(records),container=el('chat');container.replaceChildren();el('agents').replaceChildren();
 for(const agent of ['0','1','2']){const card=make('div');card.className='card';card.append(make('b','Agent '+agent),make('p',states[agent]||'等待 / 尚无工作记录'));el('agents').append(card)}
 const selected=items.slice(-500),width=1200,rowHeight=108,height=100+selected.length*rowHeight;
 const ns='http://www.w3.org/2000/svg';function svg(tag,attributes,text){const item=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attributes))item.setAttribute(key,value);if(text!==undefined)item.textContent=text;return item}
 const diagram=svg('svg',{viewBox:'0 0 '+width+' '+height,width:'100%',role:'img','aria-label':'三Agent实时交互时序图'});diagram.style.minWidth='1000px';
 const defs=svg('defs',{}),marker=svg('marker',{id:'arrowhead',markerWidth:10,markerHeight:8,refX:9,refY:4,orient:'auto-start-reverse'});marker.append(svg('path',{d:'M0,0 L10,4 L0,8 z',fill:'#72d6cb'}));defs.append(marker);diagram.append(defs);
 const positions=[200,600,1000];
 for(let index=0;index<3;index++){const x=positions[index];diagram.append(svg('rect',{x:x-85,y:8,width:170,height:44,rx:8,fill:'#28435d',stroke:'#82b3d4'}),svg('text',{x,y:36,'text-anchor':'middle',fill:'white','font-size':18},'Agent '+index),svg('line',{x1:x,y1:52,x2:x,y2:height,stroke:'#6d859e','stroke-dasharray':'7 6'}))}
 const running=new Map();for(const [index,item]of selected.entries()){if(item.event.kind!=='tool')continue;const job=eventJob(item.event),x=positions[Number(item.sender)];if(x===undefined)continue;if(item.event.data.status==='running')running.set(job,{index,x});if(item.event.data.status==='completed'&&running.has(job)){const start=running.get(job);diagram.append(svg('rect',{x:start.x-6,y:95+start.index*rowHeight,width:12,height:Math.max(20,(index-start.index)*rowHeight),fill:'#436e92',stroke:'#91c9ed'}));running.delete(job)}}for(const start of running.values())diagram.append(svg('rect',{x:start.x-6,y:95+start.index*rowHeight,width:12,height:Math.max(20,height-95-start.index*rowHeight),fill:'#436e92',stroke:'#91c9ed'}));
 let time=null;for(const [index,item]of selected.entries()){
  const y=95+index*rowHeight,{event,title,detail,type,sender,peer}=item;if(event.time!==null)time=event.time;
  diagram.append(svg('text',{x:8,y:y+8,fill:'#9bb1c9','font-size':11},'#'+event.sequence+' t='+show(time)));
  const group=svg('g',{tabindex:0,role:'button','aria-label':title});group.style.cursor='pointer';group.append(svg('title',{},detail+'（点击查看实际消息原文）'));
  const from=positions[Number(sender)],to=positions[Number(peer)];
  if(type==='message'&&from!==undefined&&to!==undefined){
   if(from===to)group.append(svg('path',{d:'M'+from+','+y+' h65 v26 h-65',fill:'none',stroke:'#72d6cb','stroke-width':2,'marker-end':'url(#arrowhead)'}));
   else group.append(svg('line',{x1:from,y1:y+24,x2:to,y2:y+24,stroke:'#72d6cb','stroke-width':2,'marker-end':'url(#arrowhead)'}));
   const center=(from+to)/2;group.append(svg('rect',{x:center-165,y:y-15,width:330,height:29,rx:5,fill:'#142334'}),svg('text',{x:center,y:y+5,'text-anchor':'middle',fill:'#dffbf4','font-size':14},title));
  }else{const x=type==='system'||from===undefined?600:from;group.append(svg('rect',{x:x-165,y:y-18,width:330,height:45,rx:7,fill:type==='system'?'#644c2c':'#274b64',stroke:'#88aac6'}),svg('text',{x,y:y+9,'text-anchor':'middle',fill:'white','font-size':14},title))}
  const description=svg('text',{x:125,y:y+58,fill:'#bdcee1','font-size':12});for(let offset=0;offset<detail.length;offset+=88)description.append(svg('tspan',{x:125,dy:offset?17:0},detail.slice(offset,offset+88)));group.append(description);
  const inspect=()=>{el('snapshot').textContent=JSON.stringify(event,null,2);el('snapshot').parentElement.open=true;el('snapshot').scrollIntoView({block:'nearest'})};group.onclick=inspect;group.onkeydown=key=>{if(key.key==='Enter')inspect()};diagram.append(group);
 }
 container.append(diagram);if(!items.length)container.append(make('p','等待真实消息。请选择任务并开始；旧汇总记录无法恢复完整交互。'));
}
