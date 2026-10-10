import { computed, ref, watch } from 'vue'
export function usePagination<T>(source:()=>T[], size=10){
 const page=ref(1),pageSize=ref(size)
 const total=computed(()=>source().length)
 const pages=computed(()=>Math.max(1,Math.ceil(total.value/pageSize.value)))
 const rows=computed(()=>source().slice((page.value-1)*pageSize.value,page.value*pageSize.value))
 watch([total,pageSize],()=>{page.value=Math.min(page.value,pages.value)})
 function reset(){page.value=1}
 return {page,pageSize,total,pages,rows,reset}
}
