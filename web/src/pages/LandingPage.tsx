import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router";
import { Wordmark } from "../app/Wordmark";
import { AccuracyChart } from "../charts/AccuracyChart";
import { Legend } from "../components/Legend";
import { RangeGlyph } from "../components/RangeGlyph";
import { incidentQuery, useFleet, useModel } from "../data/api";
import type { Fleet } from "../data/schema";
import { conditionText } from "../lib/describe";
import { decimal, longDate, percent, percentRange, shortDate } from "../lib/format";
import { brokenLink, hiddenSegment, labelGap, missingCase, quietModels } from "../lib/story";
import { ArchitectureFlow } from "./landing/ArchitectureFlow";
import styles from "./LandingPage.module.css";

const REPO = "https://github.com/SifatSwapnil2022/Sentinel-AI";
const SOURCES = {
  chargebacks:
    "https://www.chargebackgurus.com/blog/dont-run-out-the-clock-understanding-chargeback-time-limits",
  degradation: "https://pmc.ncbi.nlm.nih.gov/articles/PMC9270447/",
  cbpe: "https://nannyml.readthedocs.io/en/main/how_it_works/performance_estimation.html",
};

/** The demo incident of a given kind, if the data has one. */
function alertOf(fleet: Fleet | undefined, kind: string) {
  return fleet?.alerts.find((a) => a.kind === kind);
}

function useOptionalIncident(id: string | undefined) {
  return useQuery({ ...incidentQuery(id ?? ""), enabled: id !== undefined });
}

