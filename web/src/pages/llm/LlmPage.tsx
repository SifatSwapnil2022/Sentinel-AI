import { Fragment } from "react";
import { Link, useLocation } from "react-router";
import { DailyChart } from "../../charts/DailyChart";
import { QueryState } from "../../components/QueryState";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { useLlm } from "../../data/api";
import type { Llm, LlmRule } from "../../data/schema";
import { dateRange, inRange, previousRange } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { withParams } from "../../filters/links";
import { useFilters } from "../../filters/useFilters";
import { csvName } from "../../lib/csv";
import { compact, count, percent, points, shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import modelStyles from "../model/Model.module.css";
import styles from "./Llm.module.css";

export const RULE_LABELS: Record<LlmRule, string> = {
  pii_leak: "Personal data in answers",
  unsupported_answers: "Unsupported answers",
  errors: "Errors and timeouts",
  latency: "Latency",
  negative_feedback: "Thumbs-down",
  topic_shift: "Topic mix",
};

const RULE_TEXT: Record<LlmRule, string> = {
  pii_leak: "An answer contained an email address, phone number or card number. One is enough.",
  unsupported_answers:
    "More answers than usual contain a sentence the retrieved articles don't support, or a number they don't contain.",
  errors: "More calls than usual failed or timed out.",
  latency: "p95 latency reached 1.5 times its usual level.",
  negative_feedback: "More users than usual gave a thumbs-down.",
  topic_shift: "What people ask about moved away from the usual mix (Jensen–Shannon distance 0.15 or more).",
};

export function LlmPage() {
  useTitle("LLM apps");
  const llm = useLlm();
  return (
    <>
      <FilterBar scope="model" />
      <QueryState query={llm} subject="LLM monitoring">
        {(data) => <LlmView llm={data} />}
      </QueryState>
    </>
  );
}

function LlmView({ llm }: { llm: Llm }) {
  const { filters } = useFilters();
  const { search } = useLocation();
  const range = dateRange(filters, llm.today);
  const before = previousRange(range);
  const days = llm.days.filter((d) => inRange(d.date, range));
  const previous = llm.days.filter((d) => inRange(d.date, before));
  const dates = days.map((d) => d.date);
  const span = `${shortDate(range.from)} to ${shortDate(range.to)}`;
  const ref = llm.reference;
  const open = llm.incidents.filter((i) => i.status === "open");
  const shown = llm.incidents.filter((i) => i.openedOn <= range.to && (i.resolvedOn ?? llm.today) >= range.from);
  const worst = [...open].sort((a, b) => Number(b.severity === "critical") - Number(a.severity === "critical"))[0];
  const selectedId = new URLSearchParams(search).get("incident") ?? worst?.id;
  const selected = llm.incidents.find((i) => i.id === selectedId);

  const sum = (rows: typeof days, f: (d: (typeof days)[number]) => number) => rows.reduce((s, d) => s + f(d), 0);
  const requests = sum(days, (d) => d.requests);
  const weighted = (rows: typeof days, f: (d: (typeof days)[number]) => number) =>
    sum(rows, (d) => f(d) * d.requests) / Math.max(sum(rows, (d) => d.requests), 1);
  const unsupported = weighted(days, (d) => d.unsupportedRate);
  const prevUnsupported = previous.length ? weighted(previous, (d) => d.unsupportedRate) : null;
  const versions = [...new Set(days.flatMap((d) => Object.keys(d.versions)))].sort();
  const compare = filters.compare && previous.length === days.length;

  const topicNow: Record<string, number> = {};
  for (const d of days) for (const [k, v] of Object.entries(d.topics)) topicNow[k] = (topicNow[k] ?? 0) + v;
  const refTotal = Object.values(ref.topics).reduce((a, b) => a + b, 0);
  const nowTotal = Object.values(topicNow).reduce((a, b) => a + b, 0);
  const topics = Object.keys(ref.topics)
    .map((t) => ({ topic: t, reference: (ref.topics[t] ?? 0) / refTotal, now: (topicNow[t] ?? 0) / Math.max(nowTotal, 1) }))
    .sort((a, b) => b.now - b.reference - (a.now - a.reference));
  const maxShare = Math.max(...topics.flatMap((t) => [t.reference, t.now]), 0.01);

  const line = (id: string, label: string, f: (d: (typeof days)[number]) => number) => ({
    id,
    label,
    values: days.map(f),
  });

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <div className={layout.titleRow}>
          <h1 className={layout.title}>{llm.app.name}</h1>
          <span className={layout.version}>{llm.app.model.name}</span>
          <StatusMark status={open.some((i) => i.severity === "critical") ? "critical" : open.length ? "warning" : "healthy"} />
        </div>
        <p className={layout.lead}>
          {llm.app.description} Normal behaviour is taken from {shortDate(llm.app.referenceWindow.from)} to{" "}
          {shortDate(llm.app.referenceWindow.to)}.
        </p>
        {open.map((i) => (
          <p key={i.id} className={modelStyles.banner} data-severity={i.severity}>
            <StatusMark status={i.severity} compact />
            <span>
              Open since {shortDate(i.openedOn)}:{" "}
              <Link to={withParams(search, { incident: i.id })}>{i.title}</Link>
            </span>
          </p>
        ))}
      </header>

      <dl className={modelStyles.stats}>
        <div>
          <dt>Requests</dt>
          <dd>
            <span className={modelStyles.statValue}>{compact(requests)}</span>
            <span className={modelStyles.statNote}>{span}</span>
          </dd>
        </div>
        <div>
          <dt>Unsupported answers</dt>
          <dd>
            <span className={modelStyles.statValue}>{percent(unsupported)}</span>
            <span className={modelStyles.statNote}>
              {compare && prevUnsupported !== null
                ? `${points(unsupported - prevUnsupported)} on previous period`
                : `usually ${percent(ref.unsupportedRate)}`}
            </span>
          </dd>
        </div>
        <div>
          <dt>Answers with personal data</dt>
          <dd>
            <span className={modelStyles.statValue}>{count(sum(days, (d) => d.piiAnswers))}</span>
            <span className={modelStyles.statNote}>should be 0</span>
          </dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd>
            <span className={modelStyles.statValue}>${sum(days, (d) => d.costUsd).toFixed(2)}</span>
            <span className={modelStyles.statNote}>
              {compact(sum(days, (d) => d.inputTokens + d.outputTokens))} tokens
            </span>
          </dd>
        </div>
      </dl>

      <div className={layout.grid}>
        <Tile
          span={7}
          title="Unsupported answers"
          note={`Share of answers with a sentence the retrieved articles don't support, ${span}. Usually ${percent(ref.unsupportedRate)}.`}
          csv={() => ({
            name: csvName(llm.app.id, "daily", range.from, range.to),
            rows: days.map((d) => ({
              date: d.date,
              requests: d.requests,
              unsupported_rate: d.unsupportedRate,
              error_rate: d.errorRate,
              pii_answers: d.piiAnswers,
              negative_rate: d.negativeRate,
              p95_latency_ms: d.p95LatencyMs,
              cost_usd: d.costUsd,
              topic_shift: d.topicShift,
              signals: d.signals.join(" "),
            })),
          })}
        >
          <DailyChart
            kind="line"
            zero
            dates={dates}
            series={[line("unsupported", "Unsupported answers", (d) => d.unsupportedRate)]}
            compare={compare ? previous.map((d) => d.unsupportedRate) : undefined}
            format={(v) => percent(v, 0)}
            label={`Unsupported answers by day, ${span}`}
          />
        </Tile>
        <Tile span={5} title="Requests by prompt version" note="Shows when a new prompt was rolled out or rolled back.">
          <DailyChart
            kind="bar"
            stacked
            dates={dates}
            series={versions.map((v, i) => ({
              id: v,
              label: `Prompt ${v}`,
              slot: i + 1,
              values: days.map((d) => d.versions[v]?.requests ?? null),
            }))}
            format={(v) => count(Math.round(v))}
            label={`Requests by prompt version, ${span}`}
          />
        </Tile>
        <Tile span={4} title="p95 latency" note={`Usually ${Math.round(ref.p95LatencyMs)} ms.`}>
          <DailyChart
            kind="line"
            dates={dates}
            series={[line("p95", "p95 latency", (d) => d.p95LatencyMs)]}
            compare={compare ? previous.map((d) => d.p95LatencyMs) : undefined}
            format={(v) => `${(v / 1000).toFixed(1)} s`}
            label={`p95 latency by day, ${span}`}
          />
        </Tile>
        <Tile span={4} title="Errors and timeouts" note={`Usually ${percent(ref.errorRate)}.`}>
          <DailyChart
            kind="line"
            zero
            dates={dates}
            series={[line("errors", "Errors and timeouts", (d) => d.errorRate)]}
            format={(v) => percent(v, 1)}
            label={`Error rate by day, ${span}`}
          />
        </Tile>
        <Tile span={4} title="Thumbs-down" note={`Share of rated answers. Usually ${percent(ref.negativeRate, 0)}.`}>
          <DailyChart
            kind="line"
            zero
            dates={dates}
            series={[line("negative", "Thumbs-down", (d) => d.negativeRate)]}
            format={(v) => percent(v, 0)}
            label={`Thumbs-down rate by day, ${span}`}
          />
        </Tile>

        <Tile span={6} title="What people ask about" note={`Share of requests by topic, ${span}, against the reference weeks.`}>
          <TableScroll label="Topics">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th scope="col">Share</th>
                  <th scope="col" className={layout.num}>Change</th>
                </tr>
              </thead>
              <tbody>
                {topics.map((t) => (
                  <tr key={t.topic}>
                    <th scope="row">{t.topic}</th>
                    <td>
                      <div className={modelStyles.shares}>
                        <span>
                          <span className={modelStyles.bar} data-kind="reference" aria-hidden="true">
                            <span style={{ width: `${(t.reference / maxShare) * 100}%` }} />
                          </span>
                          {percent(t.reference, 0)} usually
                        </span>
                        <span>
                          <span className={modelStyles.bar} aria-hidden="true">
                            <span style={{ width: `${(t.now / maxShare) * 100}%` }} />
                          </span>
                          {percent(t.now, 0)} now
                        </span>
                      </div>
                    </td>
                    <td className={layout.num}>{points(t.now - t.reference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Tile>

        <Tile span={6} title="Prompt versions" note="Every version that served traffic, over its whole life.">
          <TableScroll label="Prompt versions">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Served</th>
                  <th scope="col" className={layout.num}>Requests</th>
                  <th scope="col" className={layout.num}>Unsupported</th>
                  <th scope="col" className={layout.num}>Thumbs-down</th>
                  <th scope="col" className={layout.num}>Cost per 1k</th>
                </tr>
              </thead>
              <tbody>
                {llm.versions.map((v) => (
                  <tr key={v.version}>
                    <th scope="row">{v.version}</th>
                    <td>
                      {shortDate(v.from)} to {shortDate(v.to)}
                    </td>
                    <td className={layout.num}>{compact(v.requests)}</td>
                    <td className={layout.num}>{percent(v.unsupportedRate)}</td>
                    <td className={layout.num}>{percent(v.negativeRate, 0)}</td>
                    <td className={layout.num}>${v.costPer1k.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Tile>

        <Tile title="Incidents" note={`Touching ${span}. Select one to see what fired and example answers.`}>
          {shown.length === 0 ? (
            <p className={layout.empty}>No incidents in these dates.</p>
          ) : (
            <TableScroll label="LLM incidents">
              <table className={layout.table}>
                <thead>
                  <tr>
                    <th scope="col">Incident</th>
                    <th scope="col">Checks that failed</th>
                    <th scope="col">Severity</th>
                    <th scope="col">Opened</th>
                    <th scope="col">Resolved</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((i) => (
                    <tr key={i.id} className={i.id === selected?.id ? modelStyles.selectedRow : undefined}>
                      <th scope="row">
                        <Link to={withParams(search, { incident: i.id })} aria-current={i.id === selected?.id ? "true" : undefined}>
                          {i.title}
                        </Link>
                      </th>
                      <td>{i.rules.map((r) => RULE_LABELS[r]).join(", ")}</td>
                      <td>
                        <StatusMark status={i.severity} />
                      </td>
                      <td>{shortDate(i.openedOn)}</td>
                      <td>{i.resolvedOn ? shortDate(i.resolvedOn) : "Open"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
        </Tile>

        {selected && (
          <Tile title={selected.title} note={`${shortDate(selected.openedOn)} to ${selected.resolvedOn ? shortDate(selected.resolvedOn) : "now"}, ${selected.days} days with failing checks.`}>
            <ul className={styles.rules}>
              {selected.rules.map((r) => (
                <li key={r}>
                  <strong>{RULE_LABELS[r]}.</strong> {RULE_TEXT[r]}
                </li>
              ))}
            </ul>
            {selected.examples.length > 0 && (
              <div className={styles.examples}>
                {selected.examples.map((e, k) => (
                  <Fragment key={k}>
                    <article className={styles.example} aria-label={`Example ${k + 1}`}>
                      <p className={styles.meta}>
                        Prompt {e.promptVersion}, {e.topic}
                        {e.feedback === -1 ? ", user gave a thumbs-down" : ""}
                      </p>
                      <p>
                        <span className={styles.role}>Question</span> {e.question}
                      </p>
                      <p className={styles.context}>
                        <span className={styles.role}>Retrieved</span> {e.context}
                      </p>
                      <p>
                        <span className={styles.role}>Answer</span> <Highlighted text={e.answer} marks={[...e.unsupported, ...e.pii]} />
                      </p>
                    </article>
                  </Fragment>
                ))}
                <p className={modelStyles.note}>
                  Highlighted: sentences the retrieved article doesn't support, and personal data.
                </p>
              </div>
            )}
          </Tile>
        )}
      </div>
    </div>
  );
}

/** Text with the given passages marked, for showing exactly what a check flagged. */
export function Highlighted({ text, marks }: { text: string; marks: string[] }) {
  const found = marks.filter((m) => m && text.includes(m)).sort((a, b) => text.indexOf(a) - text.indexOf(b));
  const parts: { text: string; mark: boolean }[] = [];
  let at = 0;
  for (const m of found) {
    const i = text.indexOf(m, at);
    if (i < 0) continue;
    if (i > at) parts.push({ text: text.slice(at, i), mark: false });
    parts.push({ text: m, mark: true });
    at = i + m.length;
  }
  if (at < text.length) parts.push({ text: text.slice(at), mark: false });
  return (
    <>
      {parts.map((p, i) => (p.mark ? <mark key={i}>{p.text}</mark> : <Fragment key={i}>{p.text}</Fragment>))}
    </>
  );
}
