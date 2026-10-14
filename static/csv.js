/* SABAGeo: read plot corners from a CSV file. Used by the map page and Register New Plot.

   Two kinds of file work:
   1. No header row: the first two columns, in the order the coordinate type expects
      (latitude, longitude for lat/long types; easting, northing for the others).
   2. A header row, like the field kit template:
        corner,easting,northing,latitude,longitude,datum,zone,notes
      Columns are found by name, so their order does not matter. Fill in EITHER
      easting + northing OR latitude + longitude. If the datum and zone columns are
      filled in, the matching coordinate type is suggested.

   parseCornerCsv(text) returns
     { pairs: [[a, b], ...], kind: "degrees" | "metres" | null, crs: suggested type or null, skipped: n }
   pairs are [latitude, longitude] when kind is "degrees", else [easting, northing].
   kind is null for a file without a header (the caller keeps its current type). */
(function () {
  const isNum = (s) => s !== "" && s != null && !isNaN(Number(s));
  const NAMES = {
    lat: ["latitude", "lat"],
    lon: ["longitude", "lon", "long", "lng"],
    e: ["easting", "east", "x", "e"],
    n: ["northing", "north", "y", "n"],
    datum: ["datum"],
    zone: ["zone", "belt", "zone_or_belt"],
  };

  function split(line) {
    return line.split(/[,;\t]/).map((x) => x.trim().replace(/^"|"$/g, ""));
  }

  function suggest(datum, zone) {
    const d = (datum || "").toLowerCase();
    const z = (zone || "").toLowerCase().replace(/\s+/g, "");
    const minna = d.includes("minna");
    if (!minna && !/wgs/.test(d)) return null; // only suggest when the file says which datum it is
    if (minna && /west/.test(z)) return "minna_west";
    if (minna && /mid/.test(z)) return "minna_mid";
    if (minna && /east/.test(z)) return "minna_east";
    const m = z.match(/3[123]/);
    if (m) return (minna ? "minna_utm" : "utm") + m[0];
    if (/latlon|latlong|geographic|degrees/.test(z)) return minna ? "minna" : "wgs84";
    return null;
  }

  window.parseCornerCsv = function (text) {
    const lines = String(text || "").replace(/^﻿/, "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return { pairs: [], kind: null, crs: null, skipped: 0 };
    const first = split(lines[0]);
    const hasHeader = first.some((c) => /[a-z]/i.test(c) && !isNum(c));

    if (!hasHeader) {
      const rows = lines.map(split);
      const good = rows.filter((c) => c.length >= 2 && isNum(c[0]) && isNum(c[1]));
      return { pairs: good.map((c) => [Number(c[0]), Number(c[1])]), kind: null, crs: null, skipped: rows.length - good.length };
    }

    const head = first.map((h) => h.toLowerCase().replace(/[^a-z_]/g, ""));
    const col = (key) => head.findIndex((h) => NAMES[key].includes(h));
    const c = { lat: col("lat"), lon: col("lon"), e: col("e"), n: col("n"), datum: col("datum"), zone: col("zone") };
    const rows = lines.slice(1).map(split);

    const pick = (a, b) => rows.filter((r) => a >= 0 && b >= 0 && isNum(r[a]) && isNum(r[b])).map((r) => [Number(r[a]), Number(r[b])]);
    const metres = pick(c.e, c.n);
    const degrees = pick(c.lat, c.lon);
    const useDegrees = degrees.length > metres.length;
    const pairs = useDegrees ? degrees : metres;

    // the first filled-in datum and zone decide the suggested type
    const firstVal = (i) => { if (i < 0) return ""; const r = rows.find((x) => (x[i] || "") !== ""); return r ? r[i] : ""; };
    let crs = suggest(firstVal(c.datum), useDegrees ? "latlon" : firstVal(c.zone));
    if (crs && useDegrees !== (crs === "wgs84" || crs === "minna")) crs = null; // datum/zone disagrees with the columns used

    return { pairs, kind: pairs.length ? (useDegrees ? "degrees" : "metres") : null, crs, skipped: rows.length - pairs.length };
  };
})();
