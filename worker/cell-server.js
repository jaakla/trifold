/**
 * HTTP adapter for the Trifold JavaScript SDK.
 *
 * Endpoints:
 *   GET /cell/{addr}
 *   GET /cells/{addr1},{addr2},...
 *   GET /locate/{lon},{lat}?level=N
 *   GET /parent/{addr}
 *   GET /children/{addr}
 *   GET /level/{N}?face=F
 *
 * Deploy with: npx wrangler deploy worker/cell-server.js
 */
import {
  MAX_LEVEL,
  cellFeature,
  children64,
  encode64,
  levelFeatureCollection,
  locateAddress,
  parent64,
  parseAddress,
  toCompact,
  toPath,
} from "../js/trifold.js";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Content-Type": "application/json",
  "Cache-Control": "public, max-age=86400",
};

const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: CORS });

const parseLevel = (value, fallback = 6) => {
  const level = Number.parseInt(value ?? String(fallback), 10);
  if (!Number.isInteger(level) || level < 0 || level > MAX_LEVEL) {
    throw new RangeError(`level must be within 0..${MAX_LEVEL}`);
  }
  return level;
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const segments = url.pathname.split("/").filter(Boolean);
    try {
      if (segments[0] === "cell" && segments[1]) {
        return json(cellFeature(segments[1]));
      }

      if (segments[0] === "cells" && segments[1]) {
        const addresses = segments[1].split(",").slice(0, 500);
        return json({
          type: "FeatureCollection",
          features: addresses.map(address => cellFeature(address)),
        });
      }

      if (segments[0] === "locate" && segments[1]) {
        const [lon, lat] = segments[1].split(",").map(Number);
        const level = parseLevel(url.searchParams.get("level"));
        const address = locateAddress(lon, lat, level);
        return json({
          id: toCompact(address),
          path: toPath(address),
          addr64: address.toString(),
          level,
        });
      }

      if (segments[0] === "parent" && segments[1]) {
        const identity = parseAddress(segments[1]);
        if (!identity.digits.length) return json({ error: "level-0 has no parent" }, 400);
        return json({ id: toCompact(parent64(encode64(identity.face, identity.digits))) });
      }

      if (segments[0] === "children" && segments[1]) {
        const identity = parseAddress(segments[1]);
        const address = encode64(identity.face, identity.digits);
        return json({ ids: children64(address).map(toCompact) });
      }

      if (segments[0] === "level" && segments[1]) {
        const level = parseLevel(segments[1]);
        if (level > 5) return json({ error: "level > 5: use /cells or PMTiles" }, 400);
        const faceValue = url.searchParams.get("face");
        const face = faceValue === null ? null : Number.parseInt(faceValue, 10);
        return json(levelFeatureCollection(level, { face }));
      }

      return json({
        sdk: "@trifold/grid",
        endpoints: [
          "/cell/{addr}",
          "/cells/{a1},{a2},...",
          "/locate/{lon},{lat}?level=N",
          "/parent/{addr}",
          "/children/{addr}",
          "/level/{N}?face=F",
        ],
        example: "/locate/-0.1276,51.5072?level=6  ->  TF6958",
      });
    } catch (error) {
      return json({ error: String(error?.message ?? error) }, 400);
    }
  },
};
