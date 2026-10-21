import {useState} from 'react';

export type BoardDomain={id:string;name:string};
export type BoardClass={id:string;domain_id:string};
const short=(id:string)=>id.slice(id.lastIndexOf('.',id.lastIndexOf('.')-1)+1);
const LIMIT=300;

/** Domains as cards: rename them and move classes by dragging a class onto another card, or with the menu on each class. */
export function DomainBoard({domains,classes,names,membership,kinds={},onRename,onMove}:{domains:BoardDomain[];classes:BoardClass[];names:Record<string,string>;membership:Record<string,string>;kinds?:Record<string,{kind:string}>;onRename:(id:string,name:string)=>void;onMove:(cls:string,domain:string)=>void}){
  const [filter,setFilter]=useState('');const [over,setOver]=useState('');
  const current=(c:BoardClass)=>membership[c.id]??c.domain_id;
  const label=(d:BoardDomain)=>names[d.id]??d.name;
  const shown=classes.filter(c=>!filter||c.id.toLowerCase().includes(filter.toLowerCase())).slice(0,LIMIT);
  return <div className="domain-board">
    <label>Find a class<input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Part of a class name"/></label>
    <p className="fine-print">Drag a class onto another domain, or use the menu on the class. Every class must stay in exactly one domain. {classes.length>LIMIT&&`The board lists the first ${LIMIT} classes that match the search.`}</p>
    <div className="board-columns">{domains.map(d=>{const mine=shown.filter(c=>current(c)===d.id);const total=classes.filter(c=>current(c)===d.id).length;const original=classes.filter(c=>c.domain_id===d.id).length;
      return <section key={d.id} className={'board-card'+(over===d.id?' over':'')} aria-label={'Domain '+label(d)}
        onDragOver={e=>{e.preventDefault();setOver(d.id);}} onDragLeave={()=>setOver('')} onDrop={e=>{e.preventDefault();setOver('');const cls=e.dataTransfer.getData('text/plain');if(cls)onMove(cls,d.id);}}>
        <header><input aria-label={'Name for '+d.id} value={label(d)} onChange={e=>onRename(d.id,e.target.value)}/><span>{total} {total===1?'class':'classes'}{total!==original&&` (was ${original})`}</span></header>
        {kinds[d.id]?.kind==='TECHNICAL'&&<small>Technical domain: keep as shared configuration or a library.</small>}
        {total===0&&<small role="alert">A domain cannot be empty.</small>}
        <ul>{mine.map(c=><li key={c.id} draggable onDragStart={e=>{e.dataTransfer.setData('text/plain',c.id);e.dataTransfer.effectAllowed='move';}} className={current(c)!==c.domain_id?'moved':''}>
          <span title={c.id}>{short(c.id)}</span>
          <select aria-label={'Domain for '+c.id} value={current(c)} onChange={e=>onMove(c.id,e.target.value)}>{domains.map(x=><option key={x.id} value={x.id}>{label(x)}</option>)}</select></li>)}</ul>
      </section>;})}</div>
  </div>;
}
