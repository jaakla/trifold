import {test} from 'node:test';
import assert from 'node:assert/strict';
// Generated configuration supplies the public browser key.
import {normalizePoint,parsePoints,cartoRequest,createGeneration,queryPoints,withinBudget} from '../../../docs/assets/map-demo.mjs';

test('geometry budget rejects over-cap before allocation',()=>{
  assert.equal(withinBudget(6500,6500),true);
  for(const size of [6501,14000,Infinity,NaN,-1])assert.equal(withinBudget(size,6500),false);
});

test('geographic validation and wrapped longitude',()=>{
  assert.deepEqual(normalizePoint(180.01,0),[-179.99,0]);
  assert.deepEqual(normalizePoint(540,90),[-180,90]);
  for(const point of [['',1],[1,91],[Infinity,0],[1,null]])assert.throws(()=>normalizePoint(...point));
});
test('CARTO key is restricted to CARTO and preserves custom protocols',()=>{
  const carto=cartoRequest('https://tiles.basemaps.cartocdn.com/tiles.json').url;
  assert.ok(new URL(carto).searchParams.has('key'));
  const custom='pmtiles://https://maps.goplex.ee/data/test.pmtiles';
  assert.equal(cartoRequest(custom).url,custom);
  assert.equal(cartoRequest('https://example.org/test').url,'https://example.org/test');
});
test('bounded CSV/GeoJSON, invalid rows and empty values',()=>{
  const parsed=parsePoints('name,latitude,longitude\n"A, B",59.437,24.7536\nMissing,0,\nBad,no,4');
  assert.equal(parsed.points.length,1);assert.equal(parsed.invalid,2);
  assert.equal(parsePoints('{"type":"MultiPoint","coordinates":[[0,0],[1,2]]}').points.length,2);
  assert.throws(()=>parsePoints('lon,lat\n0,0\n1,1',{limit:1}),/Maximum/);
  assert.throws(()=>parsePoints('x'.repeat(2*1024*1024+1)),/2 MB/);
  assert.throws(()=>parsePoints('lon,name\n1,A'),/both/);
});
test('new selection invalidates previous result and aborts its signal',()=>{
  const generation=createGeneration(),old=generation.next(),next=generation.next();
  assert.equal(old.current(),false);assert.equal(old.signal.aborted,true);
  assert.equal(next.current(),true);generation.cancel();assert.equal(next.current(),false);
});
test('batch cancellation stops stale results between chunks',async()=>{
  const generation=createGeneration(),task=generation.next();let calls=0;
  const results=await queryPoints(Array.from({length:150},()=>[0,0]),()=>{calls++;if(calls===2)generation.cancel();return {};},task);
  assert.equal(results,null);assert.ok(calls<=64);
});
