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
export const post = <T,>(path: string, body?: unknown) => api<T>(path, {method:'POST', ...(body ? {body: JSON.stringify(body)} : {})});
