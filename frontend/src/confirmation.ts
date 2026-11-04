import {ref} from 'vue'
export const confirmation=ref<{message:string;accept:string}|null>(null)
let resolve:((value:boolean)=>void)|null=null
export function confirmAction(message:string,accept='确认'){if(resolve)return Promise.resolve(false);confirmation.value={message,accept};return new Promise<boolean>(done=>{resolve=done})}
export function answerConfirmation(value:boolean){const done=resolve;resolve=null;confirmation.value=null;done?.(value)}
