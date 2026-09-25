import {createMapDemo,createGeneration,yieldFrame} from './map-demo.mjs';
import {
  bboxCover, cellFeature, coverRanges, fromPath, parent64, polyfill, toCompact, locateAddress,
} from '../sdk/trifold.js';
import {
  s2Cover, s2Compact, s2CellFeature, s2LevelForT3,
} from '../sdk/s2mini.js';
const {DATASETS,PMTILES_DATASETS,DATASET_STATS}=window.TRIFOLD_DATA;

const LEVEL_COLORS={0:'#3f0008',1:'#67000d',2:'#a50f15',3:'#cb181d',4:'#ef3b2c',
  5:'#fb6a4a',6:'#fc9272',7:'#fcbba1',8:'#fee0d2'};
const COASTAL='#74a9cf';

const SYS_NOTES={
 tri:'Trifold T3: icosahedral triangles, exact aperture-4 nesting. Click a cell for its '+
     'compact base32 address, digit path and uint64. Pole cells are meridian wedges reaching '+
     '±90°. Mercator clips them; Globe displays the complete geometry.',
 a5:'<a href="https://a5geo.org" target="_blank">A5</a> (Felix Palmer, 2025): dodecahedral '+
    'pentagons, res 6 (~8,300 km²), with equal area within each level. '+
    'Aperture-4 hierarchy is <i>logical</i>: parents only approximately cover children. '+
    'Compacted via native a5.compact.',
 h3:'Uber H3, res 3 hexagons (~12,400 km²), with 12 pentagons globally. Aperture-7 '+
    'parents only approximately contain children; compacted via native h3.compact_cells.',
 s2:'Google S2 (via s2sphere), level 6 (~20,750 km²). Cube-sphere quadtree with exact '+
    'aperture-4 nesting and Hilbert indexing; cell areas vary ~2× face-centre to '+
    'corner. The pole sits at a cube-face centre = shared corner of 4 cells.',
 rhpx:'rHEALPix res 4 (~12,950 km², aperture 9: 3×3 children with exact nesting). Near-exact '+
    'equal area with polar cap and dart cells. The grid is included in the OGC DGGS standard.',
 htm:'HTM-style octahedral triangles, level 6 (~15,570 km²), based on the astronomy grid '+
    'and generated here on an octahedron. Its 90° faces produce more shape deformation than '+
    'the T3 icosahedron.',
 rect:'Plain lon/lat quadtree, level 7 (~15,500 km² at the equator, shrinking toward the '+
    'poles). Globe view shows the convergence of meridians at the poles.',
};
const GROUP_NOTES={
 triangle:' The triangle layer is the source geometry and exact accounting unit.',
 rhombus:' Full-grid rhombi are exact two-triangle groups with a nested Hilbert-addressed diamond hierarchy. Land-filtered layers may show partial groups.',
 hex:' Hex groups contain six triangles in face interiors. Icosahedron seams and vertices have smaller or phase-shifted groups.',
};

let state={sys:'tri',level:'6',mode:'compacted',group:'triangle',proj:'globe'};
const cache={};
const protocol=new pmtiles.Protocol();
maplibregl.addProtocol('pmtiles',protocol.tile);

async function decode(key){
  if(cache[key])return cache[key];
  const b=Uint8Array.from(atob(DATASETS[key]),c=>c.charCodeAt(0));
  const stream=new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'));
  const topo=JSON.parse(await new Response(stream).text());
  const gj=topojson.feature(topo,topo.objects[Object.keys(topo.objects)[0]]);
  if(key.startsWith('tri_'))for(const feature of gj.features)
    if(feature.properties.path&&!feature.properties.addr64)
      feature.properties.addr64=fromPath(feature.properties.path).toString();
  for(const old of Object.keys(cache))delete cache[old];
  cache[key]=gj;return gj;
}
function dataKey(){
  if(state.sys!=='tri')return `${state.sys}_${state.mode}`;
  const suffix=state.group==='triangle'?'':`_${state.group}`;
  return `tri_L${state.level}_${state.mode}${suffix}`;
}

