<script setup lang="ts">
import { computed } from 'vue'
const props=defineProps<{content:string}>()
// 使用 Vue 文本节点渲染，正文中的 HTML 不执行。
const blocks=computed(()=>{
 const result:{kind:string;text:string;level?:number}[]=[];let code=false,buffer:string[]=[]
 const flush=()=>{if(buffer.length){result.push({kind:code?'code':'paragraph',text:buffer.join('\n')});buffer=[]}}
 for(const line of props.content.split('\n')){
  if(line.startsWith('```')){flush();code=!code;continue}
  if(code){buffer.push(line);continue}
  const heading=line.match(/^(#{1,4})\s+(.+)$/)
  if(heading){flush();result.push({kind:'heading',level:heading[1].length,text:heading[2]})}
  else if(/^\s*[-*+]\s+/.test(line)){flush();result.push({kind:'bullet',text:line.replace(/^\s*[-*+]\s+/,'')})}
  else if(/^>\s?/.test(line)){flush();result.push({kind:'quote',text:line.replace(/^>\s?/,'')})}
  else if(/^---+$/.test(line.trim())){flush();result.push({kind:'rule',text:''})}
  else if(!line.trim())flush()
  else buffer.push(line)
 }
 flush();return result
})
function inline(text:string){return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map(s=>({text:s.startsWith('**')?s.slice(2,-2):s.startsWith('`')?s.slice(1,-1):s,kind:s.startsWith('**')?'strong':s.startsWith('`')?'code':'span'}))}
</script>
<template><div class="markdown-body"><template v-for="(block,index) in blocks" :key="index"><pre v-if="block.kind==='code'"><code>{{block.text}}</code></pre><hr v-else-if="block.kind==='rule'"><component v-else :is="block.kind==='heading'?'h'+block.level:block.kind==='quote'?'blockquote':'p'" :class="{'markdown-bullet':block.kind==='bullet'}"><component v-for="(part,i) in inline(block.text)" :key="i" :is="part.kind">{{part.text}}</component></component></template></div></template>
