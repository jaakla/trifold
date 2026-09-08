import {SettlementCheck,CLASSES} from '../sdk/settlementcheck.mjs';
import {bboxCover,cellRing} from '../sdk/trifold.js';
import {createMapDemo,loadWithRetry,withinBudget} from './map-demo.mjs';
const COLORS={10:'#bdf2ff',11:'#b0e0a4',12:'#51b07c',13:'#207b6b',21:'#ffea4e',22:'#ef8a3f',23:'#7a3e20',30:'#f32b25'};
const legend=document.getElementById('legend');
for(const code of [30,23,22,21,13,12,11,10]) legend.insertAdjacentHTML('beforeend',`<div class="legend-row"><span class="swatch" style="background:${COLORS[code]}"></span><span class="code">${code}</span><span>${CLASSES[code].label}</span></div>`);
const status=document.getElementById('status'),result=document.getElementById('result');
const sc=await loadWithRetry(()=>SettlementCheck.fromUrl('./data/degurba_R2025A_E2025_L12.tfdg'),status);
status.innerHTML=`Classes ready · <b>${(sc.nCells/1e6).toFixed(0)}M cells</b> · details optional`;
const EMPTY={type:'FeatureCollection',features:[]};
const presets=[...document.querySelectorAll('[data-place]')].map(button=>{const [lon,lat,zoom]=button.dataset.place.split(',').map(Number);return {name:button.textContent,center:[lon,lat],zoom};});
document.querySelector('.presets').remove();
const demo=createMapDemo({container:'map',initialView:{center:[24.75,59.44],zoom:10.5,projection:'mercator'},limits:{points:5000},adapter:{
  id:'settlementcheck',presets,layers:['cells-fill','cells-line'],
  queryPoint:([lon,lat])=>selectPoint(lon,lat),describeResult:r=>describe(r),
  queryBatch:([lon,lat])=>sc.classify(lon,lat),pointColor:r=>COLORS[r.code]||'#999',
  clearSelection:()=>{selectedPoint=null;selectionToken++;},
  setVisible:visible=>{overlayVisible=visible;if(!visible){demo.cancel('overlay');map.getSource('cells')?.setData(EMPTY);status.textContent='Settlement overlay hidden.';}else if(map.getSource('cells'))renderLayer();},
  dispose:()=>{clearTimeout(timer);sc.unloadDetails();}
}});
const map=demo.map;
function centre(ring){let x=0,y=0,z=0;for(const [lon,lat] of ring.slice(0,-1)){const a=lon*Math.PI/180,b=lat*Math.PI/180,c=Math.cos(b);x+=c*Math.cos(a);y+=c*Math.sin(a);z+=Math.sin(b)}return [Math.atan2(y,x)*180/Math.PI,Math.atan2(z,Math.hypot(x,y))*180/Math.PI]}
let selectedPoint=null,selectionToken=0;
function selectPoint(lon,lat){
  selectedPoint=[lon,lat];selectionToken++;
  return sc.classify(lon,lat);
}
function describe(r){
  result.innerHTML=`<strong>${r.label??'No source data'}</strong>
    <span class="small">${r.settlementClass??'No classification'}${r.code===null?'':` · code ${r.code}`}</span>
    <dl><dt>Surface</dt><dd>${r.surface??'Details not loaded'}</dd>
    <dt>Level 1</dt><dd>${r.level1Class===null?'—':`${r.level1Class} (${r.level1Code})`}</dd>
    <dt>Class share</dt><dd>${r.classShare===null?'—':(r.classShare*100).toFixed(1)+'%'}</dd>
    <dt>Boundary</dt><dd>${r.mixed===null?'Details not loaded':r.mixed?'Mixed':'Homogeneous'}</dd>
    <dt>Nodata mix</dt><dd>${r.nodataMixed===null?'Details not loaded':r.nodataMixed?'Yes':'No'}</dd>
    <dt>T3 cell</dt><dd>${r.cell} · L${r.level}</dd>
    <dt>Population</dt><dd>Not included in this classification dataset</dd></dl>
    ${r.detailsLoaded?'':`<button id="load-details" class="action">Load boundary details for this point</button><div id="detail-status" class="small" role="status"></div>`}
    <details><summary>Source details</summary><dl>
    <dt>Status</dt><dd>${r.status}</dd>
    <dt>Source</dt><dd>${r.source} / ${r.sourceRelease}</dd>
    <dt>Year</dt><dd>${r.year} · ${r.estimateKind}</dd>
    <dt>Resolution</dt><dd>${r.sourceResolutionKm} km source grid</dd></dl>
    <p class="small">Population counts require the separate <a href="https://human-settlement.emergency.copernicus.eu/ghs_wup_pop_r2025a.php">GHS-WUP-POP</a> dataset; a settlement class does not determine a population number.</p></details>`;
  const button=document.getElementById('load-details');
  if(button)button.onclick=async()=>{
    const token=selectionToken,point=selectedPoint;
    button.disabled=true;document.getElementById('detail-status').textContent='Loading boundary details…';
    try{const detailed=await sc.checkAsync(...point);if(token===selectionToken)demo.present(detailed)}
    catch(error){if(token===selectionToken){button.disabled=false;document.getElementById('detail-status').textContent='Details unavailable. Classes remain available; click to retry.'}}
  };
}
let overlayVisible=true;
// Bound geometry uploads: wider L12 views exhausted memory in browser QA.
// Coarser datasets are needed to extend this overview beyond the cell budget.
const CELL_CAP=6500,MIN_OVERLAY_ZOOM=8.4;
const wrapLongitude=lon=>((lon+180)%360+360)%360-180;
async function renderLayer(){
  const task=demo.task('overlay');
  if(!map.getSource('cells'))return;
  if(!overlayVisible){map.getSource('cells').setData(EMPTY);status.textContent='Settlement overlay hidden.';return;}
  const b=map.getBounds(),lat=(b.getNorth()+b.getSouth())/2;
  const width=(b.getEast()-b.getWest())*111*Math.max(.15,Math.cos(lat*Math.PI/180));
  const height=(b.getNorth()-b.getSouth())*111,estimate=width*height/1.52;
  if(map.getZoom()<MIN_OVERLAY_ZOOM||!withinBudget(estimate,CELL_CAP)){
    map.getSource('cells').setData(EMPTY);
    status.innerHTML=`Zoom in to preview <b>L12 settlement cells</b>. Wider views need a coarser dataset (${CELL_CAP.toLocaleString()}-cell limit).`;
    return;
  }
  status.textContent='Classifying visible cells…';
  await new Promise(requestAnimationFrame);
  if(!task.current())return;
  const started=performance.now();
  try{
    // bboxCover accepts west > east for an antimeridian-crossing viewport.
    const addresses=bboxCover(wrapLongitude(b.getWest()),b.getSouth(),wrapLongitude(b.getEast()),b.getNorth(),12,{mode:'intersects'});
    if(addresses.length>CELL_CAP){
      map.getSource('cells').setData(EMPTY);
      status.innerHTML=`${addresses.length.toLocaleString()} cells exceed the cap · <b>zoom in</b>`;
      return;
    }
    const features=[];
    for(let i=0;i<addresses.length;i++){
      if(i%512===0){
        await new Promise(requestAnimationFrame);
        if(!task.current())return;
      }
      const ring=cellRing(addresses[i]),point=centre(ring);
      const r=document.getElementById('mixed').checked?await sc.checkAsync(...point):sc.classify(...point);
      if(!task.current())return;
      features.push({type:'Feature',properties:{code:r.code??-1,mixed:r.mixed===null?-1:r.mixed?1:0},
        geometry:{type:'Polygon',coordinates:[ring]}});
    }
    map.getSource('cells').setData({type:'FeatureCollection',features});
    status.innerHTML=`Rendered <b>${features.length.toLocaleString()} real L12 cells</b> in ${(performance.now()-started).toFixed(0)} ms`;
  }catch(error){
    if(!task.current())return;
    if(document.getElementById('mixed').checked){
      document.getElementById('mixed').checked=false;
      document.getElementById('layer-detail-status').textContent='Boundary details unavailable; showing classes. Toggle again to retry.';
      updateLayerPaint(false);renderLayer();return;
    }
    map.getSource('cells').setData(EMPTY);
    status.textContent='Unable to draw this area. Pan or zoom to retry.';
    console.error(error);
  }
}
map.on('load',()=>{map.addSource('cells',{type:'geojson',data:EMPTY});map.addLayer({id:'cells-fill',type:'fill',source:'cells',paint:{'fill-color':['match',['get','code'],10,COLORS[10],11,COLORS[11],12,COLORS[12],13,COLORS[13],21,COLORS[21],22,COLORS[22],23,COLORS[23],30,COLORS[30],'#bbb'],'fill-opacity':.73}});map.addLayer({id:'cells-line',type:'line',source:'cells',paint:{'line-color':['case',['==',['get','mixed'],1],'#111','#fff'],'line-opacity':['case',['==',['get','mixed'],1],.72,.22],'line-width':['case',['==',['get','mixed'],1],1.2,.35]}});renderLayer()});
let timer;
map.on('movestart',()=>{demo.cancel('overlay');clearTimeout(timer)});
map.on('moveend',()=>{clearTimeout(timer);timer=setTimeout(renderLayer,80)});
function updateLayerPaint(enabled){
  if(!map.getLayer('cells-fill'))return;
  demo.setPaint('cells-fill','fill-opacity',enabled?['case',['==',['get','mixed'],1],.9,.24]:.73);
  map.setPaintProperty('cells-line','line-width',enabled?['case',['==',['get','mixed'],1],2,.25]:['case',['==',['get','mixed'],1],1.2,.35]);
}
document.getElementById('mixed').onchange=event=>{
  document.getElementById('layer-detail-status').textContent='';
  if(!event.target.checked)sc.unloadDetails();
  updateLayerPaint(event.target.checked);
  renderLayer();
};
window.__settlementcheck={map,sc,renderLayer,demo};