const fillPaint={
  'fill-color':['case',['!',['get','interior']],COASTAL,
    ['match',['get','level'],0,LEVEL_COLORS[0],1,LEVEL_COLORS[1],2,LEVEL_COLORS[2],
     3,LEVEL_COLORS[3],4,LEVEL_COLORS[4],5,LEVEL_COLORS[5],6,LEVEL_COLORS[6],
     7,LEVEL_COLORS[7],LEVEL_COLORS[8]]],
  'fill-opacity':0.55};
function addGridLayers(sourceLayer){
  const sourceSpec={source:'grid'};
  if(sourceLayer)sourceSpec['source-layer']=sourceLayer;
  map.addLayer({id:'grid-fill',type:'fill',...sourceSpec,paint:fillPaint});
  map.addLayer({id:'grid-line',type:'line',...sourceSpec,
    paint:{'line-color':'#333','line-width':0.5,'line-opacity':0.7}});
}
function replaceGridSource(source,sourceLayer){
  if(map.getLayer('grid-line'))map.removeLayer('grid-line');
  if(map.getLayer('grid-fill'))map.removeLayer('grid-fill');
  if(map.getSource('grid'))map.removeSource('grid');
  map.addSource('grid',source);
  addGridLayers(sourceLayer);
}

const demo=createMapDemo({container:'map',initialView:{center:[10,30],zoom:1.6},adapter:{
  id:'comparison',layers:['grid-fill','grid-line'],
  presets:[{name:'Tallinn',center:[24.7536,59.4370],zoom:5},{name:'London',center:[-0.1276,51.5072],zoom:5}],
  queryPoint:([lon,lat])=>{const hits=map.queryRenderedFeatures(map.project([lon,lat]),{layers:['grid-fill']});return hits[0]?.properties??(state.sys==='tri'?{cell:toCompact(locateAddress(lon,lat,Number(state.level))),level:Number(state.level),status:'Base-resolution lookup; no displayed land-filtered cell at this point'}:{status:'No displayed grid cell at this point',system:state.sys});}
}});
const map=demo.map;
window.__trifold={map,demo};

