let csrfToken = '';
export function setCsrfToken(value: string) { csrfToken = value; }

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    ...options, headers: {'X-ArchIntel-Request':'1', ...(csrfToken ? {'X-CSRF-Token':csrfToken} : {}),
      ...(options?.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options?.headers}
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/security/')) window.dispatchEvent(new Event('archintel-session-expired'));
    let message = 'Request failed. Check the API connection.';
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* retain transport error */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export async function apiBlob(path:string):Promise<Blob>{
  const response=await fetch('/api/v1'+path,{headers:{'X-ArchIntel-Request':'1'}});
  if(!response.ok)throw new Error('Could not load analysis evidence for comparison.');
  return response.blob();
}
/** Streaming POST: resolves with the raw response so callers can read newline-delimited JSON. */
export async function apiStream(path:string,body:unknown):Promise<Response>{
  const response=await fetch('/api/v1'+path,{method:'POST',headers:{'X-ArchIntel-Request':'1','Content-Type':'application/json',...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:JSON.stringify(body)});
  if(!response.ok){let message='Request failed. Check the API connection.';try{const detail=(await response.json()).detail;message=typeof detail==='string'?detail:JSON.stringify(detail);}catch{/* keep generic */}throw new Error(message);}
  return response;
}
export async function* ndjson<T>(response:Response):AsyncGenerator<T>{
  const reader=response.body?.getReader();
  if(!reader){for(const line of (await response.text()).split('\n'))if(line.trim())yield JSON.parse(line) as T;return;}
  const decoder=new TextDecoder();let buffer='';
  for(;;){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let index;while((index=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,index).trim();buffer=buffer.slice(index+1);if(line)yield JSON.parse(line) as T;}}
  if(buffer.trim())yield JSON.parse(buffer) as T;
}
export const post = <T,>(path: string, body?: unknown) => api<T>(path, {method:'POST', ...(body ? {body: JSON.stringify(body)} : {})});
