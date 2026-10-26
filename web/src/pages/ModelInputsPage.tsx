import { Fragment, useState } from "react";
import { useParams } from "react-router";
import { DriftSpark } from "../charts/DriftSpark";
import { HistogramCompare } from "../charts/HistogramCompare";
import { ReconstructionChart } from "../charts/ReconstructionChart";
import { Legend } from "../components/Legend";
import { QueryState } from "../components/QueryState";
import { useModel } from "../data/api";
import type { Feature, Model } from "../data/schema";
import { METHOD_LABELS } from "../lib/describe";
import { decimal, percent, pValue, shortDate } from "../lib/format";
import { ModelHeader } from "./ModelHeader";
import styles from "./ModelInputsPage.module.css";
import layout from "./layout.module.css";
import { TableScroll } from "../components/TableScroll";
import { useTitle } from "../lib/useTitle";

export function ModelInputsPage() {
  const { modelId = "" } = useParams();
  useTitle(`${modelId} inputs`);
  const model = useModel(modelId);
  return (
    <QueryState query={model} subject="this model">
      {(data) => <Inputs model={data} />}
    </QueryState>
  );
}

function Inputs({ model }: { model: Model }) {
  const features = [...model.features].sort(
    (a, b) => Number(b.latest.drifted) - Number(a.latest.drifted) || a.name.localeCompare(b.name),
  );
  const drifted = features.filter((f) => f.latest.drifted);
  const firstOut = model.days.find((d) => d.multivariate.drifted);
  const latestOut = model.days.at(-1)?.multivariate.drifted ?? false;

  return (
    <div className={layout.page}>
      <ModelHeader model={model} />

      <section className={layout.section} aria-labelledby="relationships-heading">
        <div className={layout.sectionHead}>
          <h2 id="relationships-heading">Feature relationships</h2>
        </div>
        <p className={layout.meta}>
          {latestOut
            ? `Outside the expected range${firstOut ? ` since ${shortDate(firstOut.date)}` : ""}. The way features move together has changed, which can hurt accuracy even when each feature looks normal on its own.`
            : "Within the expected range. Features still move together the way they did in the reference data."}
        </p>
        <ReconstructionChart days={model.days} />
        <p className={layout.sectionNote}>
          Each day's data is compressed with PCA fitted on reference data, then rebuilt; the line is
          the average rebuild error. The shaded area is the range clean data falls in, and it widens on
          days with fewer predictions.
        </p>
      </section>

      <section className={layout.section} aria-labelledby="features-heading">
        <div className={layout.sectionHead}>
          <h2 id="features-heading">Features</h2>
          <p className={layout.quiet}>
            {drifted.length === 0
              ? `None of ${features.length} features drifted on the latest day.`
              : `${drifted.length} of ${features.length} drifted on the latest day.`}
          </p>
        </div>
        <FeatureTable features={features} />
      </section>
    </div>
  );
}

function FeatureTable({ features }: { features: Feature[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <TableScroll label="Features">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Feature</th>
            <th scope="col">Test</th>
            <th scope="col" className={layout.num}>Latest</th>
            <th scope="col" className={layout.num}>Threshold</th>
            <th scope="col" className={layout.num}>PSI</th>
            <th scope="col" className={styles.sparkHead}>
              Last 30 days
            </th>
            <th scope="col">
              <span className="visually-hidden">Distribution</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {features.map((f) => {
            const isOpen = open === f.name;
            const panelId = `hist-${f.name}`;
            return (
              <Fragment key={f.name}>
                <tr data-drifted={f.latest.drifted} className={styles.row}>
                  <th scope="row" className={styles.name}>
                    {f.name}
                    <div className={styles.kind}>
                      {f.kind}
                      {f.latest.nullRate > 0 && `, ${percent(f.latest.nullRate, 0)} missing`}
                    </div>
                  </th>
                  <td className={styles.method}>{METHOD_LABELS[f.method]}</td>
                  <td className={layout.num}>
                    <span className={f.latest.drifted ? styles.drifted : undefined}>
                      {f.isPValue ? pValue(f.latest.statistic) : decimal(f.latest.statistic, 3)}
                    </span>
                    {f.latest.drifted && <div className={styles.flag}>Drifted</div>}
                  </td>
                  <td className={layout.num}>
                    {f.isPValue ? `p < ${f.threshold}` : `≥ ${decimal(f.threshold, 2)}`}
                  </td>
                  <td className={layout.num}>{decimal(f.latest.psi, 3)}</td>
                  <td>
                    <DriftSpark feature={f} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className={styles.toggle}
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      onClick={() => setOpen(isOpen ? null : f.name)}
                    >
                      {isOpen ? "Hide distribution" : "Show distribution"}
                      <span className="visually-hidden"> of {f.name}</span>
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr className={styles.panelRow}>
                    <td colSpan={7} id={panelId}>
                      <div className={styles.panel}>
                        <Legend
                          items={["barReference", "bar"]}
                          labels={{ barReference: "Reference data", bar: "Latest day" }}
                        />
                        <HistogramCompare
                          feature={f.name}
                          bins={f.histogram.bins}
                          reference={f.histogram.reference}
                          current={f.histogram.current}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <p className={layout.sectionNote}>
        The test is chosen from the feature's type and the size of the reference data. The line shows
        each day's result relative to its threshold; above the rule means drift.
      </p>
    </TableScroll>
  );
}