map.on('load',async()=>{
  map.addSource('grid',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
  addGridLayers();

  map.on('mouseenter','grid-fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','grid-fill',()=>map.getCanvas().style.cursor='');
  await refresh();
});

const refreshGeneration=createGeneration();
async function refresh(){
  const task=refreshGeneration.next();
  document.getElementById('loading').style.display='flex';
  document.getElementById('row-level').style.display=state.sys==='tri'?'block':'none';
  document.getElementById('row-group').style.display=state.sys==='tri'?'block':'none';
  const key=dataKey();
  let byLevel={},nInt=0,n=0;
  if(PMTILES_DATASETS[key]){
    const spec=PMTILES_DATASETS[key];
    const url=new URL(spec.url,window.location.href).href;
    replaceGridSource({type:'vector',url:`pmtiles://${url}`},spec.sourceLayer);
    const stats=DATASET_STATS[key];
    byLevel=stats.byLevel;nInt=stats.interior;n=stats.count;
  }else{
    const gj=await decode(key);
    if(!task.current())return;
    replaceGridSource({type:'geojson',data:gj});
    for(const f of gj.features){
      byLevel[f.properties.level]=(byLevel[f.properties.level]||0)+1;
      if(f.properties.interior)nInt++;
    }
    n=gj.features.length;
  }
  const unit=state.sys==='tri'&&state.group!=='triangle'?'groups':'cells';
  document.getElementById('stats').innerHTML=
    `<b>${n.toLocaleString()}</b> ${unit} · ${nInt.toLocaleString()} interior · `+
    `${(n-nInt).toLocaleString()} coastal`;
  document.getElementById('legend').innerHTML=
    Object.keys(byLevel).sort((a,b)=>a-b).map(L=>
      `<i style="background:${LEVEL_COLORS[L]||'#ccc'}"></i>level ${L}: `+
      `${byLevel[L].toLocaleString()}`).join('<br>')+
    `<br><i style="background:${COASTAL}"></i>coastal (mixed)`;
  document.getElementById('sysnote').innerHTML=SYS_NOTES[state.sys]+
    (state.sys==='tri'?GROUP_NOTES[state.group]:'');
  document.getElementById('loading').style.display='none';
}
function wireSeg(id,prop,cb){
  const seg=document.getElementById(id);
  seg.querySelectorAll('button').forEach(b=>{b.onclick=()=>{
    seg.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');state[prop]=b.dataset.v;cb();};});
}
wireSeg('seg-sys','sys',refresh);
wireSeg('seg-level','level',refresh);
wireSeg('seg-group','group',refresh);
wireSeg('seg-mode','mode',refresh);


const COVER_LEVEL_LABELS={3:'~880 km',4:'~440 km',5:'~220 km',6:'~110 km',
  7:'~55 km',8:'~28 km',9:'~14 km',10:'~7 km',11:'~3.4 km'};
const COVER_RENDER_LIMIT=1600;
const COVER_OUTPUT_LIMIT=260;
const COVER_RANGE_LIMIT=120;
const COVER_CELL_CAP=50000;
const coverState={
  draw:'bbox',
  level:6,
  mode:'intersects',
  output:'full',
  format:'compact',
  compare:'t3',
  bbox:[-0.55,51.25,0.25,51.75],
  previewBbox:null,
  polygon:[],
  dragging:false,
  dragStart:null,
  cells:[],
  compacted:[],
  ranges:[],
  s2Level:0,
  s2Cells:[],
  s2Compacted:[],
  s2Capped:false,
  elapsedMs:0,
};

const coverDemo=createMapDemo({container:'covermap',initialView:{center:[-0.12,51.5],zoom:7,projection:'mercator'},adapter:{
  id:'coverage',layers:['cover-query-fill','cover-query-line','cover-query-point','cover-cells-fill','cover-cells-line','cover-s2-cells-fill','cover-s2-cells-line'],
  presets:[{name:'London',center:[-0.12,51.5],zoom:7},{name:'Tallinn',center:[24.7536,59.4370],zoom:7}],
  acceptClick:()=>coverState.draw!=='polygon'&&!coverState.dragging,
  queryPoint:([lon,lat])=>({grid:'T3',cell:toCompact(locateAddress(lon,lat,coverState.level)),level:coverState.level})
}});
const coverMap=coverDemo.map;
coverMap.doubleClickZoom.disable();

function coverCollection(features=[]){return {type:'FeatureCollection',features};}
function compareCoverBigInt(a,b){return a<b?-1:a>b?1:0;}
function normalizeLng(lng){
  const wrapped=((((lng+180)%360)+360)%360)-180;
  return wrapped===-180&&lng>0?180:wrapped;
}
function clampLat(lat){return Math.max(-90,Math.min(90,lat));}
function cleanCoord(coord){return [Number(normalizeLng(coord[0]).toFixed(6)),
  Number(clampLat(coord[1]).toFixed(6))];}
function bboxFromCoords(a,b){
  const lonA=normalizeLng(a[0]),lonB=normalizeLng(b[0]);
  const minLat=Math.min(clampLat(a[1]),clampLat(b[1]));
  const maxLat=Math.max(clampLat(a[1]),clampLat(b[1]));
  const west=Math.min(lonA,lonB),east=Math.max(lonA,lonB);
  return east-west>180?[east,minLat,west,maxLat]:[west,minLat,east,maxLat];
}
function bboxGeometry([minLon,minLat,maxLon,maxLat]){
  if(minLon<=maxLon)return {type:'Polygon',coordinates:[[
    [minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat],
  ]]};
  return {type:'MultiPolygon',coordinates:[
    [[[minLon,minLat],[180,minLat],[180,maxLat],[minLon,maxLat],[minLon,minLat]]],
    [[[-180,minLat],[maxLon,minLat],[maxLon,maxLat],[-180,maxLat],[-180,minLat]]],
  ]};
}
function polygonGeometry(){
  if(coverState.polygon.length<3)return null;
  const ring=coverState.polygon.map(cleanCoord);
  ring.push([...ring[0]]);
  return {type:'Polygon',coordinates:[ring]};
}
// rough query area (km^2), only used to guard against runaway covers
function coverQueryAreaKm2(active){
  let ring;
  if(active.kind==='bbox'){
    const [w,s,e,n]=active.bbox;
    const dLon=Math.abs(e-w>180?360-Math.abs(e-w):e-w);
    const midLat=(s+n)/2;
    return Math.abs(dLon*110.57*Math.cos(midLat*Math.PI/180))*Math.abs((n-s)*110.57);
  }
  ring=active.geometry.coordinates[0];
  let area=0,latSum=0;
  for(let i=0;i<ring.length-1;i++){
    area+=ring[i][0]*ring[i+1][1]-ring[i+1][0]*ring[i][1];
    latSum+=ring[i][1];
  }
  const meanLat=latSum/Math.max(1,ring.length-1);
  const km=110.57;
  return Math.abs(area/2)*km*km*Math.cos(meanLat*Math.PI/180);
}
function renderCoverQuery(){
  const features=[];
  const bbox=coverState.previewBbox||coverState.bbox;
  if(coverState.draw==='bbox'&&bbox){
    features.push({type:'Feature',properties:{kind:'bbox'},geometry:bboxGeometry(bbox)});
  }else if(coverState.draw==='polygon'&&coverState.polygon.length){
    const geom=polygonGeometry();
    if(geom)features.push({type:'Feature',properties:{kind:'polygon'},geometry:geom});
    else if(coverState.polygon.length>1)features.push({
      type:'Feature',
      properties:{kind:'line'},
      geometry:{type:'LineString',coordinates:coverState.polygon.map(cleanCoord)},
    });
    coverState.polygon.forEach((coord,index)=>features.push({
      type:'Feature',
      properties:{kind:'vertex',index},
      geometry:{type:'Point',coordinates:cleanCoord(coord)},
    }));
  }
  const source=coverMap.getSource('cover-query');
  if(source)source.setData(coverCollection(features));
}
function compactCoverCells(cells){
  let current=[...new Set(cells.map(cell=>BigInt(cell)).map(String))]
    .map(BigInt).sort(compareCoverBigInt);
  let changed=true;
  while(changed){
    changed=false;
    const groups=new Map();
    const next=[];
    for(const cell of current){
      let parent;
      try{parent=parent64(cell);}catch(e){next.push(cell);continue;}
      const key=parent.toString();
      if(!groups.has(key))groups.set(key,{parent,children:[]});
      groups.get(key).children.push(cell);
    }
    for(const group of groups.values()){
      if(group.children.length===4){next.push(group.parent);changed=true;}
      else next.push(...group.children);
    }
    current=[...new Set(next.map(String))].map(BigInt).sort(compareCoverBigInt);
  }
  return current;
}
function visibleCoverCells(){
  if(coverState.output==='full')return coverState.cells;
  return coverState.compacted;
}
function renderCoverCells(){
  const source=coverMap.getSource('cover-cells');
  if(source){
    const cells=visibleCoverCells();
    const features=cells.slice(0,COVER_RENDER_LIMIT)
      .map(cell=>cellFeature(cell,{precision:5}));
    source.setData(coverCollection(features));
  }
  const s2source=coverMap.getSource('cover-s2-cells');
  if(s2source){
    const showS2=coverState.compare==='s2';
    const s2cells=coverState.output==='full'?coverState.s2Cells:coverState.s2Compacted;
    const features=showS2
      ? s2cells.slice(0,COVER_RENDER_LIMIT).map(cell=>s2CellFeature(cell,{precision:5}))
      : [];
    s2source.setData(coverCollection(features));
  }
}
function formatCoverCells(cells){
  return coverState.format==='compact'
    ? cells.map(cell=>toCompact(cell))
    : cells.map(cell=>cell.toString());
}
function compactSavings(full,compacted){
  return full>0?(1-compacted/full)*100:0;
}
function renderCoverOutput(){
  const box=document.getElementById('cover-output-box');
  let text='';
  if(coverState.output==='ranges'){
    const rows=coverState.ranges.slice(0,COVER_RANGE_LIMIT)
      .map(([low,high])=>[low.toString(),high.toString()]);
    text=JSON.stringify(rows,null,2);
    if(coverState.ranges.length>COVER_RANGE_LIMIT)
      text+=`
... ${coverState.ranges.length-COVER_RANGE_LIMIT} more ranges`;
  }else{
    const cells=coverState.output==='compacted'?coverState.compacted:coverState.cells;
    const values=formatCoverCells(cells).slice(0,COVER_OUTPUT_LIMIT);
    text=JSON.stringify(values,null,2);
    if(cells.length>COVER_OUTPUT_LIMIT)
      text+=`
... ${cells.length-COVER_OUTPUT_LIMIT} more indexes`;
  }
  box.textContent=text;
  const rendered=Math.min(visibleCoverCells().length,COVER_RENDER_LIMIT);
  const renderNote=visibleCoverCells().length>COVER_RENDER_LIMIT
    ? ` · rendered first ${rendered.toLocaleString()}`:'';
  const t3Save=compactSavings(coverState.cells.length,coverState.compacted.length);
  let html=`<b>T3 L${coverState.level}</b>: ${coverState.cells.length.toLocaleString()} cells `+
    `&rarr; ${coverState.compacted.length.toLocaleString()} compacted `+
    `(${t3Save.toFixed(0)}% saved) · ${coverState.ranges.length.toLocaleString()} ranges · `+
    `${coverState.elapsedMs.toFixed(1)} ms${renderNote}`;
  if(coverState.compare==='s2'){
    const s2Save=compactSavings(coverState.s2Cells.length,coverState.s2Compacted.length);
    const t3c=coverState.compacted.length,s2c=coverState.s2Compacted.length;
    let verdict;
    if(t3c===s2c)verdict=`tie (${t3c.toLocaleString()} each)`;
    else{
      const smaller=t3c<s2c?'T3':'S2';
      const pct=(Math.abs(s2c-t3c)/Math.max(t3c,s2c))*100;
      verdict=`<b>${smaller} ${pct.toFixed(0)}% smaller</b>`;
    }
    html+=`<br><b style="color:#1c7c4a">S2 L${coverState.s2Level}</b>: `+
      `${coverState.s2Cells.length.toLocaleString()} cells &rarr; `+
      `${s2c.toLocaleString()} compacted (${s2Save.toFixed(0)}% saved)`+
      (coverState.s2Capped?' · capped':'')+
      `<br>final compacted size: T3 ${t3c.toLocaleString()} vs S2 ${s2c.toLocaleString()} cells `+
      `&mdash; ${verdict}`;
  }
  document.getElementById('cover-status').innerHTML=html;
}
function activeCoverGeometry(){
  if(coverState.draw==='bbox'&&coverState.bbox)return {kind:'bbox',bbox:coverState.bbox};
  if(coverState.draw==='polygon'&&coverState.polygon.length>=3)
    return {kind:'polygon',geometry:polygonGeometry()};
  return null;
}
function runCoverage(){
  const active=activeCoverGeometry();
  if(!active){
    document.getElementById('cover-status').textContent='Draw a bbox or a polygon with at least 3 vertices.';
    document.getElementById('cover-output-box').textContent='[]';
    coverState.cells=[];coverState.compacted=[];coverState.ranges=[];
    coverState.s2Cells=[];coverState.s2Compacted=[];
    renderCoverCells();
    return;
  }
  const estimate=coverQueryAreaKm2(active)/(25.5e6/Math.pow(4,coverState.level));
  if(estimate>COVER_CELL_CAP){
    document.getElementById('cover-status').innerHTML=
      `Area too large for L${coverState.level} (~${Math.round(estimate).toLocaleString()} cells, `+
      `cap ${COVER_CELL_CAP.toLocaleString()}). Draw a smaller shape or lower the level.`;
    document.getElementById('cover-output-box').textContent='[]';
    coverState.cells=[];coverState.compacted=[];coverState.ranges=[];
    coverState.s2Cells=[];coverState.s2Compacted=[];
    renderCoverCells();
    return;
  }
  const started=performance.now();
  try{
    coverState.cells=active.kind==='bbox'
      ? bboxCover(...active.bbox,coverState.level,{mode:coverState.mode})
      : polyfill(active.geometry,coverState.level,{mode:coverState.mode});
    coverState.compacted=compactCoverCells(coverState.cells);
    coverState.ranges=coverRanges(coverState.compacted);
    if(coverState.compare==='s2'){
      coverState.s2Level=s2LevelForT3(coverState.level);
      const query=active.kind==='bbox'
        ? {kind:'bbox',bbox:active.bbox}
        : {kind:'polygon',geometry:active.geometry};
      const result=s2Cover(query,coverState.s2Level,{mode:coverState.mode,cap:COVER_CELL_CAP});
      coverState.s2Cells=result.cells;
      coverState.s2Capped=result.capped;
      coverState.s2Compacted=s2Compact(result.cells);
    }else{
      coverState.s2Cells=[];coverState.s2Compacted=[];coverState.s2Capped=false;
    }
    coverState.elapsedMs=performance.now()-started;
    renderCoverCells();
    renderCoverOutput();
  }catch(err){
    console.error(err);
    document.getElementById('cover-status').textContent=err.message||String(err);
    document.getElementById('cover-output-box').textContent='[]';
  }
}
function updateCoverHint(){
  const hint=coverState.draw==='bbox'
    ? 'Drag on the map to draw a bbox.'
    : 'Click polygon vertices on the map; Finish closes the current shape.';
  document.getElementById('cover-hint').textContent=hint;
  coverMap.getCanvas().style.cursor=coverState.draw==='bbox'?'crosshair':'copy';
}
function wireCoverSeg(id,prop,cb){
  const seg=document.getElementById(id);
  seg.querySelectorAll('button').forEach(button=>{button.onclick=()=>{
    seg.querySelectorAll('button').forEach(other=>other.classList.remove('on'));
    button.classList.add('on');
    coverState[prop]=button.dataset.v;
    cb();
  };});
}

coverMap.on('load',()=>{
  coverMap.addSource('cover-cells',{type:'geojson',data:coverCollection()});
  coverMap.addSource('cover-s2-cells',{type:'geojson',data:coverCollection()});
  coverMap.addSource('cover-query',{type:'geojson',data:coverCollection()});
  coverMap.addLayer({id:'cover-s2-cells-fill',type:'fill',source:'cover-s2-cells',
    paint:{'fill-color':'#1c7c4a','fill-opacity':0.18}});
  coverMap.addLayer({id:'cover-s2-cells-line',type:'line',source:'cover-s2-cells',
    paint:{'line-color':'#13643a','line-width':1,'line-opacity':0.7}});
  coverMap.addLayer({id:'cover-cells-fill',type:'fill',source:'cover-cells',
    paint:{'fill-color':'#d94e2f','fill-opacity':0.24}});
  coverMap.addLayer({id:'cover-cells-line',type:'line',source:'cover-cells',
    paint:{'line-color':'#8b2f1f','line-width':1,'line-opacity':0.78}});
  coverMap.addLayer({id:'cover-query-fill',type:'fill',source:'cover-query',
    filter:['==',['geometry-type'],'Polygon'],
    paint:{'fill-color':'#2b6f9a','fill-opacity':0.16}});
  coverMap.addLayer({id:'cover-query-line',type:'line',source:'cover-query',
    paint:{'line-color':'#12384f','line-width':2.2,'line-opacity':0.95}});
  coverMap.addLayer({id:'cover-query-point',type:'circle',source:'cover-query',
    filter:['==',['geometry-type'],'Point'],
    paint:{'circle-radius':4,'circle-color':'#12384f','circle-stroke-color':'#fff',
      'circle-stroke-width':1.5}});
  renderCoverQuery();
  updateCoverHint();
  runCoverage();
});
coverMap.on('mousedown',e=>{
  if(coverState.draw!=='bbox'||e.originalEvent.button!==0)return;
  e.preventDefault();
  coverState.dragging=true;
  coverState.dragStart=[e.lngLat.lng,e.lngLat.lat];
  coverState.previewBbox=bboxFromCoords(coverState.dragStart,coverState.dragStart);
  coverMap.dragPan.disable();
  renderCoverQuery();
});
coverMap.on('mousemove',e=>{
  if(!coverState.dragging)return;
  coverState.previewBbox=bboxFromCoords(coverState.dragStart,[e.lngLat.lng,e.lngLat.lat]);
  renderCoverQuery();
});
coverMap.on('mouseup',e=>{
  if(!coverState.dragging)return;
  coverState.dragging=false;
  coverMap.dragPan.enable();
  const bbox=bboxFromCoords(coverState.dragStart,[e.lngLat.lng,e.lngLat.lat]);
  coverState.previewBbox=null;
  coverState.bbox=bbox;
  coverState.polygon=[];
  renderCoverQuery();
  runCoverage();
});
coverMap.on('click',e=>{
  if(coverState.draw!=='polygon'||coverState.dragging)return;
  coverState.polygon.push(cleanCoord([e.lngLat.lng,e.lngLat.lat]));
  coverState.bbox=null;
  renderCoverQuery();
  if(coverState.polygon.length>=3)runCoverage();
});
coverMap.on('dblclick',e=>{
  if(coverState.draw!=='polygon')return;
  e.preventDefault();
  if(coverState.polygon.length>=3)runCoverage();
});

wireCoverSeg('cover-draw','draw',()=>{
  updateCoverHint();
  renderCoverQuery();
  if(activeCoverGeometry())runCoverage();
});
wireCoverSeg('cover-compare','compare',runCoverage);
wireCoverSeg('cover-mode','mode',runCoverage);
wireCoverSeg('cover-output','output',()=>{
  renderCoverCells();
  renderCoverOutput();
});
wireCoverSeg('cover-format','format',renderCoverOutput);
document.getElementById('cover-level').addEventListener('input',e=>{
  coverState.level=Number(e.target.value);
  document.getElementById('cover-level-label').textContent=
    `L${coverState.level} ${COVER_LEVEL_LABELS[coverState.level]}`;
});
document.getElementById('cover-level').addEventListener('change',runCoverage);
document.getElementById('cover-run').addEventListener('click',runCoverage);
document.getElementById('cover-finish').addEventListener('click',()=>{
  if(coverState.draw==='polygon'&&coverState.polygon.length>=3)runCoverage();
});
document.getElementById('cover-clear').addEventListener('click',()=>{
  coverState.bbox=null;
  coverState.previewBbox=null;
  coverState.polygon=[];
  coverState.cells=[];
  coverState.compacted=[];
  coverState.ranges=[];
  coverState.s2Cells=[];
  coverState.s2Compacted=[];
  renderCoverQuery();
  renderCoverCells();
  document.getElementById('cover-status').textContent='Draw a bbox or polygon to run coverage.';
  document.getElementById('cover-output-box').textContent='[]';
});
window.trifoldCoverageDemo={state:coverState,runCoverage};
