import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {safeStoredArray, RequestOwnership, blendInputs, routeFromHash} from '../assets/state.mjs';

// A small DOM harness exercises the actual application functions. Live browser QA
// additionally verifies geometry, browser focus behavior and assistive semantics.
const source=(await readFile(new URL('../assets/app.js',import.meta.url),'utf8')).replace(/^import .*?;\s*/m,'');
function harness(fetcher=async()=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>({movies:[]})})) {
  let document;
  class Element {
    constructor(id='') {this.id=id;this.children=[];this.attributes={};this.dataset={};this.style={};this.textContent='';this.value='';this.isConnected=true;this.classes=new Set(id.includes('modal-shell')?['hidden']:[]);this.classList={add:(...v)=>v.forEach(x=>this.classes.add(x)),remove:(...v)=>v.forEach(x=>this.classes.delete(x)),contains:v=>this.classes.has(v),toggle:(v,on)=>{on=on??!this.classes.has(v);on?this.classes.add(v):this.classes.delete(v);return on;}};}
    set innerHTML(value) {this.html=value;this.children=[];}
    get innerHTML() {return this.html||'';}
    setAttribute(key,value) {this.attributes[key]=String(value);}
    getAttribute(key) {return this.attributes[key]??null;}
    removeAttribute(key) {delete this.attributes[key];}
    appendChild(value) {this.children.push(value);return value;}
    append(...values) {this.children.push(...values);}
    replaceChildren(...values) {this.children=[...values];}
    focus() {document.activeElement=this;}
    closest() {return null;}
    querySelector() {return this.children[0]||null;}
    querySelectorAll() {return this.children;}
    contains(value) {return this===value||this.children.includes(value);}
    getClientRects() {return [{}];}
    addEventListener() {}
  }
  const elements=new Map();
  const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  document={getElementById:get,createElement:()=>new Element(),querySelector:()=>get('site-shell'),querySelectorAll:selector=>selector==='.modal-shell'?[...elements.values()].filter(el=>el.id.endsWith('modal-shell')):[],body:get('body'),addEventListener(){},activeElement:get('start-focus')};
  const context=vm.createContext({document,localStorage:{getItem:()=>null,setItem(){},removeItem(){}},fetch:fetcher,Headers,FormData,AbortController,DOMException,URL,URLSearchParams,console,setTimeout,clearTimeout,requestAnimationFrame:callback=>callback(),safeStoredArray,RequestOwnership,blendInputs,routeFromHash});
  context.location={hash:'#explore'};
  vm.runInContext(source,context);
  return {context,get,document,run:code=>vm.runInContext(code,context)};
}

test('actual search surface retains the newer result under reversed completion',async()=>{
  const pending=[];
  const h=harness(()=>new Promise(resolve=>pending.push(resolve)));
  const first=h.run("executeMainSearch('older query')");
  const second=h.run("executeMainSearch('newer query')");
  const response=message=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>({movies:[],exact_match:false,message})});
  pending[1](response('New query explanation'));await second;
  pending[0](response('Stale query explanation'));await first;
  assert.equal(h.get('search-feedback-banner').textContent,'New query explanation');
  assert.match(h.get('main-search-grid-results').innerHTML,/newer query/);
});

test('actual genre selection preserves its button and separate signup/browse state',()=>{
  const h=harness();
  h.run("state.allGenres=['Drama','Comedy'];renderProfileGenreChips();");
  const button=h.get('browse-genre-grid').children[0];button.focus();button.onclick();
  assert.equal(h.get('browse-genre-grid').children[0],button);
  assert.equal(h.document.activeElement,button);
  assert.equal(button.getAttribute('aria-pressed'),'true');
  assert.equal(h.run("state.browseGenres.has('Drama')"),true);
  assert.equal(h.run("state.genres.has('Drama') || state.signupGenres.has('Drama') || state.hybridGenres.has('Drama')"),false);
});

