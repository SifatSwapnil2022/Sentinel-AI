import styles from "./ArchitectureFlow.module.css";

const STAGES = [
  {
    name: "Model server",
    tech: "Python SDK",
    detail: "Logging appends to a bounded buffer and returns. Batches go out in the background.",
  },
  {
    name: "Ingest API",
    tech: "FastAPI",
    detail: "Validates, queues, answers 202. Under backlog it says retry later instead of slowing down.",
  },
  {
    name: "Queue",
    tech: "Redis Streams",
    detail: "Holds accepted batches until written. Nothing is lost if a worker dies.",
  },
  {
    name: "Workers",
    tech: "Consumer group",
    detail: "Write idempotently, recompute the affected days, open and resolve incidents.",
  },
  {
    name: "Storage",
    tech: "Postgres",
    detail: "Predictions partitioned by day. Dashboard pages are precomputed, so reads are one lookup.",
  },
  {
    name: "Dashboard",
    tech: "React",
    detail: "Every estimate drawn with its likely range, every incident with its cause.",
  },
] as const;

/** The service's data path, as an ordered list that reads in order and reflows on phones. */
export function ArchitectureFlow() {
  return (
    <ol className={styles.flow} aria-label="How data flows through Sentinel">
      {STAGES.map((stage) => (
        <li key={stage.name} className={styles.stage}>
          <p className={styles.name}>{stage.name}</p>
          <p className={styles.tech}>{stage.tech}</p>
          <p className={styles.detail}>{stage.detail}</p>
        </li>
      ))}
    </ol>
  );
}
