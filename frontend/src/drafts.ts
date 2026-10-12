// 草稿仅存于当前浏览器标签的 sessionStorage，24 小时后失效。
const ttl=24*60*60*1000
export function readDraft(key:string){try{const raw=sessionStorage.getItem(key);if(!raw)return null;const item=JSON.parse(raw);if(!item.savedAt||Date.now()-item.savedAt>ttl){sessionStorage.removeItem(key);return null}return item.value}catch{return null}}
export function storeDraft(key:string,value:unknown){try{sessionStorage.setItem(key,JSON.stringify({savedAt:Date.now(),value}));return true}catch{return false}}
export function removeDraft(key:string){try{sessionStorage.removeItem(key)}catch{}}
