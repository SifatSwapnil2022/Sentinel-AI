import { useCallback, useMemo } from "react";
import { Link, useLocation } from "react-router";
import { DailyChart } from "../../charts/DailyChart";
import { DriftSpark, driftScore } from "../../charts/DriftSpark";
import { Heatmap, ScaleLegend } from "../../charts/Heatmap";
import { HistogramCompare } from "../../charts/HistogramCompare";
import { ReconstructionChart } from "../../charts/ReconstructionChart";
import { Legend } from "../../components/Legend";
import { SortableTh } from "../../components/SortableTh";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import type { Day, Feature, Model } from "../../data/schema";
import { withParams } from "../../filters/links";
import { csvName } from "../../lib/csv";
import { METHOD_LABELS } from "../../lib/describe";
import { decimal, percent, points, pValue, shortDate } from "../../lib/format";
import { useSort } from "../../lib/useSort";
import layout from "../layout.module.css";
import styles from "./Model.module.css";

/** Drift score: the test result as a multiple of its threshold, so 1 is where drift starts. */
export const DRIFT_BINS = [
  { below: 0.5, token: "--seq-1", label: "Under half the threshold" },
  { below: 1, token: "--seq-2", label: "Half to threshold" },
  { below: 2, token: "--seq-4", label: "Over threshold" },
  { below: Number.POSITIVE_INFINITY, token: "--seq-6", label: "Twice the threshold or more" },
] as const;

export function driftColor(score: number): string {
  return `var(${(DRIFT_BINS.find((b) => score < b.below) ?? DRIFT_BINS[3]).token})`;
}

/** A missing-value rate this far above the reference counts as a data quality problem. */
export const MISSING_JUMP = 0.05;

interface FeatureRow {
  feature: Feature;
  driftDays: number;
  missing: number | null;
  missingJump: number | null;
}

type Key = "name" | "method" | "latest" | "psi" | "driftDays" | "missing";

