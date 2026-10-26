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
import { brokenLink, hiddenSegment, labelGap, quietModels } from "../lib/story";
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
    document.title = "Sentinel: know a model is failing before its labels arrive";
  }, []);

  const fleet = useFleet();
  const dropAlert = alertOf(fleet.data, "estimate_drop");
  const conceptAlert = alertOf(fleet.data, "concept_drift");
  const linkAlert = alertOf(fleet.data, "multivariate");
  const caseModel = useModel(dropAlert?.modelId ?? "fraud-screen");
  const concept = useOptionalIncident(conceptAlert?.id);
  const relation = useOptionalIncident(linkAlert?.id);

  const gap =
    fleet.data && caseModel.data
      ? labelGap(fleet.data, caseModel.data.labelDelayDays, caseModel.data.id)
      : null;
  const segment = concept.data ? hiddenSegment(concept.data) : null;
  const link = relation.data ? brokenLink(relation.data) : null;
  const quiet = fleet.data ? quietModels(fleet.data) : [];

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
            <a href="#approach">Approach</a>
            <a href="#how">How it works</a>
            <a href="#evidence">Evidence</a>
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
              Know a model is failing before its labels arrive.
            </h1>
            <p className={styles.lede}>
              Most production models learn whether they were right weeks later: a chargeback, a
              loan default, a cancelled plan. Until then, the accuracy on the dashboard describes
              last month's model. Sentinel estimates accuracy the day predictions are made, checks
              the estimate when labels land, and names the traffic behind a drop.
            </p>
            <div className={styles.actions}>
              <Link to="/overview" className={styles.primary}>
                Open the live dashboard
              </Link>
              <a href={REPO} className={styles.secondary}>
                Read the code
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
                demo. Its accuracy fell on {shortDate(gap.flaggedOn)}, and Sentinel opened an
                incident that day. Chargebacks for that day will be complete around{" "}
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
                The band is what Sentinel estimated each day. Rings appear only as labels come in,
                and the strip below shows how few have.
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
              A model doesn't crash when the world changes. It keeps answering, a little more
              wrong each week, and the usual tools are built to notice too late or to notice the
              wrong thing.
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
                Drift tests fire on seasonal shifts the model handles fine. They can't see the
                failure that matters most: the same inputs now leading to different outcomes.
                Even label-free estimators{" "}
                <a href={SOURCES.cbpe}>assume that doesn't happen</a>.
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
                    . The overall number looks like noise.
                  </>
                ) : (
                  "A small drop overall can be a collapse for one region or customer group, and the overall number looks like noise."
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
            <h2 id="approach-title">What Sentinel does about it</h2>
            <p className={styles.sectionLede}>
              Four checks, each covering a gap the others leave. Every example below is a live
              page in the demo, computed by the same engine the service runs.
            </p>
          </div>
          <ol className={styles.steps}>
            <li className={styles.step}>
              <div>
                <h3>Estimate accuracy without labels</h3>
                <p className={styles.method}>Calibrated confidence-based performance estimation</p>
              </div>
              <p>
                Calibrated scores give an expected confusion matrix, so accuracy, precision,
                recall and F1 come with a likely range from the first day.
              </p>
              <p className={styles.proof}>
                {gap ? (
                  <>
                    {gap.modelId}: estimate fell to {percent(gap.estimate)} from{" "}
                    {shortDate(gap.flaggedOn)}, with almost no labels for those days.{" "}
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
                Measured accuracy is compared with the estimate on the same rows. A gap outside the
                range means inputs now lead to different outcomes: the case estimation alone can't
                see.
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
                A model fitted on reference data reconstructs each day. When relationships between
                features change, error rises, even if every feature looks normal on its own.
              </p>
              <p className={styles.proof}>
                {link ? (
                  <>
                    Correlation of {link.a} and {link.b}: {decimal(link.before)} to{" "}
                    {decimal(link.after)}, with no single-feature alarm.{" "}
                    <Link to={`/incidents/${link.incidentId}`}>See the incident</Link>
                  </>
                ) : (
                  <Link to="/incidents">See incidents</Link>
                )}
              </p>
            </li>
            <li className={styles.step}>
              <div>
                <h3>Name the segment, and stay quiet otherwise</h3>
                <p className={styles.method}>Shift-share decomposition, ranked by confident drop</p>
              </div>
              <p>
                A drop is split into "worse in this segment" and "more traffic from a harder
                segment". Only drops that are statistically clear are listed, and rules must hold
                two days before anyone is paged.
              </p>
              <p className={styles.proof}>
                {quiet.length > 0 ? (
                  <>
                    {quiet.join(", ")}: no alert in {fleet.data?.windowDays ?? 30} days of traffic.{" "}
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
              Built so that monitoring can never slow down or break the service it watches.
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
            <h2 id="evidence-title">How it's checked</h2>
            <p className={styles.sectionLede}>
              Monitoring that cries wolf gets muted, and monitoring that's wrong is worse than
              none. These are measured, not claimed.
            </p>
          </div>
          <dl className={styles.evidence}>
            <div>
              <dt>1e-9</dt>
              <dd>
                Largest difference from NannyML's estimates and sampling errors, for all four
                metrics. Drift statistics match Evidently.
              </dd>
            </div>
            <div>
              <dt>0.55%</dt>
              <dd>
                Clean days on which the relationship detector alarms, averaged over ten
                references. It was 6.5% before the band was fixed.
              </dd>
            </div>
            <div>
              <dt>0 of 20</dt>
              <dd>
                Seeded runs with an incident before the injected change, or on the healthy model.
                The subtle credit drift is caught in 4 of 5 seeds; the others in 5 of 5.
              </dd>
            </div>
            <div>
              <dt>0 differences</dt>
              <dd>
                Between this demo and 182,624 predictions streamed through the running service:
                SDK, API, Redis, workers, Postgres.
              </dd>
            </div>
            <div>
              <dt>~20k/s</dt>
              <dd>Predictions accepted by one API process; a single worker keeps up.</dd>
            </div>
            <div>
              <dt>95%</dt>
              <dd>
                Python test coverage, with server tests on real Postgres and Redis, and zero serious
                accessibility violations across the dashboard.
              </dd>
            </div>
          </dl>
          <p className={styles.muted}>
            Every design decision and its trade-off is written up as an{" "}
            <a href={`${REPO}/tree/main/docs/adr`}>architecture decision record</a>.
          </p>
        </section>

        {/* ----------------------------------------------------------------- start */}
        <section id="start" className={styles.section} aria-labelledby="start-title">
          <div className={styles.sectionHead}>
            <h2 id="start-title">Run it</h2>
            <p className={styles.sectionLede}>
              The whole stack runs on one machine with Docker. The demo streams four models' traffic
              in through the SDK, so you watch incidents open on real infrastructure.
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
            </ul>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>
          Sentinel is open source under the MIT licence. Built by Md Sifatullah Sheikh.
        </p>
        <p className={styles.muted}>
          The demo runs on synthetic traffic from four scenario models; every number on it comes
          from the real engine.
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
