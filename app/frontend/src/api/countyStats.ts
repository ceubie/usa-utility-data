import { querySparql } from "./client";
import type { RequestOptions } from "./http";
import { isSector } from "../types/graph";

export interface CountyStat {
  geoid: string;
  providers: number | null;
  authorities: string[];
}

export interface CountyStatResult {
  stats: CountyStat[];
  complete: boolean;
  note: string | null;
}

const ROW_CAP = 1000;

export async function loadCountyStats(
  fips: string,
  sector: string | null,
  options?: RequestOptions,
): Promise<CountyStatResult> {
  if (!/^\d{2}$/.test(fips)) {
    return { stats: [], complete: false, note: "The state has no county FIPS in the base map." };
  }
  const sectorName = sector && isSector(sector) ? sector : null;
  try {
    const providers = await querySparql(providerQuery(fips, sectorName), options);
    const authority = await querySparql(authorityQuery(fips, sectorName), options);
    if (providers.kind !== "select" || authority.kind !== "select") {
      return { stats: [], complete: false, note: "County counts were not a SELECT result." };
    }
    const providerComplete = providers.row_count < ROW_CAP;
    const authorityComplete = authority.row_count < ROW_CAP;
    const byGeoid = new Map<string, CountyStat>();
    for (const row of providers.rows) {
      const geoid = row.geoid?.value;
      const count = row.providers?.value;
      if (!geoid) continue;
      const parsed = count === undefined ? null : Number(count);
      byGeoid.set(geoid, {
        geoid,
        providers: parsed !== null && Number.isFinite(parsed) ? parsed : null,
        authorities: [],
      });
    }
    for (const row of authority.rows) {
      const geoid = row.geoid?.value;
      const name = row.authority?.value;
      if (!geoid || !name) continue;
      const current = byGeoid.get(geoid) ?? { geoid, providers: providerComplete ? 0 : null, authorities: [] };
      if (!current.authorities.includes(name)) current.authorities.push(name);
      byGeoid.set(geoid, current);
    }
    const notes: string[] = [];
    if (!providerComplete) notes.push("Provider counts stopped at the query limit.");
    if (!authorityComplete) notes.push("Authority values stopped at the query limit.");
    return {
      stats: [...byGeoid.values()],
      complete: providerComplete,
      note: notes.length > 0 ? notes.join(" ") : null,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "County counts failed.";
    return { stats: [], complete: false, note: message };
  }
}

function providerQuery(fips: string, sector: string | null): string {
  const sectorLine = sector ? `\n    ?system ud:sector ${quote(sector)} .` : "";
  return `PREFIX ud: <http://utilities.local/ontology/>
SELECT ?geoid (COUNT(DISTINCT ?system) AS ?providers) WHERE {
  ?system ud:servesCounty ?county .${sectorLine}
  ?county ud:county_geoid ?geoid ;
          ud:state ${quote(fips)} .
}
GROUP BY ?geoid`;
}

function authorityQuery(fips: string, sector: string | null): string {
  const sectorLine = sector ? `\n            ud:sector ${quote(sector)} ;` : "";
  return `PREFIX ud: <http://utilities.local/ontology/>
SELECT ?geoid ?authority WHERE {
  ?coverage a ud:CountyCoverage ;
            ud:county_geoid ?geoid ;
            ud:state ${quote(fips)} ;
            ud:is_served true ;
            ud:authority ?authority ;${sectorLine}
            ud:county_geoid ?geoid .
}`;
}

function quote(value: string): string {
  return JSON.stringify(value);
}