export function InputsTab({ model, days }: { model: Model; days: Day[] }) {
  const { search } = useLocation();
  const dates = useMemo(() => days.map((d) => d.date), [days]);
  const inRange = useMemo(() => new Set(dates), [dates]);

  const rows: FeatureRow[] = useMemo(
    () =>
      model.features.map((feature) => {
        const series = feature.series.filter((s) => inRange.has(s.date));
        const last = series.at(-1);
        const missing = last?.nullRate ?? null;
        return {
          feature,
          driftDays: series.filter((s) => s.drifted).length,
          missing,
          missingJump: missing === null ? null : missing - feature.referenceNullRate,
        };
      }),
    [model.features, inRange],
  );

  const get = useCallback((row: FeatureRow, key: Key): string | number | null => {
    const f = row.feature;
    switch (key) {
      case "name":
        return f.name;
      case "method":
        return METHOD_LABELS[f.method];
      case "latest":
        return driftScore(f.latest.statistic, f.threshold, f.isPValue);
      case "psi":
        return f.latest.psi;
      case "driftDays":
        return row.driftDays;
      case "missing":
        return row.missingJump;
    }
  }, []);
  const { sorted, toggle, ariaSort } = useSort<FeatureRow, Key>(rows, get, { key: "driftDays", direction: "desc" });

  const requested = new URLSearchParams(search).get("feature");
  const selected =
    rows.find((r) => r.feature.name === requested) ??
    [...rows].sort((a, b) => b.driftDays - a.driftDays || (b.missingJump ?? 0) - (a.missingJump ?? 0))[0];

  const byCell = useMemo(() => {
    const map = new Map<string, { score: number | null; nullRate: number | null; drifted: boolean }>();
    for (const f of model.features) {
      for (const s of f.series) {
        map.set(`${f.name}|${s.date}`, {
          score: s.statistic === null ? null : driftScore(s.statistic, f.threshold, f.isPValue),
          nullRate: s.nullRate,
          drifted: s.drifted,
        });
      }
    }
    return map;
  }, [model.features]);
  const reference = new Map(model.features.map((f) => [f.name, f.referenceNullRate]));
  const missingSpike = (name: string, date: string) => {
    const cell = byCell.get(`${name}|${date}`);
    return cell?.nullRate != null && cell.nullRate - (reference.get(name) ?? 0) > MISSING_JUMP;
  };

  const withMissing = rows.filter((r) =>
    r.feature.series.some((s) => inRange.has(s.date) && s.nullRate !== null && s.nullRate - r.feature.referenceNullRate > 0.01),
  );
  const span = `${shortDate(dates[0] ?? "")} to ${shortDate(dates.at(-1) ?? "")}`;
  const heatmapRows = [...rows].sort((a, b) => b.driftDays - a.driftDays || a.feature.name.localeCompare(b.feature.name));
  const firstOut = days.find((d) => d.multivariate.drifted);

  return (
    <div className={layout.grid}>
      <Tile
        title="Drift by feature and day"
        note={`Each day's test result against its threshold, ${span}. Triangles mark days with ${percent(MISSING_JUMP, 0)}+ more missing values than the reference. Select a cell to inspect the feature.`}
        table={() => (
          <TableScroll label="Drift by feature and day">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  {heatmapRows.map((r) => (
                    <th key={r.feature.name} scope="col" className={layout.num}>
                      {r.feature.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...dates].reverse().map((date) => (
                  <tr key={date}>
                    <th scope="row">{shortDate(date)}</th>
                    {heatmapRows.map((r) => {
                      const cell = byCell.get(`${r.feature.name}|${date}`);
                      return (
                        <td key={r.feature.name} className={layout.num}>
                          {cell?.score == null ? "No data" : `${decimal(cell.score, 2)}${cell.drifted ? " drifted" : ""}`}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
        csv={() => ({
          name: csvName(model.id, "feature-drift", dates[0] ?? "", dates.at(-1) ?? ""),
          rows: model.features.flatMap((f) =>
            f.series
              .filter((s) => inRange.has(s.date))
              .map((s) => ({
                feature: f.name,
                date: s.date,
                method: f.method,
                statistic: s.statistic,
                threshold: f.threshold,
                drifted: s.drifted,
                psi: s.psi,
                null_rate: s.nullRate,
                reference_null_rate: f.referenceNullRate,
              })),
          ),
        })}
      >
        <Heatmap
          label={`Daily drift score for ${rows.length} features of ${model.name}, ${span}`}
          rows={heatmapRows.map((r) => ({
            id: r.feature.name,
            label: r.feature.name,
            href: withParams(search, { feature: r.feature.name }),
          }))}
          columns={dates}
          value={(name, date) => byCell.get(`${name}|${date}`)?.score ?? null}
          color={driftColor}
          marker={missingSpike}
          cellHref={(name) => withParams(search, { feature: name })}
          labelWidth={170}
          describe={(name, date, score) => {
            const cell = byCell.get(`${name}|${date}`);
            return (
              <>
                <strong>
                  {name}, {shortDate(date)}
                </strong>
                {score === null ? "No values to test" : `${decimal(score, 2)} times the threshold${cell?.drifted ? ", drifted" : ""}`}
                <br />
                {percent(cell?.nullRate, 1)} missing, {percent(reference.get(name), 1)} in reference
              </>
            );
          }}
        />
        <ScaleLegend items={DRIFT_BINS.map((b) => ({ color: `var(${b.token})`, label: b.label }))} />
      </Tile>

      {selected && <FeatureDetail row={selected} />}

      <Tile
        span={6}
        title="Feature relationships"
        note={
          days.at(-1)?.multivariate.drifted
            ? `Outside the expected range${firstOut ? ` since ${shortDate(firstOut.date)}` : ""}: features no longer move together as in the reference.`
            : "Within the expected range: features still move together as in the reference."
        }
        csv={() => ({
          name: csvName(model.id, "reconstruction", dates[0] ?? "", dates.at(-1) ?? ""),
          rows: days.map((d) => ({ date: d.date, ...d.multivariate })),
        })}
      >
        <ReconstructionChart days={days} />
        <p className={styles.note}>
          PCA fitted on the reference compresses each day's rows and rebuilds them. The line is the
          average rebuild error; the band is where clean data falls, wider on days with fewer rows.
        </p>
      </Tile>

      <Tile
        span={6}
        title="Missing values"
        note={`Share of rows with no value, ${span}. Features within a point of their reference are left out.`}
        csv={() => ({
          name: csvName(model.id, "missing", dates[0] ?? "", dates.at(-1) ?? ""),
          rows: withMissing.flatMap((r) =>
            r.feature.series
              .filter((s) => inRange.has(s.date))
              .map((s) => ({ feature: r.feature.name, date: s.date, null_rate: s.nullRate, reference: r.feature.referenceNullRate })),
          ),
        })}
      >
        {withMissing.length === 0 ? (
          <p className={layout.empty}>Every feature is within a point of its reference missing rate.</p>
        ) : (
          <DailyChart
            kind="line"
            dates={dates}
            zero
            label={`Missing values by day for ${withMissing.length} features`}
            format={(v) => percent(v, 0)}
            series={withMissing.slice(0, 8).map((r, i) => ({
              id: r.feature.name,
              label: r.feature.name,
              slot: i + 1,
              values: dates.map((date) => byCell.get(`${r.feature.name}|${date}`)?.nullRate ?? null),
            }))}
          />
        )}
      </Tile>

      <Tile
        title="Features"
        note={`Latest test result, and how many days in ${span} each feature drifted.`}
        csv={() => ({
          name: csvName(model.id, "features", dates.at(-1) ?? ""),
          rows: sorted.map((r) => ({
            feature: r.feature.name,
            kind: r.feature.kind,
            test: r.feature.method,
            statistic: r.feature.latest.statistic,
            threshold: r.feature.threshold,
            drifted: r.feature.latest.drifted,
            psi: r.feature.latest.psi,
            drift_days: r.driftDays,
            null_rate: r.missing,
            reference_null_rate: r.feature.referenceNullRate,
          })),
        })}
      >
        <TableScroll label="Features">
          <table className={layout.table}>
            <thead>
              <tr>
                <SortableTh label="Feature" state={ariaSort("name")} onSort={() => toggle("name")} />
                <SortableTh label="Test" state={ariaSort("method")} onSort={() => toggle("method")} />
                <SortableTh label="Latest" numeric state={ariaSort("latest")} onSort={() => toggle("latest")} />
                <th scope="col" className={layout.num}>Threshold</th>
                <SortableTh label="PSI" numeric state={ariaSort("psi")} onSort={() => toggle("psi")} />
                <SortableTh label="Drift days" numeric state={ariaSort("driftDays")} onSort={() => toggle("driftDays")} />
                <SortableTh label="Missing" numeric state={ariaSort("missing")} onSort={() => toggle("missing")} />
                <th scope="col">Last 90 days</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const f = r.feature;
                const isSelected = selected?.feature.name === f.name;
                return (
                  <tr key={f.name} className={isSelected ? styles.selectedRow : undefined}>
                    <th scope="row">
                      <Link to={withParams(search, { feature: f.name })} aria-current={isSelected ? "true" : undefined}>
                        {f.name}
                      </Link>
                      <div className={styles.statNote}>{f.kind}</div>
                    </th>
                    <td>{METHOD_LABELS[f.method]}</td>
                    <td className={layout.num}>
                      {f.isPValue ? pValue(f.latest.statistic) : decimal(f.latest.statistic, 3)}
                      {f.latest.drifted && <div className={styles.statNote}>drifted</div>}
                    </td>
                    <td className={layout.num}>{f.isPValue ? `p < ${f.threshold}` : `≥ ${decimal(f.threshold, 2)}`}</td>
                    <td className={layout.num}>{decimal(f.latest.psi, 3)}</td>
                    <td className={layout.num}>{r.driftDays}</td>
                    <td className={layout.num}>
                      {percent(r.missing, 1)}
                      {r.missingJump !== null && Math.abs(r.missingJump) >= 0.005 && (
                        <div className={styles.statNote}>{points(r.missingJump)} vs reference</div>
                      )}
                    </td>
                    <td>
                      <DriftSpark feature={f} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
      </Tile>
    </div>
  );
}

function FeatureDetail({ row }: { row: FeatureRow }) {
  const f = row.feature;
  return (
    <Tile
      title={`Distribution of ${f.name}`}
      note={`Latest day against the reference data. ${METHOD_LABELS[f.method]}: ${
        f.isPValue ? pValue(f.latest.statistic) : decimal(f.latest.statistic, 3)
      } (${f.isPValue ? `drift below p ${f.threshold}` : `drift at ${decimal(f.threshold, 2)} or more`}), PSI ${decimal(f.latest.psi, 3)}.`}
      table={() => (
        <TableScroll label={`Distribution of ${f.name}`}>
          <table className={layout.table}>
            <thead>
              <tr>
                <th scope="col">Bin</th>
                <th scope="col" className={layout.num}>Reference</th>
                <th scope="col" className={layout.num}>Latest day</th>
                <th scope="col" className={layout.num}>Change</th>
              </tr>
            </thead>
            <tbody>
              {f.histogram.bins.map((bin, i) => {
                const ref = f.histogram.reference[i] ?? 0;
                const cur = f.histogram.current[i] ?? 0;
                return (
                  <tr key={bin}>
                    <th scope="row">{bin}</th>
                    <td className={layout.num}>{percent(ref)}</td>
                    <td className={layout.num}>{percent(cur)}</td>
                    <td className={layout.num}>{points(cur - ref)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
      )}
      csv={() => ({
        name: csvName(f.name, "histogram"),
        rows: f.histogram.bins.map((bin, i) => ({
          bin,
          reference: f.histogram.reference[i],
          current: f.histogram.current[i],
        })),
      })}
    >
      <Legend items={["barReference", "bar"]} labels={{ barReference: "Reference data", bar: "Latest day" }} />
      <HistogramCompare
        feature={f.name}
        bins={f.histogram.bins}
        reference={f.histogram.reference}
        current={f.histogram.current}
      />
    </Tile>
  );
}
