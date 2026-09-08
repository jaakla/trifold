import {createMapDemo,escapeHTML} from './map-demo.mjs';
import {CountryCheck,locateIndex,indexToCompact,indexToLonLatRing,samplePolyline} from '../sdk/countrycheck.mjs';
const TFCS_B64=window.TRIFOLD_CORE;
const TFCR_URLS=['data/borders_L10.tfcr','__TFCR_URL__'];

const NONE_COLOR='#8a93a0';
const EMPTY={type:'FeatureCollection',features:[]};
// deterministic, well-spread hue per country id (golden-angle)
function countryColor(cid){
  if(cid==null||cid<0)return NONE_COLOR;
  const h=(cid*137.508)%360;
  const s=cid%2?52:64, l=cid%3?46:56;
  return `hsl(${h.toFixed(1)},${s}%,${l}%)`;
}
const CITIES=[
 ['Tallinn',24.7536,59.4370],['Helsinki',24.9384,60.1699],
 ['St Petersburg',30.3141,59.9386],['London',-0.1276,51.5072],['Paris',2.3522,48.8566],
 ['Vatican City',12.4534,41.9029],['San Marino',12.4578,43.9424],['Berlin',13.405,52.52],
 ['Kaliningrad (RU exclave)',20.5,54.71],['Singapore',103.8198,1.3521],
 ['Johor Bahru (MY)',103.76,1.49],['Hong Kong',114.17,22.32],['Tokyo',139.6917,35.6895],
 ['New York',-74.006,40.7128],['Point Roberts (US exclave)',-123.06,48.98],
 ['Mexico City',-99.1332,19.4326],['Brasília',-47.9292,-15.7801],
 ['Cape Town',18.4241,-33.9249],['Maseru (Lesotho)',27.4869,-29.3142],
 ['Cairo',31.2357,30.0444],['Jerusalem',35.2137,31.7683],['Istanbul',28.9784,41.0082],
 ['Nicosia (CY)',33.3623,35.1656],['N. Nicosia (XNC)',33.3623,35.1923],
 ['Pristina (Kosovo XKO)',21.1655,42.6629],['Caspian Sea (XCA)',51.0,42.0],
 ['Western Sahara',-13.0,24.5],['Simferopol (Crimea)',34.1,44.95],
 ['Gibraltar',-5.3536,36.1408],['Reykjavík',-21.9426,64.1466],['Sydney',151.2093,-33.8688],
 ['Gulf of Finland (EST coastal water)',24.75,59.50],
 ['Mid-Atlantic (ocean)',-30,30],['South Pacific (ocean)',-150,-30],
 ['North Pole (ocean)',0,89.5]];

// dataset: embedded base64 -> bytes -> CountryCheck
const t0=performance.now();
const bytes=Uint8Array.from(atob(TFCS_B64),c=>c.charCodeAt(0));
const cc=await CountryCheck.fromBytes(bytes);
const loadMs=performance.now()-t0;
const codeToCid=new Map(cc.countries.map((c,i)=>[c.code,i]));
document.getElementById('loadnote').textContent=
  `Dataset: ${(bytes.length/1024).toFixed(0)} KB embedded in this page · `+
  `decoded + indexed in ${loadMs.toFixed(0)} ms · level ${cc.level} · `+
  `${cc.countries.length} countries · ${cc.stats.runs.toLocaleString()} runs`;

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
  for(let i=0;i<pts.length;i++)results[i]=cc.check(pts[i][1],pts[i][2]);
  const ms=performance.now()-t0;
  // flips: only computed when refinement is on (cheap second pass, untimed)
  let base=null;
  if(cc._refine){
    const keep=cc._refine; cc._refine=null;
    base=new Array(pts.length);
    for(let i=0;i<pts.length;i++)base[i]=cc.country(pts[i][1],pts[i][2]);
    cc._refine=keep;
  }
  return {results,ms,base};
}

