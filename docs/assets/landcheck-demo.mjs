import {createMapDemo,escapeHTML} from './map-demo.mjs';
import {LandCheck,locateIndex,indexToCompact,indexToLonLatRing,samplePolyline} from '../sdk/landcheck.mjs';
const TFLS_B64=window.TRIFOLD_CORE;
const TFLR_URLS=['data/coastal_osm_L10.tflr','https://maps.goplex.ee/data/coastal_osm_L10.tflr'];
const NE_URLS=['data/ne_50m_land.geojson','https://maps.goplex.ee/data/ne_50m_land.geojson'];

const KIND_COLOR={land:'#22c55e',coast:'#f59e0b',sea:'#16277e'};
const EMPTY={type:'FeatureCollection',features:[]};
const CITIES=[
 ['Tallinn',24.7536,59.4370],['London',-0.1276,51.5072],['Tokyo',139.6917,35.6895],
 ['New York',-74.006,40.7128],['São Paulo',-46.6333,-23.5505],['Cairo',31.2357,30.0444],
 ['Sydney',151.2093,-33.8688],['Reykjavík',-21.9426,64.1466],['Singapore',103.8198,1.3521],
 ['Mid-Atlantic',-30,30],['South Pacific',-150,-30],['Mariana Trench',142.2,11.35],
 ['Sahara',10,25],['Himalaya',86.92,27.99],['Amazon',-62,-3],
 ['North Pole',0,89.99],['South Pole',0,-89.99],['Antarctica coast',161.69,-79.88],
 ['Fiji (antimeridian)',179.5,-16.6],['Bering Strait',-169.5,65.8],
 ['Venice lagoon',12.34,45.43],['Maldives',73.5,4.2],['Lake Victoria',33,-1],
 ['Gibraltar',-5.35,36.14],['Dover Strait',1.4,51],['Suez',32.55,29.95],
 ['Cape Horn',-67.27,-55.98],['Svalbard',15.6,78.2],['Galápagos',-90.97,-0.74],
 ['Easter Island',-109.35,-27.11]];

// dataset: embedded base64 -> bytes -> LandCheck
const t0=performance.now();
const bytes=Uint8Array.from(atob(TFLS_B64),c=>c.charCodeAt(0));
const lc=await LandCheck.fromBytes(bytes);
const loadMs=performance.now()-t0;
document.getElementById('loadnote').textContent=
  `Dataset: ${(bytes.length/1024).toFixed(0)} KB embedded in this page · `+
  `decoded + indexed in ${loadMs.toFixed(0)} ms · level ${lc.level} `+
  `(${lc.stats.runs.toLocaleString()} runs)`;

function randomPoints(n){
  // uniform on the sphere (not uniform in lat)
  const pts=new Array(n);
  for(let i=0;i<n;i++){
    const lon=Math.random()*360-180;
    const lat=Math.asin(2*Math.random()-1)*180/Math.PI;
    pts[i]=['',lon,lat];
  }
  return pts;
}

// classify: timing measured tightly around the lookup loop only
function classify(pts){
  const results=new Array(pts.length);
  const t0=performance.now();
  for(let i=0;i<pts.length;i++)results[i]=lc.check(pts[i][1],pts[i][2]);
  const ms=performance.now()-t0;
  return {results,ms};
}

