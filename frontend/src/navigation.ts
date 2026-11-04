export const sections=['projects','jobs','traces','document','wiki','wiki-sources','memory','governance','skills','models','credentials']
export function readRoute(hash=window.location.hash){const [path,query='']=hash.replace(/^#\/?/,'').split('?');return {section:sections.includes(path)?path:'projects',params:new URLSearchParams(query)}}
export function routeHash(section:string,values:Record<string,string|number>={}){const params=new URLSearchParams();for(const [key,value] of Object.entries(values))if(String(value))params.set(key,String(value));return '#/'+section+(params.size?'?'+params:'')}
const visitedRoutes=new Map<string,Record<string,string>>()
export function navigateTo(section:string,values:Record<string,string|number>={}){const current=readRoute();visitedRoutes.set(current.section+':'+(current.params.get('workspace')||''),Object.fromEntries(current.params));const cached=visitedRoutes.get(section+':'+(values.workspace||''))||{};window.location.hash=routeHash(section,{...cached,...values})}
export function rememberRoute(values:Record<string,string|number>){const route=readRoute();for(const [key,value] of Object.entries(values)){if(String(value))route.params.set(key,String(value));else route.params.delete(key)}window.history.replaceState(null,'',routeHash(route.section,Object.fromEntries(route.params)));window.dispatchEvent(new Event('mc:route-state'))}
export function routeNumber(key:string,fallback:number,allowed?:number[]){const n=Number(readRoute().params.get(key));return Number.isInteger(n)&&n>0&&(!allowed||allowed.includes(n))?n:fallback}
export const leaveGuards=new Set<()=>boolean|Promise<boolean>>()
export async function canLeave(){for(const guard of leaveGuards)if(!await guard())return false;return true}
