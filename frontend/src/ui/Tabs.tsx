import type { KeyboardEvent, ReactNode } from 'react';

export type TabItem<T extends string>={value:T;label:string;icon?:ReactNode};

export function Tabs<T extends string>({items,value,onChange,label}:{items:TabItem<T>[];value:T;onChange:(value:T)=>void;label:string}){
  function handleKeyDown(event:KeyboardEvent<HTMLButtonElement>){
    if(event.key!=='ArrowRight'&&event.key!=='ArrowLeft'&&event.key!=='Home'&&event.key!=='End')return;
    event.preventDefault();
    const current=items.findIndex(item=>item.value===value);
    const next=event.key==='Home'?0:event.key==='End'?items.length-1:(current+(event.key==='ArrowRight'?1:-1)+items.length)%items.length;
    onChange(items[next].value);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }
  return <div className="hub-tabs" role="tablist" aria-label={label}>{items.map(item=><button key={item.value} role="tab" aria-selected={value===item.value} tabIndex={value===item.value?0:-1} className={value===item.value?'active':''} onClick={()=>onChange(item.value)} onKeyDown={handleKeyDown}>{item.icon}{item.label}</button>)}</div>;
}
