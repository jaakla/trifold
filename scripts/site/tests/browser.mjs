// Browser plugin unavailable: bounded, sequential Playwright fallback.
const {chromium}=await import(process.env.TRIFOLD_PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import http from 'node:http';
import assert from 'node:assert/strict';
import {deflateSync} from 'node:zlib';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const root=join(repo,'docs');
const fixture=await fs.mkdtemp(join(tmpdir(),'trifold-site-qa-'));
execFileSync(process.env.TRIFOLD_PYTHON||join(repo,'.venv/bin/python'),[join(repo,'scripts/site/tests/build_fixture.py'),fixture]);
console.log('UI-only synthetic fixture and screenshots:',fixture);
let details=0,failDetails=true;
const server=http.createServer(async(req,res)=>{try{const path=new URL(req.url,'http://localhost').pathname;let file=root+path;
  if(path.endsWith('.tfdg'))file=fixture+'/degurba_R2025A_E2025_L12.tfdg';
  if(path.endsWith('.tfdd')){details++;if(failDetails){res.writeHead(503);res.end();return;}file=fixture+'/degurba_R2025A_E2025_L12.details/'+path.split('/').at(-1);}
  let content=await fs.readFile(file);
  if(path==='/sdk/trifold.js'){content=content.toString().replace('export function bboxCover(', 'function originalBboxCover(');content+='\nexport function bboxCover(w,s,e,n,level){return [locateAddress(w,s,level)];}\n';}
  if(path==='/assets/index-demo.mjs'){
    content=content.toString().replace('const {DATASETS,PMTILES_DATASETS,DATASET_STATS}=window.TRIFOLD_DATA;', 'const {DATASETS,DATASET_STATS}=window.TRIFOLD_DATA; const PMTILES_DATASETS={};')
      .replace('async function decode(key){', "async function decode(key){return {type:'FeatureCollection',features:[cellFeature(locateAddress(24.7536,59.4370,6))]};");
  }
  res.setHeader('Content-Type',path.endsWith('.html')?'text/html':path.endsWith('.css')?'text/css':/\.(m?js)$/.test(path)?'text/javascript':'application/octet-stream');res.end(content);
}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true});
try{for(const name of (process.env.QA_PAGES||'settlementcheck,landcheck,countrycheck,index,demo,sdk-api,t3-technical-reference').split(',')){
 const page=await browser.newPage({viewport:{width:1505,height:1045}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log(name,e.message);});page.on('console',m=>{if(m.type()==='error')console.log(name,m.text().slice(0,200));});
 page.setDefaultTimeout(15000);page.on('crash',()=>console.log('PAGE CRASH',name));
 let refinementFails=true;
 await page.route(/\.(tflr|tfcr)(\?|$)/,route=>{if(refinementFails)return route.fulfill({status:503,body:'UI fixture failure'});const header=Buffer.alloc(12);header.write(name==='landcheck'?'TFLR':'TFCR');header[4]=1;header[5]=10;return route.fulfill({status:200,body:Buffer.concat([header,deflateSync(Buffer.alloc(0))])});});
 page.on('response',r=>{if(r.status()>=400)console.log('HTTP',r.status(),r.url());});
 const start=Date.now();await page.goto(`http://127.0.0.1:${server.address().port}/${name}.html`);
 let readyMs=Date.now()-start;
 assert.match(await page.title(),/Trifold documentation/);
 assert.ok(await page.locator('main').innerText());
 assert.equal(new URL(page.url()).pathname,`/${name}.html`);
 if(name==='index'){
   assert.equal(await page.locator('.map-demo, canvas').count(),0);
   assert.equal(await page.evaluate(()=>performance.getEntriesByType('resource').some(r=>/maplibre|pmtiles|topojson|index-demo|sdk\//.test(r.name))),false);
   await page.locator('.page-actions a[href="demo.html"]').click();
   assert.equal(new URL(page.url()).pathname,'/demo.html');
   await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);
   for(const hash of ['demo','coverage']){
     await page.goto(`http://127.0.0.1:${server.address().port}/index.html?projection=mercator&covermap-projection=globe#${hash}`);
     await page.waitForURL(`**/demo.html?projection=mercator&covermap-projection=globe#${hash}`);
   }
   await page.goto(`http://127.0.0.1:${server.address().port}/index.html#concept`);
   assert.equal(new URL(page.url()).pathname,'/index.html');
   await page.evaluate(()=>scrollTo(0,0));
 }
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);
 if(['settlementcheck','landcheck','countrycheck','demo'].includes(name)){
   await page.waitForFunction(name=>window['__'+(name==='demo'?'trifold':name)]?.map.getSource(name==='demo'?'grid':name==='settlementcheck'?'cells':'points'),name,{timeout:30000});
   readyMs=Date.now()-start;
   await page.waitForTimeout(150);
   await page.screenshot({path:join(fixture,`${name}-entry.png`)});
   const frame=page.locator('.map-demo').first();await frame.scrollIntoViewIfNeeded();
   await frame.locator('[name=longitude]').fill('24.7536');await frame.locator('[name=latitude]').fill('59.437');
   await frame.getByRole('button',{name:'Inspect point',exact:true}).click();
   await page.waitForTimeout(350);assert.match(await frame.locator('.demo-status:not(.demo-layer-status)').innerText(),/Point ready/);
   await frame.getByRole('button',{name:'Copy result',exact:true}).click();
   assert.ok(JSON.parse(await page.evaluate(()=>navigator.clipboard.readText())));
   await frame.getByRole('button',{name:'Copy coordinates',exact:true}).click();
   assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/24.753/);
   await frame.getByRole('button',{name:'Clear selection',exact:true}).click();
   assert.match(await frame.locator('.demo-result').innerText(),/Select a point/);
   await frame.locator('[name=latitude]').fill('91');await frame.getByRole('button',{name:'Inspect point',exact:true}).click();
   assert.match(await frame.locator('.demo-status:not(.demo-layer-status)').innerText(),/latitude/);
   await frame.locator('[name=latitude]').fill('59.437');await frame.getByRole('button',{name:'Inspect point',exact:true}).click();
   await frame.getByRole('button',{name:'Globe',exact:true}).click();await frame.getByRole('button',{name:'Flat (Mercator)',exact:true}).click();
   assert.match(page.url(),/projection=mercator/);
   if(name==='settlementcheck'){
     assert.equal(details,0);await page.getByRole('button',{name:'Load boundary details for this point'}).click();
     await page.waitForFunction(()=>document.querySelector('#detail-status')?.textContent.includes('unavailable'));failDetails=false;
     await page.getByRole('button',{name:'Load boundary details for this point'}).click();await page.waitForFunction(()=>!document.querySelector('#load-details'));
     assert.equal(details,2);assert.match(await page.locator('#result').innerText(),/60.0%/);
     await frame.locator('.demo-tools summary').click();
     await page.locator('#mixed').check();await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Rendered'));
     await page.locator('#mixed').uncheck();
     // No over-cap allocation: the budget gate empties the source at low zoom.
     await page.evaluate(()=>__settlementcheck.map.jumpTo({zoom:8}));
     await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('6,500'));
     await page.evaluate(()=>__settlementcheck.map.jumpTo({center:[180,0],zoom:11}));
     await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Rendered'));
     await page.evaluate(()=>__settlementcheck.demo.select(180.01,0));
     assert.match(await frame.locator('[name=longitude]').inputValue(),/-179.99/);
     await frame.locator('.demo-tools summary').click();
   }
   await frame.locator('.demo-visible').uncheck();await frame.locator('.demo-visible').check();
   if(['settlementcheck','landcheck','countrycheck'].includes(name)){
     await frame.locator('.demo-batch summary').click();await frame.locator('.demo-batch input').setInputFiles({name:'tiny.csv',mimeType:'text/csv',buffer:Buffer.from('lon,lat\n24.7536,59.437\n-0.1276,51.5072\ninvalid,10')});
     await page.waitForFunction(()=>document.querySelector('.demo-status').textContent.includes('2 points classified; 1 invalid'));
     await frame.locator('.batch-clear').click();
     await frame.locator('.batch-sample').click();await page.waitForFunction(()=>document.querySelector('.demo-status').textContent.includes('points classified'));
   }
   if(name==='landcheck'||name==='countrycheck'){
     await frame.locator('.demo-tools summary').click();
     await page.locator('#seg-mode [data-v=route]').click();await page.locator('#b-route-eu').click();
     assert.match(await page.locator('#routenote').innerText(),/classified/);
     await page.locator('#fileinput').setInputFiles({name:'tiny-route.geojson',mimeType:'application/json',buffer:Buffer.from('{"type":"LineString","coordinates":[[24.7536,59.437],[24.754,59.438]]}')});
     await page.waitForTimeout(100);assert.equal(await page.locator('#droperr').innerText(),'');
     await page.locator('#b-route-clear').click();
     await page.locator('#seg-mode [data-v=points]').click();
     await page.locator('#refinecb').check();await page.waitForFunction(()=>!document.querySelector('#refinecb').checked&&!document.querySelector('#refinecb').disabled);
     refinementFails=false;await page.locator('#refinecb').check();await page.waitForFunction(()=>document.querySelector('#refinenote').textContent.includes('Loaded:'));
     await page.locator('#refinecb').uncheck();
   }
   if(name==='demo'){
     await frame.locator('.demo-tools summary').click();await page.locator('#seg-level [data-v="4"]').click();
     await page.locator('#seg-sys [data-v="h3"]').click();await page.waitForTimeout(100);assert.match(await page.locator('#sysnote').innerText(),/Uber H3/);
     await page.locator('#seg-sys [data-v="tri"]').click();
     const cover=page.locator('.map-demo').nth(1);await cover.locator('.demo-tools summary').click();
     await page.locator('#cover-compare [data-v="s2"]').click();await page.locator('#cover-run').click();
     assert.match(await page.locator('#cover-status').innerText(),/S2/);
     await page.locator('#cover-output [data-v="ranges"]').click();
     await page.locator('#cover-format [data-v="addr64"]').click();
     await cover.getByRole('button',{name:'Globe',exact:true}).click();await cover.getByRole('button',{name:'Flat (Mercator)',exact:true}).click();
     await cover.locator('[name=longitude]').fill('24.7536');await cover.locator('[name=latitude]').fill('59.437');await cover.getByRole('button',{name:'Inspect point',exact:true}).click();
     await page.waitForTimeout(100);assert.match(await cover.locator('.demo-result').innerText(),/cell/);
   }
 }
 const code=page.locator('pre:has(code)').first();if(await code.count()){const expected=await code.locator('code').innerText();await code.getByRole('button',{name:'Copy code'}).click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),expected);}
 await page.evaluate(()=>document.querySelectorAll('.demo-side').forEach(n=>n.scrollTop=0));
 await page.screenshot({path:join(fixture,`${name}-desktop.png`)});
 for(const width of [1440,1024,390,320]){await page.setViewportSize({width,height:width===1440?900:width===1024?768:844});await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(120);if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))console.log('overflow',name,width,await page.evaluate(()=>[...document.querySelectorAll('main *')].filter(n=>n.getBoundingClientRect().right>innerWidth).slice(0,15).map(n=>[n.tagName,n.id,n.className,n.getBoundingClientRect().width])));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${name} overflow ${width}`);if(width===390){await page.screenshot({path:join(fixture,`${name}-mobile.png`)});await page.getByRole('button',{name:'Menu',exact:true}).click();assert.equal(await page.locator('#product-nav a:visible').count(),7);await page.keyboard.press('Escape');assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'),'false');}}
 console.log(JSON.stringify({name,readyMs,flowMs:Date.now()-start,errors}));assert.deepEqual(errors,[]);await page.close();
}}finally{await browser.close();server.close();}