let lastPts=null,lastLabel='';
function show(pts,label){
  lastPts=pts;lastLabel=label;
  label=escapeHTML(label);
  const {results,ms}=classify(pts);
  let nLand=0,nSea=0,nCoast=0,coastLand=0,nFlipped=0;
  const features=new Array(Math.min(pts.length,5000));
  for(let i=0;i<pts.length;i++){
    const r=results[i];
    if(r.land)nLand++;else nSea++;
    // a "flip": the OSM polygon test disagrees with the fraction-based guess
    const flipped=r.refined&&r.landFraction!=null&&
      ((r.landFraction>=0.5)!==r.land);
    if(r.kind==='coast'){nCoast++;if(r.land)coastLand++;if(flipped)nFlipped++;}
    if(i<5000)features[i]={type:'Feature',
      properties:{name:pts[i][0],kind:r.kind,land:r.land,conf:r.confidence,
        frac:r.landFraction,cell:r.cell,refined:r.refined,flipped,
        color:KIND_COLOR[r.kind]},
      geometry:{type:'Point',coordinates:[pts[i][1],pts[i][2]]}};
  }
  map.getSource('points').setData({type:'FeatureCollection',features:features.slice(0,5000)});
  if(pts.length>5000)demo.notify('Benchmark classified all points; displaying the first 5,000 points only.');
  const rate=pts.length/(ms/1000);
  const refineOn=document.getElementById('refinecb').checked;
  document.getElementById('perf').style.display='block';
  document.getElementById('perf').innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> lookups/second on this device<br>`+
    `${pts.length.toLocaleString()} points (${label}) classified in ${ms.toFixed(1)} ms `+
    `(${(ms*1000/pts.length).toFixed(2)} µs/point)`+
    `${refineOn?' · <b>OSM refinement on</b>':''}<br>`+
    `answers: <span style="color:${KIND_COLOR.land}">■</span> `+
    `<b>${nLand.toLocaleString()}</b> land · `+
    `<span style="color:${KIND_COLOR.sea}">■</span> <b>${nSea.toLocaleString()}</b> sea<br>`+
    `<span style="color:${KIND_COLOR.coast}">■</span> ${nCoast.toLocaleString()} in coastal `+
    `cells (${coastLand.toLocaleString()} → land, ${(nCoast-coastLand).toLocaleString()} → sea)`+
    `${refineOn?`<br><span style="color:#c2185b">◉</span> <b>${nFlipped.toLocaleString()}</b> `+
      `answer${nFlipped===1?'':'s'} flipped by the OSM polygon test `+
      `(highlighted on the map, click one)`:''}`;
}

function splitCsvLine(l){
  const out=[];let cur='',q=false;
  for(let i=0;i<l.length;i++){const ch=l[i];
    if(q){if(ch==='"'){if(l[i+1]==='"'){cur+='"';i++;}else q=false;}else cur+=ch;}
    else if(ch==='"')q=true;
    else if(ch===','||ch===';'||ch==='\t'){out.push(cur.trim());cur='';}
    else cur+=ch;}
  out.push(cur.trim());return out;
}
function parseCsv(text){
  const lines=text.split(/\r?\n/).filter(l=>l.trim());
  if(!lines.length)throw new Error('empty file');
  let lonCol=0,latCol=1,nameCol=2,start=0;
  const head=splitCsvLine(lines[0].toLowerCase());
  const latIdx=head.findIndex(h=>/^(lat|latitude|y)$/.test(h));
  const lonIdx=head.findIndex(h=>/^(lon|lng|long|longitude|x)$/.test(h));
  if(latIdx>=0&&lonIdx>=0){
    lonCol=lonIdx;latCol=latIdx;start=1;
    nameCol=head.findIndex(h=>/^(name|label|id|title)$/.test(h));
  }
  const pts=[];
  for(let i=start;i<lines.length;i++){
    const c=splitCsvLine(lines[i]);
    const lon=parseFloat(c[lonCol]),lat=parseFloat(c[latCol]);
    if(!isFinite(lon)||!isFinite(lat))continue;
    if(lon<-180||lon>180||lat<-90||lat>90)continue;
    pts.push([nameCol>=0&&c[nameCol]?c[nameCol]:'',lon,lat]);
  }
  if(!pts.length)throw new Error('no valid lon,lat rows found');
  return pts;
}
function parseGeojson(text){
  const gj=JSON.parse(text);
  const features=gj.type==='FeatureCollection'?gj.features:
    gj.type==='Feature'?[gj]:null;
  if(!features)throw new Error('expected a GeoJSON FeatureCollection');
  const pts=[];
  for(const f of features){
    if(!f.geometry)continue;
    const geoms=f.geometry.type==='Point'?[f.geometry.coordinates]:
      f.geometry.type==='MultiPoint'?f.geometry.coordinates:[];
    for(const [lon,lat] of geoms)
      if(isFinite(lon)&&isFinite(lat)&&lon>=-180&&lon<=180&&lat>=-90&&lat<=90)
        pts.push([(f.properties&&(f.properties.name||f.properties.label))||'',lon,lat]);
  }
  if(!pts.length)throw new Error('no Point features found');
  return pts;
}

const demo=createMapDemo({container:'map',initialView:{center:[15,30],zoom:1.4},adapter:{
  id:'landcheck',layers:['coastline','coast-zones','cell-fill','cell-line','pts','route-line','route-verts'],
  presets:CITIES.slice(0,10).map(c=>({name:c[0],center:[c[1],c[2]],zoom:10})),
  queryPoint:([lon,lat])=>{drawCell(lon,lat);return lc.check(lon,lat);},
  queryBatch:([lon,lat])=>lc.check(lon,lat),pointColor:r=>KIND_COLOR[r.kind],
  acceptClick:()=>mode!=='route',
  clearSelection:()=>map.getSource('cell')?.setData(EMPTY)
}});
const map=demo.map;
window.__landcheck={map,lc,demo};

// triangle ring (closed, GeoJSON order) of the level-10 cell at a point
function cellRingAt(lon,lat){
  const index=locateIndex(lon,lat,lc.level);
  const ring=indexToLonLatRing(index,lc.level).map(p=>[p[0],p[1]]);
  ring.push(ring[0]);
  return {index,ring};
}
function drawCell(lon,lat){
  const {index,ring}=cellRingAt(lon,lat);
  map.getSource('cell').setData({type:'Feature',properties:{},
    geometry:{type:'Polygon',coordinates:[ring]}});
  return index;
}
function describe(lon,lat,name){
  const r=lc.check(lon,lat);
  let html=name?`<b>${name}</b><br>`:'';
  html+=`<b style="color:${KIND_COLOR[r.kind]}">${r.land?'LAND':'SEA'}</b>`+
    ` · kind <b>${r.kind}</b><br>confidence ${r.confidence.toFixed(3)}`;
  if(r.landFraction!=null)html+=` · land fraction ${r.landFraction.toFixed(3)}`;
  if(r.refined){
    const guess=r.landFraction!=null&&r.landFraction>=0.5;
    html+=(r.landFraction!=null&&guess!==r.land)
      ?`<br><b style="color:#c2185b">flipped by OSM polygon test</b>: the bundled `+
       `fraction (${r.landFraction.toFixed(2)}) would have guessed `+
       `<b>${guess?'LAND':'SEA'}</b>`
      :`<br>decided by OSM polygon test (agrees with the fraction guess)`;
  }
  // sea cells are not stored in the dataset; compute the address on demand
  const cell=r.cell??indexToCompact(locateIndex(lon,lat,lc.level),lc.level);
  html+=`<br>cell <span style="font-family:monospace">${cell}</span>`+
    `${r.cell?'':' <span style="color:#777">(empty = sea)</span>'}`;
  html+=`<br><span style="color:#777;font-size:11px">${lon.toFixed(4)}, ${lat.toFixed(4)}</span>`;
  return html;
}

map.on('load',()=>{
  map.addSource('coast',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'coastline',type:'line',source:'coast',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':'#7c4a03','line-width':1.4,'line-opacity':0.9}});
  map.addSource('coastzones',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'coast-zones',type:'fill',source:'coastzones',
    paint:{'fill-color':KIND_COLOR.land,'fill-opacity':0.45,'fill-antialias':false}});
  map.addSource('cell',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'cell-fill',type:'fill',source:'cell',
    paint:{'fill-color':'#d94e2f','fill-opacity':0.12}});
  map.addLayer({id:'cell-line',type:'line',source:'cell',
    paint:{'line-color':'#d94e2f','line-width':2}});
  map.addSource('points',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  const flipped=['boolean',['get','flipped'],false];
  map.addLayer({id:'pts',type:'circle',source:'points',paint:{
    'circle-color':['get','color'],
    'circle-radius':['interpolate',['linear'],['zoom'],
      0,['case',flipped,4,2.2],
      4,['case',flipped,5.5,3.5],
      8,['case',flipped,7,5]],
    'circle-opacity':0.85,
    'circle-stroke-width':['case',flipped,2.2,0.6],
    'circle-stroke-color':['case',flipped,'#c2185b','rgba(0,0,0,.4)']}});
  // route (polyline) layers: one coloured line feature per classified segment
  map.addSource('route',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-line',type:'line',source:'route',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':['get','color'],'line-width':5,'line-opacity':0.9}});
  map.addSource('routeverts',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-verts',type:'circle',source:'routeverts',
    paint:{'circle-color':'#111','circle-radius':4.5,
      'circle-stroke-width':2,'circle-stroke-color':'#fff'}});
  map.on('click',e=>{
    let lon=e.lngLat.lng,lat=e.lngLat.lat;
    lon=((lon+180)%360+360)%360-180;
    lat=Math.max(-90,Math.min(90,lat));
    // route draw mode: each click drops a vertex
    if(mode==='route'&&drawing){addVertex(lon,lat);return;}
    // route segment click: show the segment's classification
    const seg=map.queryRenderedFeatures(e.point,{layers:['route-line']});
    if(mode==='route'&&seg.length){
      const p=seg[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
        `<b style="color:${p.color}">${p.land==='true'||p.land===true?'LAND':'SEA'}</b>`+
        ` · kind <b>${p.kind}</b><br>${(+p.distanceKm).toFixed(1)} km `+
        `(${(100*p.fraction).toFixed(1)}% of route)`).addTo(map);
      return;
    }
    // clicks on a classified point are handled by the 'pts' handler below
    if(map.queryRenderedFeatures(e.point,{layers:['pts']}).length)return;

  });
  map.on('click','pts',e=>{
    const p=e.features[0].properties;
    const [lon,lat]=e.features[0].geometry.coordinates;
    demo.select(lon,lat);
  });
  map.on('mouseenter','pts',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','pts',()=>map.getCanvas().style.cursor='');
  map.on('moveend',()=>{if(coastcb.checked&&coastMode()==='osm')updateCoastline();});
  show(CITIES.map(c=>[c[0],c[1],c[2]]),'world cities + tricky spots');
});

document.getElementById('b-cities').onclick=()=>show(CITIES.map(c=>[c[0],c[1],c[2]]),'world cities + tricky spots');
document.getElementById('b-r1').onclick=()=>show(randomPoints(1000),'uniform random on sphere');
document.getElementById('b-r10').onclick=()=>show(randomPoints(10000),'uniform random on sphere');
document.getElementById('b-r100').onclick=()=>show(randomPoints(100000),'uniform random on sphere');
// --- source coastline debug layer (NE polygons / OSM-from-TFLR) ---
const coastcb=document.getElementById('coastcb');
const coastnote=document.getElementById('coastnote');
const coastsrc=document.getElementById('coastsrc');
let neGeojson=null;        // fetched NE land polygons, cached
let cellBoxes=null;        // [index,minx,miny,maxx,maxy] per refined cell, lazy
function coastMode(){return (document.getElementById('refinecb').checked&&refineCells)?'osm':'ne';}

function buildCellBoxes(){
  cellBoxes=[];
  for(const [index,entry] of refineCells){
    if(entry===0)continue;  // all-sea: nothing to fill (all-land 1 fills its triangle)
    const ring=indexToLonLatRing(index,lc.level);
    const lons=ring.map(p=>p[0]),lats=ring.map(p=>p[1]);
    cellBoxes.push([index,Math.min(...lons),Math.min(...lats),
                    Math.max(...lons),Math.max(...lats)]);
  }
}
// even-odd ray cast in the cell-local quantized grid (flat [x0,y0,x1,y1,...])
function pointInRingQ(px,py,pts){
  const n=pts.length/2;let inside=false;
  for(let i=0,j=n-1;i<n;j=i++){
    const xi=pts[2*i],yi=pts[2*i+1],xj=pts[2*j],yj=pts[2*j+1];
    if(((yi>py)!==(yj>py))&&(px<(xj-xi)*(py-yi)/((yj-yi)||1e-9)+xi))inside=!inside;
  }
  return inside;
}
function osmCoastZones(){
  if(!cellBoxes)buildCellBoxes();
  const b=map.getBounds();
  const w=b.getWest(),e=b.getEast(),s=b.getSouth(),n=b.getNorth();
  const feats=[];let nverts=0;
  for(const [index,minx,miny,maxx,maxy] of cellBoxes){
    if(maxy<s||miny>n)continue;
    let hit=false;
    for(const off of [-360,0,360]){if(maxx+off>=w&&minx+off<=e){hit=true;break;}}
    if(!hit)continue;
    const sx=(maxx-minx)/65535,sy=(maxy-miny)/65535;
    const entry=refineCells.get(index);
    if(typeof entry==='number'){   // 1 = whole cell is land: fill the triangle
      if(entry===1){
        const tri=indexToLonLatRing(index,lc.level).map(p=>[p[0],p[1]]);
        tri.push(tri[0]);
        feats.push({type:'Feature',properties:{},
          geometry:{type:'Polygon',coordinates:[tri]}});
        nverts+=3;
      }
      if(nverts>120000)return null;
      continue;
    }
    // fill the land part of this coastal cell. The dataset's rings are even-odd
    // (inside = land), so sort by area and nest a ring inside a larger one as a
    // hole (a lake/inlet); disjoint rings become separate polygons. Triangle-edge
    // segments need no filtering here — they are interior to the fill.
    const decoded=entry.map(pts=>{
      const m=pts.length/2,ll=new Array(m+1);
      let a=0;
      for(let i=0;i<m;i++){
        ll[i]=[minx+pts[2*i]*sx,miny+pts[2*i+1]*sy];
        const j=(i+1)%m;a+=pts[2*i]*pts[2*j+1]-pts[2*j]*pts[2*i+1];
      }
      ll[m]=ll[0];
      nverts+=m;
      return {ll,area:Math.abs(a)/2,q:pts};
    }).sort((p,q)=>q.area-p.area);
    const polys=[];
    for(const d of decoded){
      let host=null;
      for(const P of polys)if(pointInRingQ(d.q[0],d.q[1],P.q)){host=P;break;}
      if(host)host.coords.push(d.ll);
      else polys.push({coords:[d.ll],q:d.q});
    }
    for(const P of polys)feats.push({type:'Feature',properties:{},
      geometry:{type:'Polygon',coordinates:P.coords}});
    if(nverts>120000)return null;  // too much detail for this view
  }
  return feats;
}
async function updateCoastline(){
  if(!coastcb.checked){
    map.getSource('coast').setData({type:'FeatureCollection',features:[]});
    map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
    return;
  }
  if(coastMode()==='ne'){
    coastsrc.textContent='NE';
    map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
    if(!neGeojson){
      coastnote.textContent='Downloading Natural Earth land polygons…';
      for(const url of NE_URLS){
        try{
          const res=await fetch(url);
          if(!res.ok)continue;
          neGeojson=await res.json();
          break;
        }catch(err){console.warn(url,err);}
      }
      if(!neGeojson){
        coastnote.textContent='Could not download the NE land polygons.';
        coastcb.checked=false;return;
      }
    }
    map.getSource('coast').setData(neGeojson);
    coastnote.textContent='Brown line: Natural Earth 1:50m land outlines, the base dataset '+
      'the grid was classified against. Click anywhere for the cell triangle.';
  }else{
    coastsrc.textContent='OSM';
    map.getSource('coast').setData({type:'FeatureCollection',features:[]});
    const feats=osmCoastZones();
    if(feats===null){
      map.getSource('coastzones').setData({type:'FeatureCollection',features:[]});
      coastnote.textContent='OSM refinement geometry: zoom in further to draw it.';
      return;
    }
    map.getSource('coastzones').setData({type:'FeatureCollection',features:feats});
    coastnote.textContent=`Green fill: ${feats.length.toLocaleString()} OSM land zone(s) `+
      `in view — the clipped land area of each coastal cell, exactly the geometry `+
      `the refined lookup tests against.`;
  }
}
coastcb.onchange=updateCoastline;

// --- OSM coastal refinement toggle ---
let refineCells=null;   // decoded TFLR, kept so the checkbox can flip freely
const refinecb=document.getElementById('refinecb');
const refinenote=document.getElementById('refinenote');
refinecb.onchange=async()=>{
  if(refinecb.checked&&!refineCells){
    refinecb.disabled=true;
    refinenote.textContent='Downloading OSM refinement layer…';
    let loaded=false;
    for(const url of TFLR_URLS){
      try{
        const res=await fetch(url);
        if(!res.ok)continue;
        const buf=await res.arrayBuffer();
        refinenote.textContent=`Decoding ${(buf.byteLength/1e6).toFixed(1)} MB…`;
        await lc.loadRefinement(new Uint8Array(buf));
        refineCells=lc._refine;
        loaded=true;
        refinenote.textContent=`Loaded: ${refineCells.size.toLocaleString()} covered cells with `+
          `OSM polygon detail. Covered answers are now near-exact (confidence 0.99).`;
        break;
      }catch(err){console.warn(url,err);}
    }
    refinecb.disabled=false;
    if(!loaded){
      refinecb.checked=false;
      refinenote.textContent='Could not download the refinement layer, so the bundled fractions stay in use.';
      return;
    }
  }else{
    lc._refine=refinecb.checked?refineCells:null;
    refinenote.textContent=refinecb.checked
      ?'OSM polygon test active in covered coastline cells.'
      :'Off: coastal answers use the bundled land-area fraction.';
  }
  if(lastPts)show(lastPts,lastLabel);   // re-classify so the effect is visible
  demo.refreshSelection();
  updateCoastline();                    // coastline source follows refinement
};
function parseGeojsonLine(text){
  const gj=JSON.parse(text);
  const feats=gj.type==='FeatureCollection'?gj.features:gj.type==='Feature'?[gj]:[gj];
  for(const f of feats){
    const g=f.geometry||f;
    if(g.type==='LineString')return g.coordinates.map(c=>[c[0],c[1]]);
    if(g.type==='MultiLineString')return g.coordinates[0].map(c=>[c[0],c[1]]);
  }
  throw new Error('no LineString found');
}
document.getElementById('fileinput').onchange=async e=>{
  const file=e.target.files[0];
  if(!file)return;
  if(file.size>2*1024*1024){document.getElementById('droperr').textContent='File exceeds 2 MB limit.';e.target.value='';return;}
  document.getElementById('droperr').textContent='';
  try{
    const text=await file.text();
    const isJson=text.trimStart().startsWith('{');
    if(mode==='route'){
      const coords=isJson?parseGeojsonLine(text)
        :parseCsv(text).map(p=>[p[1],p[2]]);
      if(coords.length<2)throw new Error('need at least two vertices');
      if(coords.length>100000)throw new Error('too many vertices (max 100k)');
      loadRoute(coords);
    }else{
      const pts=isJson?parseGeojson(text):parseCsv(text);
      if(pts.length>5000)throw new Error('too many points (max 5,000)');
      show(pts,file.name);
    }
  }catch(err){
    document.getElementById('droperr').textContent=`Could not read ${file.name}: ${err.message}`;
  }
  e.target.value='';
};


// ---- Route (polyline) mode ----
let mode='points',drawing=false,routePts=[];
const perf=document.getElementById('perf');
const routenote=document.getElementById('routenote');
const bDraw=document.getElementById('b-draw');
const ROUTES={
  eu:[[24.7536,59.4370],[18.0686,59.3293]],          // Tallinn -> Stockholm, over the Baltic
  med:[[2.1734,41.3851],[3.0588,36.7538]],            // Barcelona -> Algiers, over the Med
  long:[[-9.1393,38.7223],[2.3522,48.8566],[31.2357,30.0444]]};  // Lisbon -> Paris -> Cairo
function stepKm(){return parseFloat(document.querySelector('#seg-step .on').dataset.v);}

function classifyRoute(){
  const coords=routePts.slice();
  if(coords.length<2){routenote.textContent='Add at least two points.';return;}
  const step=stepKm();
  const t0=performance.now();
  const res=lc.checkPolyline(coords,{stepKm:step});   // the real library call, timed
  const ms=performance.now()-t0;
  // colour the line: re-sample and group consecutive samples sharing land+kind.
  // segments join at the midpoint between samples (no gaps); stats come from
  // res.segments, whose order matches this grouping one-to-one.
  const {samples}=samplePolyline(coords,step,'uniform');
  const cls=samples.map(s=>lc.check(s[0],s[1]));
  const mid=(p,q)=>[(p[0]+q[0])/2,(p[1]+q[1])/2];
  const feats=[];let i=0,k=0;
  while(i<samples.length){
    const a=cls[i];let j=i;
    while(j+1<samples.length&&cls[j+1].land===a.land)j++;
    const line=samples.slice(i,j+1);
    if(i>0)line.unshift(mid(samples[i-1],samples[i]));
    if(j<samples.length-1)line.push(mid(samples[j],samples[j+1]));
    const seg=res.segments[k++]||{};
    feats.push({type:'Feature',
      properties:{color:KIND_COLOR[a.kind],kind:a.kind,land:a.land,
        distanceKm:seg.distanceKm,fraction:seg.fraction},
      geometry:{type:'LineString',coordinates:line}});
    i=j+1;
  }
  map.getSource('route').setData({type:'FeatureCollection',features:feats});
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:coords.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  map.getSource('points').setData(EMPTY);
  const rate=samples.length/(ms/1000);
  const refineOn=document.getElementById('refinecb').checked;
  let rows='';
  for(const s of res.segments)
    rows+=`<span style="color:${KIND_COLOR[s.kind]}">■</span> `+
      `<b>${s.kind}</b> · ${s.distanceKm.toFixed(0)} km (${(100*s.fraction).toFixed(0)}%)<br>`;
  perf.style.display='block';
  perf.innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> samples/second on this device<br>`+
    `${samples.length.toLocaleString()} samples · `+
    `${res.totalDistanceKm.toFixed(0)} km total · `+
    `${res.segments.length} segment${res.segments.length===1?'':'s'} (step ${step} km)`+
    `${refineOn?' · <b>OSM refinement on</b>':''}<br>`+rows;
  routenote.textContent=`${coords.length} vertices · classified in ${ms.toFixed(1)} ms.`;
}
function addVertex(lon,lat){
  routePts.push([lon,lat]);
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:routePts.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  if(routePts.length>=2)
    map.getSource('route').setData({type:'FeatureCollection',
      features:[{type:'Feature',properties:{color:'#888',kind:'',land:false},
        geometry:{type:'LineString',coordinates:routePts.slice()}}]});
  routenote.textContent=`${routePts.length} point(s) — click to add more, Finish to classify.`;
}
function startDraw(){
  drawing=true;routePts=[];
  map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
  perf.style.display='none';bDraw.textContent='✓ Finish';bDraw.classList.add('on');
  map.getCanvas().style.cursor='crosshair';
  routenote.textContent='Click the map to drop route points; click Finish to classify.';
}
function endDraw(){
  drawing=false;bDraw.textContent='✏️ Draw on map';bDraw.classList.remove('on');
  map.getCanvas().style.cursor='';
}
bDraw.onclick=()=>{
  if(drawing){endDraw();if(routePts.length>=2)classifyRoute();
    else routenote.textContent='Need at least two points — pick an example or draw again.';}
  else startDraw();
};
document.getElementById('b-route-clear').onclick=()=>{
  endDraw();routePts=[];map.getSource('route').setData(EMPTY);
  map.getSource('routeverts').setData(EMPTY);perf.style.display='none';
  routenote.textContent='Pick an example, or hit Draw on map.';
};
function loadRoute(coords){
  endDraw();routePts=coords.map(c=>c.slice());classifyRoute();
  const b=new maplibregl.LngLatBounds();for(const c of routePts)b.extend(c);
  map.fitBounds(b,{padding:90,duration:600});
}
document.getElementById('b-route-eu').onclick=()=>loadRoute(ROUTES.eu);
document.getElementById('b-route-med').onclick=()=>loadRoute(ROUTES.med);
document.getElementById('b-route-asia').onclick=()=>loadRoute(ROUTES.long);
document.querySelectorAll('#seg-step button').forEach(b=>{b.onclick=()=>{
  document.querySelectorAll('#seg-step button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  if(mode==='route'&&routePts.length>=2)classifyRoute();
};});
function setMode(m){
  mode=m;
  document.querySelectorAll('#seg-mode button').forEach(x=>x.classList.toggle('on',x.dataset.v===m));
  document.getElementById('row-points').style.display=m==='points'?'':'none';
  document.getElementById('row-route').style.display=m==='route'?'':'none';
  perf.style.display='none';
  if(m==='points'){
    endDraw();routePts=[];
    map.getSource('route').setData(EMPTY);map.getSource('routeverts').setData(EMPTY);
    if(lastPts)show(lastPts,lastLabel);
  }else{
    map.getSource('points').setData(EMPTY);map.getSource('cell').setData(EMPTY);
    routenote.textContent='Pick an example, or hit Draw on map.';
  }
}
document.querySelectorAll('#seg-mode button').forEach(b=>{b.onclick=()=>setMode(b.dataset.v);});

window.__landcheck={map,lc,demo};   // console/debug handle
