import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(frontend, "../..");
const outputDir = join(frontend, "public", "geo");
const mapshaper = join(frontend, "node_modules", "mapshaper", "bin", "mapshaper");

const layers = [
  {
    kind: "state",
    collectionName: "cb_2025_us_state_500k.zip",
    output: join(outputDir, "states.topo.json"),
    fields: "GEOID,STUSPS,NAME,STATEFP",
    percent: "10",
  },
  {
    kind: "county",
    collectionName: "cb_2025_us_county_500k.zip",
    output: join(outputDir, "counties.topo.json"),
    fields: "GEOID,STATEFP,NAME,NAMELSAD",
    percent: "5",
  },
];

if (!existsSync(mapshaper)) {
  console.error("mapshaper is not installed. Base maps were not written, and no geometries were invented.");
  process.exit(1);
}

mkdirSync(outputDir, { recursive: true });

for (const layer of layers) {
  const source = resolveSource(layer.kind, layer.collectionName);
  if (!source) {
    console.error(
      `No Census cartographic boundary file was found for ${layer.kind}. ` +
        "Looked in collection/data/reference and for TIGER zips under the data root. " +
        "No geometries were invented.",
    );
    process.exit(1);
  }
  console.log(`mapshaper ${source} -> ${layer.output}`);
  const filtered = runMapshaper(source, layer.output, layer.percent, layer.fields);
  if (filtered.status !== 0) {
    console.error("mapshaper field filter failed. Retrying the same file without dropping fields.");
    const plain = runMapshaper(source, layer.output, layer.percent, null);
    if (plain.status !== 0) {
      console.error("mapshaper failed. No geometries were invented.");
      process.exit(plain.status ?? 1);
    }
  }
}

function runMapshaper(source, output, percent, fields) {
  const args = [mapshaper, source, "-simplify", `${percent}%`, "keep-shapes"];
  if (fields) args.push("-filter-fields", fields);
  args.push("-o", "format=topojson", "force", output);
  return spawnSync(process.execPath, args, { stdio: "inherit" });
}

function resolveSource(kind, collectionName) {
  const collection = join(repo, "collection", "data", "reference", collectionName);
  if (existsSync(collection)) return collection;
  const found = findTigerZip(kind);
  return found;
}

function findTigerZip(kind) {
  const hits = [];
  for (const root of [join(repo, "data"), join(repo, "collection", "data")]) {
    walkZips(root, hits, 0);
  }
  return (
    hits.find((path) => {
      const name = path.toLowerCase();
      if (!name.endsWith(".zip")) return false;
      if (!/(tiger|tl_|cb_|cartographic|boundary)/.test(name)) return false;
      if (kind === "county") return name.includes("county");
      return name.includes("state") && !name.includes("county");
    }) ?? null
  );
}

function walkZips(directory, hits, depth) {
  if (depth > 4 || !existsSync(directory)) return;
  let entries = [];
  try {
    entries = readdirSync(directory);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry === "node_modules" || entry === "releases" || entry === "graph" || entry === "snapshots") continue;
    const path = join(directory, entry);
    let info;
    try {
      info = statSync(path);
    } catch {
      continue;
    }
    if (info.isDirectory()) walkZips(path, hits, depth + 1);
    else if (entry.toLowerCase().endsWith(".zip")) hits.push(path);
  }
}
