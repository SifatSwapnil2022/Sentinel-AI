import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { source } from "../../data/api";
import { BI_TABLES } from "../../lib/biTables";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import styles from "./Reports.module.css";

const REPO = "https://github.com/SifatSwapnil2022/Sentinel-AI";
const base = import.meta.env.BASE_URL;

/** Absolute address of a table, for BI tools that load from the web. */
function absolute(path: string): string {
  return new URL(path, window.location.origin).toString();
}

export function ReportsPage() {
  useTitle("Reports");
  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Reports</h1>
        <p className={layout.lead}>
          The numbers behind every chart here, as seven CSV tables in a star schema. Power BI, Tableau
          and spreadsheets read them as they are, and they match the dashboard to the last digit
          because both are built from the same documents.
        </p>
      </header>

      <div className={layout.grid}>
        <Tile span={6} title="Power BI" note="A Power BI project: semantic model, measures and three report pages.">
          <ol className={styles.steps}>
            <li>
              <a href={`${base}reports/sentinel-powerbi.zip`} download>
                Download the project
              </a>{" "}
              and unzip it.
            </li>
            <li>
              Open <code>Sentinel.pbip</code> in Power BI Desktop (June 2024 or later, with the PBIP
              preview feature on).
            </li>
            <li>
              The <code>DataUrl</code> parameter points at this site's tables. For live data, set it
              to your API's <code>/v1/export/</code> address and <code>ApiKey</code> to a read key,
              then refresh.
            </li>
          </ol>
        </Tile>

        <Tile span={6} title="Tableau" note="A packaged workbook with the tables inside, joined on their keys.">
          <ol className={styles.steps}>
            <li>
              <a href={`${base}reports/sentinel.twbx`} download>
                Download the workbook
              </a>
              .
            </li>
            <li>Open it in Tableau Desktop or Tableau Public (2023.1 or later).</li>
            <li>
              To refresh, download the CSVs below into one folder and use Data, Replace Data Source, or
              point the connection at that folder.
            </li>
          </ol>
        </Tile>

        <Tile title="Tables" note="Dimensions describe models and days; facts hold the measurements. Join on the key columns.">
          <Schema />
          <TableScroll label="Tables">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Table</th>
                  <th scope="col">Grain</th>
                  <th scope="col">Key</th>
                  <th scope="col">Contents</th>
                  <th scope="col">Download</th>
                </tr>
              </thead>
              <tbody>
                {BI_TABLES.map((t) => (
                  <tr key={t.name}>
                    <th scope="row">
                      <code>{t.name}</code>
                    </th>
                    <td>{t.grain}</td>
                    <td>
                      <code>{t.keys.join(", ")}</code>
                    </td>
                    <td className={styles.description}>{t.description}</td>
                    <td>
                      <a href={source.export(t.name)} download={`${t.name}.csv`}>
                        CSV
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          <p className={styles.note}>
            Web address for a BI tool's web connector: <code>{absolute(source.export("fact_model_day"))}</code>,
            and the same pattern for the other tables. Every column is described in the{" "}
            <a href={`${REPO}/blob/main/docs/bi.md`}>data dictionary</a>.
          </p>
        </Tile>
      </div>
    </div>
  );
}

/** Which fact tables join to which dimensions. */
function Schema() {
  const facts = BI_TABLES.filter((t) => t.kind === "fact");
  return (
    <div className={styles.schema} role="img" aria-label="Star schema: every fact table joins dim_model on model_id; daily facts also join dim_date on date; fact_incident_signal joins fact_incident on incident_id.">
      <div className={styles.dims}>
        <span className={styles.dim}>dim_model</span>
        <span className={styles.dim}>dim_date</span>
      </div>
      <ul className={styles.facts}>
        {facts.map((f) => (
          <li key={f.name}>
            <span className={styles.fact}>{f.name}</span>
            <span className={styles.joins}>
              {f.name === "fact_incident_signal"
                ? "fact_incident on incident_id"
                : f.keys.includes("date")
                  ? "dim_model on model_id, dim_date on date"
                  : "dim_model on model_id"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
