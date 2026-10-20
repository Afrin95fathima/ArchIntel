import {useState} from 'react';
import {api,post} from '../api';
import {ErrorBox} from '../components';

export type Changeset={id:string;state:string;files:string[];risk:string;fingerprint:string};

/** One proposed patch. Its preview, loading state and error belong to this item only. */
export function ChangesetCard({changeset:c,base,busy,canNote,act,revision}:{changeset:Changeset;base:string;busy:boolean;canNote:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;revision:()=>Record<string,unknown>}){
  const [diff,setDiff]=useState<string|null>(null);
  const [open,setOpen]=useState(false);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState<unknown>(null);
  async function inspect(){
    if(diff!==null){setOpen(value=>!value);return;}
    setLoading(true);setError(null);
    try{const patch=await api<{diff:string}>(base+'/changesets/'+c.id);setDiff(patch.diff||'');setOpen(true);}
    catch(e){setError(e);}finally{setLoading(false);}
  }
  const review=(action:string)=>()=>void act(async()=>{await post(base+'/changesets/'+c.id+'/review',{...revision(),action,fingerprint:c.fingerprint});});
  return <article aria-label={'Changeset '+c.files.join(', ')}>
    <h3>{c.state}: {c.files.join(', ')}</h3><p>Risk {c.risk} | Patch hash {c.fingerprint}</p>
    <button disabled={loading} aria-expanded={open} onClick={()=>void inspect()}>{loading?'Loading patch…':open?'Hide patch':'Inspect patch'}</button>
    {c.state==='PROPOSED'&&<><button disabled={busy||!canNote} onClick={review('APPROVE_STAGING')}>Approve isolated staging</button><button disabled={busy||!canNote} onClick={review('REJECT')}>Reject patch</button></>}
    {c.state==='APPROVED_FOR_STAGING'&&<button disabled={busy||!canNote} onClick={()=>void act(async()=>{await post(base+'/changesets/'+c.id+'/stage',revision());setDiff(null);setOpen(false);})}>Stage reviewed patch</button>}
    {error?<ErrorBox error={error}/>:null}
    {open&&diff!==null&&<section aria-label={'Patch preview: '+c.files.join(', ')}><h4>Exact patch preview</h4><pre>{diff||'No textual differences.'}</pre></section>}
  </article>;
}
