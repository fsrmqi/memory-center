import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
async function moduleAt(name){const source=fs.readFileSync(new URL('../src/'+name+'.ts',import.meta.url),'utf8');return import('data:text/javascript;base64,'+Buffer.from(ts.transpile(source,{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext})).toString('base64'))}
const navigation=await moduleAt('navigation'),drafts=await moduleAt('drafts')
globalThis.window={location:{hash:'#/wiki?workspace=ws_example&page=3&size=20&q=hello'},history:{replaceState(_a,_b,value){window.location.hash=value}},dispatchEvent(){}}
const values=new Map();globalThis.sessionStorage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}
test('路由深链保留项目与编码后的筛选，不接受未知页面',()=>{const hash=navigation.routeHash('wiki',{workspace:'ws_example',q:'中文 & a?',page:3});const route=navigation.readRoute(hash);assert.equal(route.section,'wiki');assert.equal(route.params.get('q'),'中文 & a?');assert.equal(navigation.readRoute('#/unknown').section,'projects');assert.equal(navigation.routeNumber('size',10,[10,20,50]),20)})
test('更新分页不丢项目，清除筛选会删除参数，非法页码回退',()=>{navigation.rememberRoute({page:2,q:''});assert.equal(navigation.readRoute().params.get('workspace'),'ws_example');assert.equal(navigation.readRoute().params.has('q'),false);window.location.hash='#/jobs?page=-3&size=999';assert.equal(navigation.routeNumber('page',1),1);assert.equal(navigation.routeNumber('size',10,[10,20,50]),10)})
test('离开保护可阻止导航，移除后恢复',async()=>{const guard=()=>false;navigation.leaveGuards.add(guard);assert.equal(await navigation.canLeave(),false);navigation.leaveGuards.delete(guard);assert.equal(await navigation.canLeave(),true)})
test('不同项目草稿隔离，显式丢弃，过期及损坏草稿不恢复',()=>{drafts.storeDraft('a',{content:'甲'});drafts.storeDraft('b',{content:'乙'});assert.equal(drafts.readDraft('a').content,'甲');drafts.removeDraft('a');assert.equal(drafts.readDraft('a'),null);assert.equal(drafts.readDraft('b').content,'乙');values.set('expired',JSON.stringify({savedAt:Date.now()-86400001,value:{content:'旧'}}));assert.equal(drafts.readDraft('expired'),null);values.set('broken','{');assert.equal(drafts.readDraft('broken'),null)})
test('浏览器禁止存储时返回失败，不伪装成草稿已保存',()=>{const previous=sessionStorage.setItem;sessionStorage.setItem=()=>{throw new Error('quota')};assert.equal(drafts.storeDraft('a',{}),false);sessionStorage.setItem=previous})

test('栏目往返恢复筛选与分页，不串用其他项目状态',()=>{window.location.hash='#/wiki?workspace=ws_a&page=3&q=保留';navigation.navigateTo('jobs',{workspace:'ws_a'});navigation.navigateTo('wiki',{workspace:'ws_a'});assert.equal(navigation.readRoute().params.get('page'),'3');assert.equal(navigation.readRoute().params.get('q'),'保留');navigation.navigateTo('wiki',{workspace:'ws_b'});assert.equal(navigation.readRoute().params.has('q'),false)})