test('actual modal stack gives only the top dialog modal ownership and Escape',()=>{
  const h=harness();const search=h.get('search-modal-shell'),movie=h.get('movie-modal-shell'),list=h.get('add-to-list-modal-shell');
  h.run('openModal(elements.searchModalShell,elements.mainSearchInput);openModal(elements.movieModalShell,elements.movieModalClose);openModal(elements.addToListModalShell,elements.addToListModalClose);');
  assert.equal(search.inert,true);assert.equal(movie.inert,true);assert.equal(list.inert,false);
  assert.equal(search.getAttribute('aria-modal'),'false');assert.equal(list.getAttribute('aria-modal'),'true');
  h.run("handleModalKeyboard({key:'Escape',preventDefault(){}})");
  assert.equal(list.classList.contains('hidden'),true);assert.equal(movie.inert,false);assert.equal(search.classList.contains('hidden'),false);
  assert.equal(h.document.activeElement,h.get('movie-modal-close'));
});

test('account generation protects profile data after a session replacement',async()=>{
  let resolve;const h=harness(()=>new Promise(done=>resolve=done));
  h.run("state.token='old-user';");const request=h.run("api('/auth/me',{owner:'profile'})");
  h.run("ownership.resetSession();state.token='new-user';");
  resolve({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>({username:'old-user'})});
  await assert.rejects(request,error=>error.name==='AbortError');
  assert.equal(h.run('state.token'),'new-user');
});

test('personal pagination resets on account replacement without resetting archive browsing',()=>{
  const h=harness();h.run("state.pages={watched:8,watchlist:4,lists:3,owner:2,shared:1,archive:5};resetPersonalPages();");
  assert.equal(h.run('state.pages.watched'),1);assert.equal(h.run('state.pages.watchlist'),1);assert.equal(h.run('state.pages.lists'),1);assert.equal(h.run('state.pages.archive'),5);
});

test('a completed owner-list mutation cannot reverse newer navigation',()=>{
  const h=harness();h.run("state.currentPage='owner-list';location.hash='#my-list/4';");
  assert.equal(h.run('canReloadOwnerList(4)'),true);
  h.run("state.currentPage='explore';location.hash='#explore';");assert.equal(h.run('canReloadOwnerList(4)'),false);
  h.run("state.currentPage='owner-list';location.hash='#my-list/5';");assert.equal(h.run('canReloadOwnerList(4)'),false);
});

test('browser availability cache expires and evicts its oldest entry',()=>{
  const h=harness();h.run("cacheAvailability('IN:1',{status:'available'},Date.now()-7*3600000);");
  assert.equal(h.run("cachedAvailability('IN:1')"),undefined);
  h.run("for(let i=0;i<600;i++)cacheAvailability('IN:'+i,{status:'available'});");
  assert.equal(h.run('state.availability.size'),512);assert.equal(h.run("state.availability.has('IN:0')"),false);
});

test('exploration shows one provider link while movie details show all providers',()=>{
  const h=harness();h.run("cacheAvailability('IN:1',{status:'available',providers:['Netflix','Prime Video','Apple TV'].map(name=>({name,types:['flatrate'],logo_path:''}))});");
  const card=h.run('createWatchArea(1)');
  assert.equal(card.children.find(child=>child.className==='provider-chips').children.length,1);
  assert.equal(card.children.some(child=>child.className==='availability-link'),false);
  const details=h.run("createWatchArea(1,'details')");
  assert.equal(details.children.find(child=>child.className==='provider-chips').children.length,3);
  assert.equal(details.children.some(child=>child.className==='availability-link'),true);
});

test('browser caching preserves the original provider check time',()=>{
  const h=harness();h.run("cacheAvailability('IN:2',{status:'available',checked_at:new Date(Date.now()-7*3600000).toISOString()});");
  assert.equal(h.run("cachedAvailability('IN:2')"),undefined);
});
