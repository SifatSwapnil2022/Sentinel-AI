import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import type { Model } from "../../data/schema";
import { withParams } from "../../filters/links";
import { csvName } from "../../lib/csv";
import { gapColor } from "../../lib/fleetStats";
import { count, percent, points, shortDate } from "../../lib/format";
import layout from "../layout.module.css";
import styles from "./Model.module.css";

type Segment = Model["segments"]["rows"][number];

/** Segments this small are left out of the ranking: their accuracy swings too much to compare. */
export const MIN_SEGMENT_ROWS = 200;

export function gap(s: Segment): number | null {
  return s.estimatedAccuracy === null || s.referenceAccuracy === null
    ? null
    : s.estimatedAccuracy - s.referenceAccuracy;
}

/** Segments ranked by how far their estimated accuracy fell below the reference. */
export function worstSegments(rows: readonly Segment[], limit = 8): Segment[] {
  return rows
    .filter((s) => s.nCurrent >= MIN_SEGMENT_ROWS && gap(s) !== null)
    .sort((a, b) => (gap(a) ?? 0) - (gap(b) ?? 0))
    .slice(0, limit);
}

export function SegmentsTab({ model }: { model: Model }) {
  const { search } = useLocation();
  const navigate = useNavigate();
  const { window, rows } = model.segments;
  const features = useMemo(() => [...new Set(rows.map((r) => r.feature))], [rows]);
  const worst = useMemo(() => worstSegments(rows), [rows]);
  const requested = new URLSearchParams(search).get("segment");
  const feature = features.includes(requested ?? "") ? (requested as string) : (worst[0]?.feature ?? features[0] ?? "");
  const segments = rows.filter((r) => r.feature === feature);
  const maxShare = Math.max(...segments.flatMap((s) => [s.shareReference, s.shareCurrent]), 0.01);
  const from = new Date(`${window.to}T00:00:00Z`);
  from.setUTCDate(from.getUTCDate() - 6);
  const span = `${shortDate(from.toISOString().slice(0, 10))} to ${shortDate(window.to)}, ${count(window.rows)} predictions`;
  const worstGap = Math.min(...worst.map((s) => gap(s) ?? 0), -0.01);

  const allRowsCsv = () => ({
    name: csvName(model.id, "segments", window.to),
    rows: rows.map((s) => ({
      feature: s.feature,
      segment: s.value,
      rows_reference: s.nReference,
      rows_current: s.nCurrent,
      share_reference: s.shareReference,
      share_current: s.shareCurrent,
      accuracy_reference: s.referenceAccuracy,
      accuracy_estimated: s.estimatedAccuracy,
      accuracy_measured: s.measuredAccuracy,
      labelled: s.labelled,
    })),
  });

  return (
    <div className={layout.grid}>
      <Tile
        span={5}
        title="Largest drops by segment"
        note={`Estimated minus reference accuracy, last 7 days. Segments under ${count(MIN_SEGMENT_ROWS)} rows are left out.`}
        csv={allRowsCsv}
      >
        {worst.length === 0 ? (
          <p className={layout.empty}>No segment is large enough to rank.</p>
        ) : (
          <TableScroll label="Largest drops by segment">
          <table className={layout.table}>
            <thead>
              <tr>
                <th scope="col">Segment</th>
                <th scope="col" className={layout.num}>Rows</th>
                <th scope="col">Against reference</th>
              </tr>
            </thead>
            <tbody>
              {worst.map((s) => {
                const g = gap(s) ?? 0;
                return (
                  <tr key={`${s.feature}|${s.value}`}>
                    <th scope="row">
                      <button
                        type="button"
                        className={layout.linkButton}
                        onClick={() => void navigate(withParams(search, { segment: s.feature }), { replace: true })}
                      >
                        {s.feature} = {s.value}
                      </button>
                    </th>
                    <td className={layout.num}>{count(s.nCurrent)}</td>
                    <td>
                      <span className={styles.bar} aria-hidden="true">
                        <span
                          style={{
                            width: `${Math.min(1, Math.abs(g) / Math.abs(worstGap)) * 100}%`,
                            background: g < 0 ? "var(--div-neg-3)" : "var(--div-pos-3)",
                          }}
                        />
                      </span>
                      {points(g)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </TableScroll>
        )}
      </Tile>

      <Tile
        span={7}
        title={`Accuracy by ${feature}`}
        note={span}
        controls={
          <label>
            <span className="visually-hidden">Feature</span>
            <select
              className={styles.select}
              value={feature}
              onChange={(e) => void navigate(withParams(search, { segment: e.target.value }), { replace: true })}
            >
              {features.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        }
        csv={allRowsCsv}
      >
        <TableScroll label={`Accuracy by ${feature}`}>
          <table className={layout.table}>
            <thead>
              <tr>
                <th scope="col">Segment</th>
                <th scope="col">Share of traffic</th>
                <th scope="col" className={layout.num}>Reference</th>
                <th scope="col" className={layout.num}>Estimated</th>
                <th scope="col" className={layout.num}>Change</th>
                <th scope="col" className={layout.num}>Measured</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((s) => {
                const g = gap(s);
                return (
                  <tr key={s.value}>
                    <th scope="row">{s.value}</th>
                    <td>
                      <div className={styles.shares}>
                        <span>
                          <span className={styles.bar} data-kind="reference" aria-hidden="true">
                            <span style={{ width: `${(s.shareReference / maxShare) * 100}%` }} />
                          </span>
                          {percent(s.shareReference, 0)} reference
                        </span>
                        <span>
                          <span className={styles.bar} aria-hidden="true">
                            <span style={{ width: `${(s.shareCurrent / maxShare) * 100}%` }} />
                          </span>
                          {percent(s.shareCurrent, 0)} now
                        </span>
                      </div>
                    </td>
                    <td className={layout.num}>{percent(s.referenceAccuracy)}</td>
                    <td className={layout.num}>{percent(s.estimatedAccuracy)}</td>
                    <td className={layout.num}>
                      {g === null ? (
                        "–"
                      ) : (
                        <span className={styles.delta} style={{ background: gapColor(g) }} data-strong={Math.abs(g) >= 0.05}>
                          {points(g)}
                        </span>
                      )}
                    </td>
                    <td className={layout.num}>
                      {s.measuredAccuracy === null ? (
                        <span className={styles.statNote}>{count(s.labelled)} labelled</span>
                      ) : (
                        <>
                          {percent(s.measuredAccuracy)}
                          <div className={styles.statNote}>{count(s.labelled)} labelled</div>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
        <p className={styles.note}>
          Reference accuracy is measured on the labelled reference data. Estimated accuracy comes from
          the model's calibrated confidence on the last 7 days; measured accuracy appears once a segment
          has 30 labelled rows.
        </p>
      </Tile>
    </div>
  );
}