let lastPts=null,lastLabel='';
function show(pts,label){
  lastPts=pts;lastLabel=label;
  label=escapeHTML(label);
  const {results,ms,base}=classify(pts);
  let nCountry=0,nBorder=0,nNone=0,nFlipped=0;
  const seen=new Set();
  const features=new Array(Math.min(pts.length,5000));
  for(let i=0;i<pts.length;i++){
    const r=results[i];
    if(r.kind==='none')nNone++;else if(r.kind==='border')nBorder++;else nCountry++;
    if(r.country)seen.add(r.country);
    const flipped=base!=null&&base[i]!==r.country;
    if(flipped)nFlipped++;
    const cid=r.country==null?-1:codeToCid.get(r.country);
    if(i<5000)features[i]={type:'Feature',
      properties:{name:pts[i][0],country:r.country,iso2:r.iso2,cname:r.name,
        kind:r.kind,conf:r.confidence,share:r.share,cell:r.cell,refined:r.refined,
        border:r.kind==='border',flipped,color:countryColor(cid)},
      geometry:{type:'Point',coordinates:[pts[i][1],pts[i][2]]}};
  }
  map.getSource('points').setData({type:'FeatureCollection',features:features.slice(0,5000)});
  if(pts.length>5000)demo.notify('Benchmark classified all points; displaying the first 5,000 points only.');
  const rate=pts.length/(ms/1000);
  const refineOn=!!cc._refine;
  document.getElementById('perf').style.display='block';
  document.getElementById('perf').innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> lookups/second on this device<br>`+
    `${pts.length.toLocaleString()} points (${label}) classified in ${ms.toFixed(1)} ms `+
    `(${(ms*1000/pts.length).toFixed(2)} µs/point)`+
    `${refineOn?' · <b>refinement on</b>':''}<br>`+
    `answers: <b>${nCountry.toLocaleString()}</b> interior-country · `+
    `<b>${nBorder.toLocaleString()}</b> border · `+
    `<b>${nNone.toLocaleString()}</b> no country<br>`+
    `<b>${seen.size.toLocaleString()}</b> distinct countries hit`+
    `${refineOn?`<br><span style="color:#c2185b">◉</span> <b>${nFlipped.toLocaleString()}</b> `+
      `answer${nFlipped===1?'':'s'} changed by the polygon test `+
      `(ringed on the map, click one)`:''}`;
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
  id:'countrycheck',layers:['borderzones','borderlines','cell-fill','cell-line','pts','route-line','route-verts'],
  presets:CITIES.slice(0,10).map(c=>({name:c[0],center:[c[1],c[2]],zoom:10})),
  queryPoint:([lon,lat])=>{drawCell(lon,lat);return cc.check(lon,lat);},
  queryBatch:([lon,lat])=>cc.check(lon,lat),pointColor:r=>countryColor(codeToCid.get(r.country)),
  acceptClick:()=>mode!=='route',
  clearSelection:()=>map.getSource('cell')?.setData(EMPTY)
}});
const map=demo.map;
window.__countrycheck={map,cc,demo};

// triangle ring (closed, GeoJSON order) of the level-10 cell at a point
function cellRingAt(lon,lat){
  const index=locateIndex(lon,lat,cc.level);
  const ring=indexToLonLatRing(index,cc.level).map(p=>[p[0],p[1]]);
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
  const r=cc.check(lon,lat);
  const cid=r.country==null?-1:codeToCid.get(r.country);
  let html=name?`<b>${name}</b><br>`:'';
  if(r.country!=null){
    html+=`<b style="color:${countryColor(cid)}">${r.country}</b>`+
      `${r.iso2?` (${r.iso2})`:''} — ${r.name||''}<br>`;
  }else{
    html+=`<b style="color:${NONE_COLOR}">no country</b> (international waters)<br>`;
  }
  html+=`kind <b>${r.kind}</b> · confidence ${r.confidence.toFixed(3)}`;
  if(r.share!=null)html+=` · area share ${Number(r.share).toFixed(3)}`;
  if(r.refined)html+=`<br><span style="color:#6d4ca8">decided by exact polygon test</span>`;
  const cell=r.cell??indexToCompact(locateIndex(lon,lat,cc.level),cc.level);
  html+=`<br>cell <span style="font-family:monospace">${cell}</span>`+
    `${r.cell?'':' <span style="color:#777">(empty = open ocean)</span>'}`;
  html+=`<br><span style="color:#777;font-size:11px">${lon.toFixed(4)}, ${lat.toFixed(4)}</span>`;
  return html;
}

map.on('load',()=>{
  map.addSource('borders',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'borderzones',type:'fill',source:'borders',
    paint:{'fill-color':['get','color'],'fill-opacity':0.5,'fill-antialias':false}});
  map.addSource('cell',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  map.addLayer({id:'cell-fill',type:'fill',source:'cell',
    paint:{'fill-color':'#6d4ca8','fill-opacity':0.12}});
  map.addLayer({id:'cell-line',type:'line',source:'cell',
    paint:{'line-color':'#6d4ca8','line-width':2}});
  map.addSource('points',{type:'geojson',
    data:{type:'FeatureCollection',features:[]}});
  const flipped=['boolean',['get','flipped'],false];
  const border=['boolean',['get','border'],false];
  map.addLayer({id:'pts',type:'circle',source:'points',paint:{
    'circle-color':['get','color'],
    'circle-radius':['interpolate',['linear'],['zoom'],
      0,['case',flipped,4,2.2],
      4,['case',flipped,5.5,3.5],
      8,['case',flipped,7,5]],
    'circle-opacity':0.85,
    'circle-stroke-width':['case',flipped,2.2,border,1.4,0.6],
    'circle-stroke-color':['case',flipped,'#c2185b',border,'#1c2733','rgba(0,0,0,.4)']}});
  // route (polyline) layers: one coloured line feature per classified segment
  map.addSource('route',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-line',type:'line',source:'route',
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':['get','color'],'line-width':5,'line-opacity':0.92}});
  map.addSource('routeverts',{type:'geojson',data:EMPTY});
  map.addLayer({id:'route-verts',type:'circle',source:'routeverts',
    paint:{'circle-color':'#111','circle-radius':4.5,
      'circle-stroke-width':2,'circle-stroke-color':'#fff'}});
  map.on('click',e=>{
    let lon=e.lngLat.lng,lat=e.lngLat.lat;
    lon=((lon+180)%360+360)%360-180;
    lat=Math.max(-90,Math.min(90,lat));
    if(mode==='route'&&drawing){addVertex(lon,lat);return;}
    const seg=map.queryRenderedFeatures(e.point,{layers:['route-line']});
    if(mode==='route'&&seg.length){
      const p=seg[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
        `<b>${p.cname||p.country||'no country'}</b>`+
        `${p.iso2?' ('+p.iso2+')':''} · kind <b>${p.kind}</b><br>`+
        `${(+p.distanceKm).toFixed(1)} km (${(100*p.fraction).toFixed(1)}% of route)`).addTo(map);
      return;
    }
    if(map.queryRenderedFeatures(e.point,{layers:['pts']}).length)return;

  });
  map.on('click','pts',e=>{
    const p=e.features[0].properties;
    const [lon,lat]=e.features[0].geometry.coordinates;
    demo.select(lon,lat);
  });
  map.on('mouseenter','pts',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','pts',()=>map.getCanvas().style.cursor='');
  map.on('moveend',()=>{if(bordercb.checked)updateBorders();});
  show(CITIES.map(c=>[c[0],c[1],c[2]]),'capitals + tricky spots');
});

document.getElementById('b-cities').onclick=()=>show(CITIES.map(c=>[c[0],c[1],c[2]]),'capitals + tricky spots');
document.getElementById('b-r1').onclick=()=>show(randomPoints(1000),'uniform random on sphere');
document.getElementById('b-r10').onclick=()=>show(randomPoints(10000),'uniform random on sphere');
document.getElementById('b-r100').onclick=()=>show(randomPoints(100000),'uniform random on sphere');

// --- source border debug layer (zone rings decoded from TFCR) ---
const bordercb=document.getElementById('bordercb');
const bordernote=document.getElementById('bordernote');
let cellBoxes=null;   // [index,minx,miny,maxx,maxy] per refined cell, lazy
function buildCellBoxes(){
  cellBoxes=[];
  for(const [index,zones] of cc._refine){
    let hasRings=false;
    for(const [cid,rings] of zones)if(rings!==null){hasRings=true;break;}
    if(!hasRings)continue;   // whole-cell zones: nothing to draw
    const ring=indexToLonLatRing(index,cc.level);
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
function borderFeatures(){
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
    // fill each country's zone in this border cell, coloured by country. The
    // dataset's zone rings are even-odd, so sort by area and nest a ring inside
    // a larger one as its hole; disjoint rings become separate polygons.
    for(const [cid,rings] of cc._refine.get(index)){
      if(rings===null)continue;
      const color=countryColor(cid);
      const decoded=rings.map(pts=>{
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
      for(const P of polys)feats.push({type:'Feature',properties:{color},
        geometry:{type:'Polygon',coordinates:P.coords}});
    }
    if(nverts>120000)return null;   // too much detail for this view
  }
  return feats;
}
function updateBorders(){
  if(!bordercb.checked){
    map.getSource('borders').setData({type:'FeatureCollection',features:[]});
    return;
  }
  if(!cc._refine){
    bordernote.textContent='Turn on exact border refinement first to load the polygons.';
    bordercb.checked=false;return;
  }
  const feats=borderFeatures();
  if(feats===null){
    map.getSource('borders').setData({type:'FeatureCollection',features:[]});
    bordernote.textContent='Source border zones: zoom in further to draw them.';
    return;
  }
  map.getSource('borders').setData({type:'FeatureCollection',features:feats});
  bordernote.textContent=`${feats.length.toLocaleString()} border-cell zone(s) in view, `+
    `filled and coloured by country, decoded from the refinement dataset — exactly the `+
    `geometry the refined lookup tests against.`;
}
bordercb.onchange=updateBorders;

// --- exact border refinement toggle ---
let refineCells=null;   // decoded TFCR, kept so the checkbox can flip freely
const refinecb=document.getElementById('refinecb');
const refinenote=document.getElementById('refinenote');
refinecb.onchange=async()=>{
  if(refinecb.checked&&!refineCells){
    refinecb.disabled=true;
    refinenote.textContent='Downloading border refinement layer…';
    let loaded=false;
    for(const url of TFCR_URLS){
      try{
        const res=await fetch(url);
        if(!res.ok)continue;
        const buf=await res.arrayBuffer();
        refinenote.textContent=`Decoding ${(buf.byteLength/1e6).toFixed(1)} MB…`;
        await cc.loadRefinement(new Uint8Array(buf));
        refineCells=cc._refine;
        loaded=true;
        refinenote.textContent=`Loaded: ${refineCells.size.toLocaleString()} border cells with `+
          `exact polygon detail. Border answers are now near-exact (confidence 0.99).`;
        break;
      }catch(err){console.warn(url,err);}
    }
    refinecb.disabled=false;
    if(!loaded){
      refinecb.checked=false;
      refinenote.textContent='Could not download the refinement layer, so the bundled best calls stay in use.';
      return;
    }
  }else{
    cc._refine=refinecb.checked?refineCells:null;
    refinenote.textContent=refinecb.checked
      ?'Exact polygon test active in border cells.'
      :'Off: border cells use the bundled best call and its area share.';
  }
  if(lastPts)show(lastPts,lastLabel);   // re-classify so the effect is visible
  demo.refreshSelection();
  updateBorders();                      // border layer follows refinement
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
      e.target.value='';return;
    }
    const pts=isJson?parseGeojson(text):parseCsv(text);
    if(pts.length>5000)throw new Error('too many points (max 5,000)');
    show(pts,file.name);
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
  eu:[[13.405,52.52],[21.0122,52.2297],[25.2797,54.6872]],   // Berlin -> Warsaw -> Vilnius
  med:[[-3.7038,40.4168],[12.4964,41.9028]],                  // Madrid -> Rome
  asia:[[28.9784,41.0082],[51.3890,35.6892],[77.2090,28.6139]]};  // Istanbul -> Tehran -> Delhi
function stepKm(){return parseFloat(document.querySelector('#seg-step .on').dataset.v);}
function segColor(s){
  return s.country==null?NONE_COLOR:countryColor(codeToCid.get(s.country));
}
function classifyRoute(){
  const coords=routePts.slice();
  if(coords.length<2){routenote.textContent='Add at least two points.';return;}
  const step=stepKm();
  const t0=performance.now();
  const res=cc.checkPolyline(coords,{stepKm:step});   // the real library call, timed
  const ms=performance.now()-t0;
  // colour the line: re-sample and group consecutive samples sharing country+kind.
  // segments join at the midpoint between samples (no gaps); stats come from
  // res.segments, whose order matches this grouping one-to-one.
  const {samples}=samplePolyline(coords,step,'uniform');
  const cls=samples.map(s=>cc.check(s[0],s[1]));
  const mid=(p,q)=>[(p[0]+q[0])/2,(p[1]+q[1])/2];
  const feats=[];let i=0,k=0;
  while(i<samples.length){
    const a=cls[i];let j=i;
    while(j+1<samples.length&&cls[j+1].country===a.country)j++;
    const cid=a.country==null?-1:codeToCid.get(a.country);
    const line=samples.slice(i,j+1);
    if(i>0)line.unshift(mid(samples[i-1],samples[i]));
    if(j<samples.length-1)line.push(mid(samples[j],samples[j+1]));
    const seg=res.segments[k++]||{};
    feats.push({type:'Feature',
      properties:{color:a.country==null?NONE_COLOR:countryColor(cid),
        country:a.country,iso2:a.iso2,cname:a.name,kind:a.kind,
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
  const refineOn=!!cc._refine;
  let rows='';
  for(const s of res.segments)
    rows+=`<span style="color:${segColor(s)}">■</span> `+
      `<b>${s.name||s.country||'no country'}</b>${s.iso2?' ('+s.iso2+')':''} · `+
      `${s.distanceKm.toFixed(0)} km (${(100*s.fraction).toFixed(0)}%)<br>`;
  perf.style.display='block';
  perf.innerHTML=
    `<b>${Math.round(rate).toLocaleString()}</b> samples/second on this device<br>`+
    `${samples.length.toLocaleString()} samples · `+
    `${res.totalDistanceKm.toFixed(0)} km total · `+
    `${res.segments.length} segment${res.segments.length===1?'':'s'} (step ${step} km)`+
    `${refineOn?' · <b>refinement on</b>':''}<br>`+rows;
  routenote.textContent=`${coords.length} vertices · classified in ${ms.toFixed(1)} ms.`;
}
function addVertex(lon,lat){
  routePts.push([lon,lat]);
  map.getSource('routeverts').setData({type:'FeatureCollection',
    features:routePts.map(c=>({type:'Feature',properties:{},
      geometry:{type:'Point',coordinates:c}}))});
  if(routePts.length>=2)
    map.getSource('route').setData({type:'FeatureCollection',
      features:[{type:'Feature',properties:{color:'#888'},
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
document.getElementById('b-route-asia').onclick=()=>loadRoute(ROUTES.asia);
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

window.__countrycheck={map,cc,demo};   // console/debug handle