export function LandingPage() {
  useEffect(() => {
    document.title = "Sentinel: model monitoring when labels come late";
  }, []);

  const fleet = useFleet();
  const dropAlert = alertOf(fleet.data, "estimate_drop");
  const conceptAlert = alertOf(fleet.data, "concept_drift");
  const linkAlert = alertOf(fleet.data, "multivariate");
  const missingAlert = alertOf(fleet.data, "data_quality");
  const caseModel = useModel(dropAlert?.modelId ?? "fraud-screen");
  const concept = useOptionalIncident(conceptAlert?.id);
  const relation = useOptionalIncident(linkAlert?.id);
  const missingIncident = useOptionalIncident(missingAlert?.id);

  const gap =
    fleet.data && caseModel.data
      ? labelGap(fleet.data, caseModel.data.labelDelayDays, caseModel.data.id)
      : null;
  const segment = concept.data ? hiddenSegment(concept.data) : null;
  const link = relation.data ? brokenLink(relation.data) : null;
  const quiet = fleet.data ? quietModels(fleet.data) : [];
  const missing = missingIncident.data ? missingCase(missingIncident.data) : null;
  const modelCount = fleet.data?.models.length ?? 8;

  return (
    <div className={styles.page}>
      <a className={styles.skip} href="#main">
        Skip to content
      </a>
      <header className={styles.top}>
        <div className={styles.topInner}>
          <Wordmark to="/" label="Sentinel home" />
          <nav aria-label="Sections" className={styles.sections}>
            <a href="#problem">Problem</a>
            <a href="#approach">Checks</a>
            <a href="#how">Architecture</a>
            <a href="#evidence">Testing</a>
            <a href={REPO}>GitHub</a>
          </nav>
          <Link to="/overview" className={styles.primary}>
            Open the dashboard
          </Link>
        </div>
      </header>

      <main id="main" tabIndex={-1} className={styles.main}>
        {/* ------------------------------------------------------------------ hero */}
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroText}>
            <h1 id="hero-title" className={styles.heroTitle}>
              Model monitoring for when the labels arrive late.
            </h1>
            <p className={styles.lede}>
              A fraud model learns it was wrong when the chargeback comes in, a credit model when the
              loan defaults. That can take months, and until then the accuracy on a dashboard is old
              news. Sentinel estimates each day's accuracy from the model's own scores, checks the
              estimate once labels arrive, and shows which part of the traffic a drop came from.
            </p>
            <p className={styles.lede}>
              The demo runs {modelCount} models on 90 days of synthetic traffic, through the same
              analysis code as the service.
            </p>
            <div className={styles.actions}>
              <Link to="/overview" className={styles.primary}>
                Open the live dashboard
              </Link>
              <a href={REPO} className={styles.secondary}>
                Source on GitHub
              </a>
            </div>
          </div>

          {gap && (
            <figure className={styles.readings} aria-labelledby="readings-caption">
              <div className={styles.reading}>
                <p className={styles.readingLabel}>Labels say</p>
                <p className={styles.readingValue}>{percent(gap.measured)}</p>
                <p className={styles.readingNote}>
                  measured on {shortDate(gap.measuredOn)}, the last day most labels are in
                </p>
              </div>
              <div className={styles.reading}>
                <p className={styles.readingLabel}>Sentinel estimates</p>
                <p className={`${styles.readingValue} ${styles.estimate}`}>
                  {percent(gap.estimate)}
                </p>
                <p className={styles.readingNote}>
                  today, likely {percentRange(gap.lower, gap.upper)}
                </p>
                <RangeGlyph
                  value={gap.estimate}
                  lower={gap.lower}
                  upper={gap.upper}
                  measured={gap.measured}
                  domain={glyphDomain(gap.lower, gap.upper, gap.measured)}
                  width={260}
                  label={gap.modelId}
                />
              </div>
              <figcaption id="readings-caption" className={styles.readingCaption}>
                <Link to={`/models/${gap.modelId}`}>{gap.modelId}</Link>, a fraud model in the
                demo. The estimate dropped on {shortDate(gap.flaggedOn)} and an incident opened the
                same day. Chargebacks for that day should be complete around{" "}
                {longDate(gap.labelsCompleteOn)}.
              </figcaption>
            </figure>
          )}
        </section>

        {caseModel.data && (
          <section className={styles.caseChart} aria-labelledby="case-title">
            <div className={styles.caseHead}>
              <h2 id="case-title" className={styles.h3}>
                {caseModel.data.id}, last {caseModel.data.days.length} days
              </h2>
              <p className={styles.muted}>
                The band is the estimate for each day. Rings are accuracy measured from labels; the
                strip underneath shows how many labels each day has so far.
              </p>
            </div>
            <Legend items={["band", "ring", "reference"]} />
            <AccuracyChart
              days={caseModel.data.days}
              metric="accuracy"
              reference={caseModel.data.referenceMetrics.accuracy}
              label="Accuracy"
            />
          </section>
        )}

        {/* --------------------------------------------------------------- problem */}
        <section id="problem" className={styles.section} aria-labelledby="problem-title">
          <div className={styles.sectionHead}>
            <h2 id="problem-title">Why models fail quietly</h2>
            <p className={styles.sectionLede}>
              When the data changes, a model keeps returning answers. Nothing errors. The common
              checks either wait for labels or watch the inputs, and each misses cases.
            </p>
          </div>
          <ol className={styles.problems}>
            <li>
              <h3>Labels arrive late</h3>
              <p>
                Card networks give cardholders up to{" "}
                <a href={SOURCES.chargebacks}>120 days to dispute a charge</a>. Until then a fraud
                model's real accuracy is unknown, and so is a credit model's until loans come due.
              </p>
            </li>
            <li>
              <h3>Input drift is the wrong alarm</h3>
              <p>
                Drift tests fire on shifts the model copes with, such as seasonal volume. They don't
                fire when the same inputs start leading to different outcomes, and label-free
                estimators <a href={SOURCES.cbpe}>assume that never happens</a>.
              </p>
            </li>
            <li>
              <h3>Averages hide the break</h3>
              <p>
                {segment ? (
                  <>
                    In the demo, measured accuracy fell {points(segment.overallDrop)} overall and{" "}
                    {points(segment.segmentDrop)} where{" "}
                    {segment.conditions.map((c) => conditionText(c.feature, c.value)).join(" and ")}
                    . Overall, that looks like noise.
                  </>
                ) : (
                  "A small drop overall can be a large one for a single region or customer group, and the overall number looks like noise."
                )}
              </p>
            </li>
          </ol>
          <p className={styles.stat}>
            Across 32 real-world datasets and four model families, accuracy degraded over time in
            91% of model and dataset pairs (
            <a href={SOURCES.degradation}>Vela et al., Scientific Reports, 2022</a>).
          </p>
        </section>

        {/* -------------------------------------------------------------- approach */}
        <section id="approach" className={styles.section} aria-labelledby="approach-title">
          <div className={styles.sectionHead}>
            <h2 id="approach-title">What it checks</h2>
            <p className={styles.sectionLede}>
              Five checks run on every model each day, and LLM apps get their own. An incident opens when one fails two days in
              a row and closes after seven quiet days. The examples link to pages in the demo.
            </p>
          </div>
          <ol className={styles.steps}>
            <li className={styles.step}>
              <div>
                <h3>Estimate accuracy without labels</h3>
                <p className={styles.method}>Calibrated confidence-based performance estimation</p>
              </div>
              <p>
                After calibration, a score of 0.8 means right about 80% of the time. Summing over a
                day's predictions gives an expected confusion matrix, so accuracy, precision, recall
                and F1 each get an estimate and a likely range without any labels.
              </p>
              <p className={styles.proof}>
                {gap ? (
                  <>
                    {gap.modelId}: the estimate fell to {percent(gap.estimate)} on{" "}
                    {shortDate(gap.flaggedOn)}, when those days had almost no labels.{" "}
                    <Link to={`/models/${gap.modelId}`}>See the model</Link>
                  </>
                ) : (
                  <Link to="/overview">See the dashboard</Link>
                )}
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Check the estimate when labels land</h3>
                <p className={styles.method}>Rolling-week comparison, reference error included</p>
              </div>
              <p>
                Once labels arrive, measured accuracy over the past week is compared with the
                estimate for the same rows. Measured below the range means the inputs now lead to
                different outcomes, which the estimate cannot see by itself.
              </p>
              <p className={styles.proof}>
                {segment ? (
                  <>
                    Traced to{" "}
                    {segment.conditions.map((c) => conditionText(c.feature, c.value)).join(" and ")}
                    . <Link to={`/incidents/${segment.incidentId}`}>See the incident</Link>
                  </>
                ) : (
                  <Link to="/incidents">See incidents</Link>
                )}
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Watch how features move together</h3>
                <p className={styles.method}>PCA reconstruction error with a held-out band</p>
              </div>
              <p>
                PCA fitted on reference data compresses and rebuilds each day's rows. When features
                stop moving together the way they used to, the rebuild error rises, even if each
                feature looks normal on its own.
              </p>
              <p className={styles.proof}>
                {link ? (
                  <>
                    Correlation of {link.a} and {link.b}: {decimal(link.before)} to{" "}
                    {decimal(link.after)}; no single feature drifted.{" "}
                    <Link to={`/incidents/${link.incidentId}`}>See the incident</Link>
                  </>
                ) : (
                  <Link to="/incidents">See incidents</Link>
                )}
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Catch missing values</h3>
                <p className={styles.method}>Null rate against the reference, per feature</p>
              </div>
              <p>
                A feature that starts arriving empty is a pipeline problem, not drift. It gets its
                own check because the accuracy estimate can move either way when it happens.
              </p>
              <p className={styles.proof}>
                {missing ? (
                  <>
                    {missing.modelId}: {missing.feature} empty for {percent(missing.nullRate, 0)} of rows,
                    and the estimate went {missing.estimateChange >= 0 ? "up" : "down"}{" "}
                    {Math.abs(missing.estimateChange * 100).toFixed(1)} points.{" "}
                    <Link to={`/incidents/${missing.incidentId}`}>See the incident</Link>
                  </>
                ) : (
                  <Link to="/incidents">See incidents</Link>
                )}
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Watch LLM apps too</h3>
                <p className={styles.method}>Answers checked against the retrieved context</p>
              </div>
              <p>
                For a retrieval-augmented assistant, each answer is checked for sentences and numbers
                the retrieved article doesn't contain, and for personal data. Latency, errors,
                thumbs-down and topic mix are tracked per prompt version.
              </p>
              <p className={styles.proof}>
                A prompt that invented fees, a provider slowdown and a phone-number leak.{" "}
                <Link to="/llm">See the LLM page</Link>
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Find the segment behind a drop</h3>
                <p className={styles.method}>Shift-share decomposition, ranked by confident drop</p>
              </div>
              <p>
                A drop is split into two parts: accuracy fell within a segment, or more traffic came
                from a segment that was always harder. Only segments whose drop is clear of sampling
                noise are listed.
              </p>
              <p className={styles.proof}>
                {quiet.length > 0 ? (
                  <>
                    {quiet.join(", ")}: no incident in {fleet.data?.windowDays ?? 90} days.{" "}
                    <Link to={`/models/${quiet[0]}`}>See the model</Link>
                  </>
                ) : (
                  <Link to="/overview">See the dashboard</Link>
                )}
              </p>
            </li>
          </ol>
        </section>

        {/* ----------------------------------------------------------- how it works */}
        <section id="how" className={styles.section} aria-labelledby="how-title">
          <div className={styles.sectionHead}>
            <h2 id="how-title">From a model server to an incident</h2>
            <p className={styles.sectionLede}>
              Logging a prediction puts it in a memory buffer and returns. If Sentinel is slow or
              down, the model server carries on and the buffer drops the oldest rows.
            </p>
          </div>
          <ArchitectureFlow />
          <pre className={styles.code} tabIndex={0} aria-label="Python SDK example">
            <code>{`from sentinel_sdk import Sentinel

sentinel = Sentinel(url, api_key, model_id="fraud-screen")

# in the request handler: microseconds, never raises
sentinel.log_prediction(request_id, features, score=0.91)

# weeks later, when the chargeback window closes
sentinel.log_label(request_id, 0)`}</code>
          </pre>
        </section>

        {/* -------------------------------------------------------------- evidence */}
        <section id="evidence" className={styles.section} aria-labelledby="evidence-title">
          <div className={styles.sectionHead}>
            <h2 id="evidence-title">How it's tested</h2>
            <p className={styles.sectionLede}>
              A monitor that alerts too often gets muted, so false alarms are tested as hard as
              detection.
            </p>
          </div>
          <dl className={styles.evidence}>
            <div>
              <dt>Against reference implementations</dt>
              <dd>
                Accuracy, precision, recall and F1 estimates match NannyML to within 1e-9, and the
                drift statistics match Evidently.
              </dd>
            </div>
            <div>
              <dt>False alarms</dt>
              <dd>
                Three random seeds, {modelCount} models, 90 days each: no incident before an injected
                change or on a model without one. On clean data the relationship check fires on
                0.55% of days.
              </dd>
            </div>
            <div>
              <dt>Detection</dt>
              <dd>
                In the same runs every injected problem opened an incident one to four days after it
                started, and the temporary shift closed by itself once traffic returned to normal.
              </dd>
            </div>
            <div>
              <dt>Live pipeline</dt>
              <dd>
                A test in CI sends four of the demo models' traffic through the API, Redis, the
                worker and Postgres, and checks the results equal the static demo exactly.
              </dd>
            </div>
            <div>
              <dt>Throughput</dt>
              <dd>One API process accepted about 20,000 predictions a second in a local load test.</dd>
            </div>
            <div>
              <dt>Accessibility</dt>
              <dd>
                Every chart has a table view. Browser tests run axe on each page in both themes and
                fail on serious violations.
              </dd>
            </div>
          </dl>
          <p className={styles.muted}>
            The reasoning behind each design choice is in the{" "}
            <a href={`${REPO}/tree/main/docs/adr`}>architecture decision records</a>.
          </p>
        </section>

        {/* ----------------------------------------------------------------- start */}
        <section id="start" className={styles.section} aria-labelledby="start-title">
          <div className={styles.sectionHead}>
            <h2 id="start-title">Run it</h2>
            <p className={styles.sectionLede}>
              The stack runs on one machine with Docker. <code>make demo</code> streams the demo
              traffic in through the SDK, so incidents open on the real services rather than from
              static files.
            </p>
          </div>
          <pre className={styles.code} tabIndex={0} aria-label="Commands to run Sentinel">
            <code>{`git clone ${REPO}.git && cd Sentinel-AI
make up      # Postgres, Redis, API, worker, dashboard on :8080
make demo    # stream the demo scenarios through the SDK`}</code>
          </pre>
          <ul className={styles.links}>
            <li>
              <a href={`${REPO}/blob/main/docs/api.md`}>API reference</a>
            </li>
            <li>
              <a href={`${REPO}/tree/main/sdk/python`}>Python SDK</a>
            </li>
            <li>
              <a href={`${REPO}/tree/main/docs/adr`}>Design decisions</a>
            </li>
          </ul>

          <div className={styles.limits}>
            <h3>What it doesn't do yet</h3>
            <ul>
              <li>Performance estimation covers binary classifiers; multiclass and regression are next.</li>
              <li>The label check needs labels to fire, so it confirms a problem rather than predicting it.</li>
              <li>Segments are searched one and two features deep, not further.</li>
              <li>There is no login or per-team access control; it is meant to run inside a private network.</li>
            </ul>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>Sentinel is open source under the MIT licence. Built by Md Sifatullah Sheikh.</p>
        <p className={styles.muted}>
          Demo traffic is synthetic. The analysis is the same code the service runs.
        </p>
        <ul className={styles.links}>
          <li>
            <a href={REPO}>GitHub</a>
          </li>
          <li>
            <a href="https://www.linkedin.com/in/mdsifatullahsheikh">LinkedIn</a>
          </li>
        </ul>
      </footer>
    </div>
  );
}

function points(delta: number): string {
  return `${(delta * 100).toFixed(1)} points`;
}

/** An axis that holds the range and the measured value with some room, rounded to 5 points. */
function glyphDomain(lower: number, upper: number, measured: number): [number, number] {
  const lo = Math.max(0, Math.floor((Math.min(lower, measured) - 0.03) * 20) / 20);
  const hi = Math.min(1, Math.ceil((Math.max(upper, measured) + 0.03) * 20) / 20);
  return [lo, hi];
}
