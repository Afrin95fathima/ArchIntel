import {useEffect, useState, type ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api, post, setCsrfToken} from '../api';
import {SecurityConsole} from './SecurityConsole';
import './security.css';
import { ArchIntelBrand } from '../Brand';

export interface Identity {id:string; username:string; tenant_id:string; kind:string; permissions:string[]; platform_owner?:boolean; csrf_token?:string}

export function AccessShell({children}:{children:ReactNode}) {
  const cache=useQueryClient();
  const [identity,setIdentity]=useState<Identity|null>(null);
  const [loading,setLoading]=useState(true);const [setup,setSetup]=useState(false);
  const [username,setUsername]=useState('');const [password,setPassword]=useState('');const [key,setKey]=useState('');
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [security,setSecurity]=useState(false);
  async function refresh(){
    try {const state=await api<{setup_required:boolean}>('/security/status');setSetup(state.setup_required);
      if(!state.setup_required){const me=await api<Identity>('/security/me');setCsrfToken(me.csrf_token||'');setIdentity(me);}
    } catch(e){setIdentity(null);if(!(e instanceof Error)||!e.message.includes('Sign in'))setError(String(e));}
    finally{setLoading(false);}
  }
  useEffect(()=>{void refresh();const expired=()=>{setIdentity(null);setCsrfToken('');cache.clear();setError('Your session ended. Sign in again.');};
    window.addEventListener('archintel-session-expired',expired);return()=>window.removeEventListener('archintel-session-expired',expired);},[]);
  async function submit(event:React.FormEvent){event.preventDefault();setBusy(true);setError('');
    try{await post('/security/'+(setup?'bootstrap':'login'),{username,password,...(setup?{bootstrap_key:key}:{})});
      setPassword('');setKey('');cache.clear();await refresh();}
    catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  async function logout(){try{await post('/security/logout');setIdentity(null);setCsrfToken('');setSecurity(false);cache.clear();localStorage.removeItem('archintel-analysis');}
    catch(e){setError(String(e));}}
  if(loading)return <main className="access-page"><p>Checking secure workspace…</p></main>;
  if(!identity)return <main className="access-page"><section className="access-card"><ArchIntelBrand/><p className="access-eyebrow">ARCHINTEL · CUSTOMER WORKSPACE</p>
    <h1>{setup?'Set up your administrator':'Sign in to ArchIntel'}</h1><p>{setup?'Your existing applications and analysis results stay in the local workspace. Create its owner account to continue.':'Use your workspace account to access analysis and runtime evidence.'}</p>
    {error&&<p role="alert" className="access-error">{error}</p>}
    <form onSubmit={submit}>
      {setup&&<><label>Setup key<input required type="password" value={key} onChange={e=>setKey(e.target.value)} autoComplete="off"/></label><p className="muted">On the server, read <code>.data/security-bootstrap.key</code>. The key works once and is sent to your ArchIntel server during setup.</p></>}
      <label>Username<input required value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username"/></label>
      <label>Password<input required type="password" minLength={setup?12:1} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete={setup?'new-password':'current-password'}/></label>
      {setup&&<p>Use at least 12 characters. Keep the password in your password manager.</p>}
      <button className="button" disabled={busy}>{busy?'Please wait…':setup?'Create administrator':'Sign in'}</button>
    </form></section></main>;
  return <><div className="access-bar"><span><strong>{identity.username}</strong> · Workspace {identity.tenant_id==='local'?'Local':identity.tenant_id.slice(0,8)}</span><div>
    <button onClick={()=>setSecurity(!security)}>{security?'Back to analysis':'Security & access'}</button><button onClick={()=>void logout()}>Sign out</button></div></div>
    {error&&<p role="alert">{error}</p>}{security?<SecurityConsole identity={identity}/>:children}</>;
}
