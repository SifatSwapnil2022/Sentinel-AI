"""Generate the Power BI project and the Tableau workbook for Sentinel's BI tables.

Both read the star schema the demo build writes to ``web/public/data/bi`` (or a live API's
``/v1/export``). The files are generated rather than saved from the desktop tools so they stay
reviewable, deterministic and in step with the tables' columns.

Usage:
    python bi/build_bi.py

Writes:
    bi/powerbi/        Power BI project (PBIP): TMDL semantic model and a PBIR report
    bi/tableau/        Tableau workbook (.twb) reading the CSVs from ./Data/bi
    web/public/reports/sentinel-powerbi.zip   the project, zipped for download
    web/public/reports/sentinel.twbx          the workbook packaged with the CSVs
"""

from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = ROOT / "web/public/data/bi"
POWERBI = ROOT / "bi/powerbi"
TABLEAU = ROOT / "bi/tableau"
PUBLIC = ROOT / "web/public/reports"
DEFAULT_URL = "https://sentinel-ai-sage-gamma.vercel.app/data/bi/"
NAMESPACE = uuid.UUID("5b1c6f9e-2f1a-4b7e-9d0c-6a1e3c2b7f40")
FIXED_TIME = (2026, 10, 24, 0, 0, 0)

# --------------------------------------------------------------------------- the star schema

TEXT, INT, NUM, BOOL, DATE = "text", "int", "num", "bool", "date"


@dataclass(frozen=True)
class Col:
    name: str
    kind: str
    percent: bool = False


TABLES: dict[str, list[Col]] = {
    "dim_model": [
        Col("model_id", TEXT),
        Col("model_name", TEXT),
        Col("team", TEXT),
        Col("version", TEXT),
        Col("description", TEXT),
        Col("label_delay_days", INT),
        Col("reference_rows", INT),
        Col("reference_accuracy", NUM, True),
        Col("reference_precision", NUM, True),
        Col("reference_recall", NUM, True),
        Col("reference_f1", NUM, True),
        Col("status", TEXT),
        Col("open_incidents", INT),
    ],
    "dim_date": [
        Col("date", DATE),
        Col("year", INT),
        Col("month", INT),
        Col("month_name", TEXT),
        Col("iso_year", INT),
        Col("iso_week", INT),
        Col("weekday", INT),
        Col("weekday_name", TEXT),
    ],
    "fact_model_day": [
        Col("model_id", TEXT),
        Col("date", DATE),
        Col("predictions", INT),
        Col("est_accuracy", NUM, True),
        Col("est_accuracy_lower", NUM, True),
        Col("est_accuracy_upper", NUM, True),
        Col("est_precision", NUM, True),
        Col("est_recall", NUM, True),
        Col("est_f1", NUM, True),
        Col("measured_accuracy", NUM, True),
        Col("measured_precision", NUM, True),
        Col("measured_recall", NUM, True),
        Col("measured_f1", NUM, True),
        Col("label_coverage", NUM, True),
        Col("p95_latency_ms", NUM),
        Col("multivariate_error", NUM),
        Col("multivariate_upper", NUM),
        Col("multivariate_drifted", BOOL),
        Col("concept_flag", BOOL),
        Col("drifted_features", INT),
        Col("max_missing_jump", NUM, True),
    ],
    "fact_feature_day": [
        Col("model_id", TEXT),
        Col("feature", TEXT),
        Col("date", DATE),
        Col("kind", TEXT),
        Col("method", TEXT),
        Col("statistic", NUM),
        Col("threshold", NUM),
        Col("drifted", BOOL),
        Col("psi", NUM),
        Col("null_rate", NUM, True),
        Col("reference_null_rate", NUM, True),
    ],
    "fact_segment": [
        Col("model_id", TEXT),
        Col("window_end", DATE),
        Col("feature", TEXT),
        Col("segment", TEXT),
        Col("rows_reference", INT),
        Col("rows_current", INT),
        Col("share_reference", NUM, True),
        Col("share_current", NUM, True),
        Col("reference_accuracy", NUM, True),
        Col("estimated_accuracy", NUM, True),
        Col("measured_accuracy", NUM, True),
        Col("labelled_rows", INT),
    ],
    "fact_incident": [
        Col("incident_id", TEXT),
        Col("model_id", TEXT),
        Col("kind", TEXT),
        Col("title", TEXT),
        Col("severity", TEXT),
        Col("status", TEXT),
        Col("opened_on", DATE),
        Col("resolved_on", DATE),
        Col("days_open", INT),
        Col("metric_basis", TEXT),
        Col("metric_reference", NUM, True),
        Col("metric_current", NUM, True),
        Col("top_segment", TEXT),
    ],
    "fact_incident_signal": [
        Col("incident_id", TEXT),
        Col("kind", TEXT),
        Col("severity", TEXT),
        Col("fired_on", DATE),
    ],
}

# (from table, from column, to table, to column): every fact joins its dimensions many-to-one.
RELATIONSHIPS = [
    ("fact_model_day", "model_id", "dim_model", "model_id"),
    ("fact_model_day", "date", "dim_date", "date"),
    ("fact_feature_day", "model_id", "dim_model", "model_id"),
    ("fact_feature_day", "date", "dim_date", "date"),
    ("fact_segment", "model_id", "dim_model", "model_id"),
    ("fact_incident", "model_id", "dim_model", "model_id"),
    ("fact_incident_signal", "incident_id", "fact_incident", "incident_id"),
]


def guid(*parts: str) -> str:
    """A stable id, so regenerating the files changes nothing unless the content does."""
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def check_csv_headers() -> None:
    """Fail early if the CSVs and this script disagree about a table's columns."""
    for table, cols in TABLES.items():
        header = (CSV_DIR / f"{table}.csv").read_text().splitlines()[0].split(",")
        expected = [c.name for c in cols]
        if header != expected:
            raise SystemExit(f"{table}.csv columns {header} differ from {expected}")


# --------------------------------------------------------------------------- Power BI: TMDL

M_TYPES = {
    TEXT: "type text",
    INT: "Int64.Type",
    NUM: "type number",
    BOOL: "type logical",
    DATE: "type date",
}
TMDL_TYPES = {TEXT: "string", INT: "int64", NUM: "double", BOOL: "boolean", DATE: "dateTime"}

# Measures: rates are weighted by predictions, so a model with ten times the traffic counts ten
# times as much, the same way the dashboard combines them.
MEASURES: dict[str, list[tuple[str, str, str]]] = {
    "fact_model_day": [
        ("Predictions", "SUM ( fact_model_day[predictions] )", "#,0"),
        (
            "Estimated accuracy",
            "DIVIDE ( SUMX ( fact_model_day, fact_model_day[est_accuracy] * fact_model_day[predictions] ), [Predictions] )",
            "0.0%",
        ),
        (
            "Reference accuracy",
            "DIVIDE ( SUMX ( fact_model_day, RELATED ( dim_model[reference_accuracy] ) * fact_model_day[predictions] ), [Predictions] )",
            "0.0%",
        ),
        (
            "Accuracy gap (points)",
            "( [Estimated accuracy] - [Reference accuracy] ) * 100",
            "+0.0;-0.0;0.0",
        ),
        (
            "Measured accuracy",
            "VAR labelled = FILTER ( fact_model_day, fact_model_day[label_coverage] >= 0.5 && NOT ISBLANK ( fact_model_day[measured_accuracy] ) )\n"
            "RETURN DIVIDE ( SUMX ( labelled, fact_model_day[measured_accuracy] * fact_model_day[predictions] ), SUMX ( labelled, fact_model_day[predictions] ) )",
            "0.0%",
        ),
        (
            "Label coverage",
            "DIVIDE ( SUMX ( fact_model_day, fact_model_day[label_coverage] * fact_model_day[predictions] ), [Predictions] )",
            "0%",
        ),
        (
            "p95 latency (ms)",
            "DIVIDE ( SUMX ( fact_model_day, fact_model_day[p95_latency_ms] * fact_model_day[predictions] ), [Predictions] )",
            "0",
        ),
        (
            "Drift days",
            "COUNTROWS ( FILTER ( fact_model_day, fact_model_day[drifted_features] >= 2 || fact_model_day[multivariate_drifted] ) )",
            "0",
        ),
        ("Largest missing-value rise", "MAX ( fact_model_day[max_missing_jump] )", "0.0%"),
    ],
    "fact_feature_day": [
        (
            "Feature drift days",
            "CALCULATE ( COUNTROWS ( fact_feature_day ), fact_feature_day[drifted] = TRUE () )",
            "0",
        ),
        ("Highest missing rate", "MAX ( fact_feature_day[null_rate] )", "0.0%"),
    ],
    "fact_incident": [
        ("Incidents", "COUNTROWS ( fact_incident )", "0"),
        (
            "Open incidents",
            'CALCULATE ( COUNTROWS ( fact_incident ), fact_incident[status] = "open" )',
            "0",
        ),
        ("Average days open", "AVERAGE ( fact_incident[days_open] )", "0.0"),
    ],
}

DESCRIPTIONS = {
    "dim_model": "One row per model: owner, version, label delay, reference metrics and current status.",
    "dim_date": "One row per day, with calendar attributes. Marked as the date table.",
    "fact_model_day": "Model by day: traffic, estimated and measured metrics, latency, drift counts.",
    "fact_feature_day": "Model by feature by day: drift test result, PSI and missing-value rate.",
    "fact_segment": "Model by feature by segment over the last 7 days: traffic share and accuracy.",
    "fact_incident": "One row per incident: kind, severity, status, dates and accuracy change.",
    "fact_incident_signal": "Each check that fired within an incident.",
}


def tmdl_table(name: str, cols: list[Col]) -> str:
    lines = [f"/// {DESCRIPTIONS[name]}", f"table {name}", f"\tlineageTag: {guid(name)}"]
    if name == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for measure, expression, fmt in MEASURES.get(name, []):
        body = expression.split("\n")
        if len(body) == 1:
            lines.append(f"\tmeasure '{measure}' = {expression}")
        else:
            lines.append(f"\tmeasure '{measure}' =")
            lines.extend(f"\t\t\t{line}" for line in body)
        lines += [
            f"\t\tformatString: {fmt}",
            f"\t\tlineageTag: {guid(name, 'measure', measure)}",
            "",
        ]
    for col in cols:
        lines.append(f"\tcolumn {col.name}")
        lines.append(f"\t\tdataType: {TMDL_TYPES[col.kind]}")
        if col.kind == DATE:
            lines.append("\t\tformatString: yyyy-mm-dd")
        elif col.percent:
            lines.append("\t\tformatString: 0.0%")
        elif col.kind == INT:
            lines.append("\t\tformatString: 0")
        if name == "dim_date" and col.name == "date":
            lines.append("\t\tisKey")
        lines += [
            f"\t\tlineageTag: {guid(name, col.name)}",
            "\t\tsummarizeBy: none",
            f"\t\tsourceColumn: {col.name}",
            "",
        ]
        if col.kind == DATE:
            lines[-1:-1] = ["\t\tannotation UnderlyingDateTimeDataType = Date"]
    types = ", ".join(f'{{"{c.name}", {M_TYPES[c.kind]}}}' for c in cols)
    lines += [
        f"\tpartition {name} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Csv.Document(Web.Contents(DataUrl, [RelativePath = "{name}.csv", Headers = if ApiKey = "" then [] else [Authorization = "Bearer " & ApiKey]]), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "\t\t\t\t    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f'\t\t\t\t    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")',
        "\t\t\t\tin",
        "\t\t\t\t    Typed",
        "",
    ]
    return "\n".join(lines)


def semantic_model(out: Path) -> None:
    definition = out / "definition"
    (definition / "tables").mkdir(parents=True)
    write_json(
        out / "definition.pbism",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "4.0",
            "settings": {},
        },
    )
    (definition / "database.tmdl").write_text("database Sentinel\n\tcompatibilityLevel: 1567\n")
    model = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        *[f"ref table {t}" for t in TABLES],
        "",
    ]
    (definition / "model.tmdl").write_text("\n".join(model))
    (definition / "expressions.tmdl").write_text(
        "/// Where the CSV tables are read from: this site's demo data, or a Sentinel API's /v1/export/ (keep the trailing slash).\n"
        f'expression DataUrl = "{DEFAULT_URL}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {guid('DataUrl')}\n"
        "\n"
        "\tannotation PBI_ResultType = Text\n"
        "\n"
        "/// A Sentinel API key with read scope. Leave empty for the demo data or an API with public reads.\n"
        'expression ApiKey = "" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = false]\n'
        f"\tlineageTag: {guid('ApiKey')}\n"
        "\n"
        "\tannotation PBI_ResultType = Text\n"
    )
    relationships = []
    for from_table, from_col, to_table, to_col in RELATIONSHIPS:
        relationships += [
            f"relationship {guid('rel', from_table, from_col, to_table)}",
            f"\tfromColumn: {from_table}.{from_col}",
            f"\ttoColumn: {to_table}.{to_col}",
            "",
        ]
    (definition / "relationships.tmdl").write_text("\n".join(relationships))
    for name, cols in TABLES.items():
        (definition / "tables" / f"{name}.tmdl").write_text(tmdl_table(name, cols))


# --------------------------------------------------------------------------- Power BI: PBIR report

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
PAGE_W, PAGE_H = 1280, 720


def column(table: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def measure(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def field(kind: str, table: str, name: str) -> dict:
    expr = column(table, name) if kind == "c" else measure(table, name)
    return {"field": expr, "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def visual(
    page: str,
    name: str,
    kind: str,
    box: tuple[int, int, int, int],
    roles: dict,
    title: str | None = None,
    objects: dict | None = None,
) -> tuple[str, dict]:
    x, y, w, h = box
    vid = guid(page, name).replace("-", "")[:20]
    body: dict = {
        "visualType": kind,
        "query": {"queryState": {role: {"projections": fields} for role, fields in roles.items()}},
        "drillFilterOtherVisuals": True,
    }
    if objects:
        body["objects"] = objects
    if title:
        body["visualContainerObjects"] = {
            "title": [{"properties": {"show": literal("true"), "text": literal(f"'{title}'")}}]
        }
    return vid, {
        "$schema": f"{SCHEMA}/visualContainer/1.2.0/schema.json",
        "name": vid,
        "position": {"x": x, "y": y, "z": 0, "width": w, "height": h},
        "visual": body,
    }


def slicer(
    page: str, name: str, box: tuple[int, int, int, int], table: str, col: str, mode: str
) -> tuple[str, dict]:
    return visual(
        page,
        name,
        "slicer",
        box,
        {"Values": [field("c", table, col)]},
        objects={"data": [{"properties": {"mode": literal(f"'{mode}'")}}]},
    )


def card(page: str, name: str, x: int, table: str, m: str) -> tuple[str, dict]:
    return visual(page, name, "card", (x, 88, 300, 110), {"Values": [field("m", table, m)]})


def pages() -> list[tuple[str, str, list[tuple[str, dict]]]]:
    fleet = "fleet"
    drift = "drift"
    incidents = "incidents"
    return [
        (
            fleet,
            "Fleet health",
            [
                slicer(fleet, "team", (20, 16, 300, 60), "dim_model", "team", "Dropdown"),
                slicer(fleet, "dates", (340, 16, 600, 60), "dim_date", "date", "Between"),
                card(fleet, "predictions", 20, "fact_model_day", "Predictions"),
                card(fleet, "accuracy", 335, "fact_model_day", "Estimated accuracy"),
                card(fleet, "gap", 650, "fact_model_day", "Accuracy gap (points)"),
                card(fleet, "open", 965, "fact_incident", "Open incidents"),
                visual(
                    fleet,
                    "trend",
                    "lineChart",
                    (20, 214, 760, 490),
                    {
                        "Category": [field("c", "dim_date", "date")],
                        "Series": [field("c", "dim_model", "model_name")],
                        "Y": [field("m", "fact_model_day", "Estimated accuracy")],
                    },
                    "Estimated accuracy by day",
                ),
                visual(
                    fleet,
                    "models",
                    "tableEx",
                    (796, 214, 464, 490),
                    {
                        "Values": [
                            field("c", "dim_model", "model_name"),
                            field("c", "dim_model", "status"),
                            field("m", "fact_model_day", "Estimated accuracy"),
                            field("m", "fact_model_day", "Accuracy gap (points)"),
                            field("m", "fact_model_day", "Predictions"),
                            field("m", "fact_incident", "Open incidents"),
                        ],
                    },
                    "Models",
                ),
            ],
        ),
        (
            drift,
            "Drift and data quality",
            [
                slicer(drift, "model", (20, 16, 300, 60), "dim_model", "model_name", "Dropdown"),
                slicer(drift, "dates", (340, 16, 600, 60), "dim_date", "date", "Between"),
                visual(
                    drift,
                    "matrix",
                    "pivotTable",
                    (20, 92, 620, 612),
                    {
                        "Rows": [
                            field("c", "dim_model", "model_name"),
                            field("c", "fact_feature_day", "feature"),
                        ],
                        "Values": [
                            field("m", "fact_feature_day", "Feature drift days"),
                            field("m", "fact_feature_day", "Highest missing rate"),
                        ],
                    },
                    "Drift days and missing values by feature",
                ),
                visual(
                    drift,
                    "driftdays",
                    "clusteredColumnChart",
                    (656, 92, 604, 300),
                    {
                        "Category": [field("c", "dim_date", "date")],
                        "Y": [field("m", "fact_model_day", "Drift days")],
                    },
                    "Models with drift, by day",
                ),
                visual(
                    drift,
                    "missing",
                    "lineChart",
                    (656, 404, 604, 300),
                    {
                        "Category": [field("c", "dim_date", "date")],
                        "Y": [field("m", "fact_model_day", "Largest missing-value rise")],
                    },
                    "Largest rise in missing values",
                ),
            ],
        ),
        (
            incidents,
            "Incidents",
            [
                slicer(
                    incidents, "status", (20, 16, 300, 60), "fact_incident", "status", "Dropdown"
                ),
                slicer(incidents, "team", (340, 16, 300, 60), "dim_model", "team", "Dropdown"),
                card(incidents, "count", 20, "fact_incident", "Incidents"),
                card(incidents, "days", 335, "fact_incident", "Average days open"),
                visual(
                    incidents,
                    "bykind",
                    "clusteredBarChart",
                    (650, 88, 610, 260),
                    {
                        "Category": [field("c", "fact_incident", "kind")],
                        "Y": [field("m", "fact_incident", "Incidents")],
                    },
                    "Incidents by first signal",
                ),
                visual(
                    incidents,
                    "list",
                    "tableEx",
                    (20, 364, 1240, 340),
                    {
                        "Values": [
                            field("c", "fact_incident", "incident_id"),
                            field("c", "dim_model", "model_name"),
                            field("c", "fact_incident", "title"),
                            field("c", "fact_incident", "severity"),
                            field("c", "fact_incident", "status"),
                            field("c", "fact_incident", "opened_on"),
                            field("c", "fact_incident", "resolved_on"),
                            field("c", "fact_incident", "days_open"),
                            field("c", "fact_incident", "top_segment"),
                        ],
                    },
                    "All incidents",
                ),
            ],
        ),
    ]


def report(out: Path) -> None:
    definition = out / "definition"
    write_json(
        out / "definition.pbir",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byPath": {"path": "../Sentinel.SemanticModel"}},
        },
    )
    write_json(
        definition / "version.json",
        {
            "$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json",
            "version": "2.0.0",
        },
    )
    write_json(
        definition / "report.json",
        {
            "$schema": f"{SCHEMA}/report/1.1.0/schema.json",
            "themeCollection": {
                "baseTheme": {
                    "name": "CY24SU06",
                    "reportVersionAtImport": "5.55",
                    "type": "SharedResources",
                }
            },
            "layoutOptimization": "None",
        },
    )
    all_pages = pages()
    write_json(
        definition / "pages" / "pages.json",
        {
            "$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [name for name, _, _ in all_pages],
            "activePageName": all_pages[0][0],
        },
    )
    for name, display, visuals in all_pages:
        folder = definition / "pages" / name
        write_json(
            folder / "page.json",
            {
                "$schema": f"{SCHEMA}/page/1.2.0/schema.json",
                "name": name,
                "displayName": display,
                "displayOption": "FitToPage",
                "height": PAGE_H,
                "width": PAGE_W,
            },
        )
        for vid, doc in visuals:
            write_json(folder / "visuals" / vid / "visual.json", doc)


def powerbi() -> None:
    shutil.rmtree(POWERBI, ignore_errors=True)
    POWERBI.mkdir(parents=True)
    write_json(
        POWERBI / "Sentinel.pbip",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0",
            "artifacts": [{"report": {"path": "Sentinel.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    semantic_model(POWERBI / "Sentinel.SemanticModel")
    report(POWERBI / "Sentinel.Report")
    (POWERBI / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")


# --------------------------------------------------------------------------- Tableau

TABLEAU_TYPES = {TEXT: "string", INT: "integer", NUM: "real", BOOL: "boolean", DATE: "date"}
DS = "federated.sentinel"


def tableau_workbook() -> str:
    """A workbook on fact_model_day joined to dim_model, with three sheets and a dashboard.

    Join-based (not relationship-based) so it opens in older versions too.
    """
    fact, dim = TABLES["fact_model_day"], TABLES["dim_model"]

    def relation(table: str, cols: list[Col]) -> str:
        columns = "\n".join(
            f"              <column datatype='{TABLEAU_TYPES[c.kind]}' name='{c.name}' ordinal='{i}' />"
            for i, c in enumerate(cols)
        )
        return (
            f"          <relation connection='textscan.{table}' name='{table}.csv' table='[{table}#csv]' type='table'>\n"
            "            <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>\n"
            f"{columns}\n"
            "            </columns>\n"
            "          </relation>"
        )

    maps = [
        f"          <map key='[{c.name}]' value='[fact_model_day.csv].[{c.name}]' />" for c in fact
    ]
    maps += [
        f"          <map key='[{c.name if c.name not in {f.name for f in fact} else c.name + ' (dim_model.csv)'}]' value='[dim_model.csv].[{c.name}]' />"
        for c in dim
    ]
    calcs = {
        "Estimated accuracy": "SUM([est_accuracy] * [predictions]) / SUM([predictions])",
        "Reference accuracy": "SUM([reference_accuracy] * [predictions]) / SUM([predictions])",
        "Accuracy gap (points)": "([Calculation_estimated] - [Calculation_reference]) * 100",
        "Label coverage": "SUM([label_coverage] * [predictions]) / SUM([predictions])",
    }
    calc_ids = {
        "Estimated accuracy": "Calculation_estimated",
        "Reference accuracy": "Calculation_reference",
        "Accuracy gap (points)": "Calculation_gap",
        "Label coverage": "Calculation_coverage",
    }
    calc_xml = "\n".join(
        f"      <column caption={quoteattr(caption)} datatype='real' name='[{calc_ids[caption]}]' role='measure' type='quantitative'>\n"
        f"        <calculation class='tableau' formula={quoteattr(formula)} />\n"
        "      </column>"
        for caption, formula in calcs.items()
    )
    named = "\n".join(
        f"          <named-connection caption='{t}' name='textscan.{t}'>\n"
        f"            <connection class='textscan' directory='Data/bi' filename='{t}.csv' password='' server='' />\n"
        "          </named-connection>"
        for t in ("fact_model_day", "dim_model")
    )

    def deps(*cols: str) -> str:
        body = []
        for c in cols:
            if c.startswith("Calculation_"):
                caption = next(k for k, v in calc_ids.items() if v == c)
                body.append(
                    f"            <column caption={quoteattr(caption)} datatype='real' name='[{c}]' role='measure' type='quantitative'>\n"
                    f"              <calculation class='tableau' formula={quoteattr(calcs[caption])} />\n"
                    "            </column>"
                )
            elif c == "date":
                body.append(
                    "            <column datatype='date' name='[date]' role='dimension' type='ordinal' />"
                )
                body.append(
                    "            <column-instance column='[date]' derivation='Day-Trunc' name='[tdy:date:ok]' pivot='key' type='ordinal' />"
                )
            elif c == "predictions":
                body.append(
                    "            <column datatype='integer' name='[predictions]' role='measure' type='quantitative' />"
                )
                body.append(
                    "            <column-instance column='[predictions]' derivation='Sum' name='[sum:predictions:qk]' pivot='key' type='quantitative' />"
                )
            else:
                body.append(
                    f"            <column datatype='string' name='[{c}]' role='dimension' type='nominal' />"
                )
                body.append(
                    f"            <column-instance column='[{c}]' derivation='None' name='[none:{c}:nk]' pivot='key' type='nominal' />"
                )
        body.extend(
            f"            <column-instance column='[{c}]' derivation='User' name='[usr:{c}:qk]' pivot='key' type='quantitative' />"
            for c in cols
            if c.startswith("Calculation_")
        )
        return "\n".join(body)

    def sheet(
        name: str, mark: str, rows: str, cols: str, color: str | None, used: tuple[str, ...]
    ) -> str:
        encodings = f"<encodings><color column='[{DS}].{color}' /></encodings>" if color else ""
        return f"""    <worksheet name={quoteattr(name)}>
      <table>
        <view>
          <datasources>
            <datasource caption='Sentinel' name='{DS}' />
          </datasources>
          <datasource-dependencies datasource='{DS}'>
{deps(*used)}
          </datasource-dependencies>
          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='{mark}' />
            {encodings}
          </pane>
        </panes>
        <rows>{rows}</rows>
        <cols>{cols}</cols>
      </table>
      <simple-id uuid='{{{guid("tableau", name).upper()}}}' />
    </worksheet>"""

    sheets = [
        (
            "Estimated accuracy by day",
            "Line",
            f"[{DS}].[usr:Calculation_estimated:qk]",
            f"[{DS}].[tdy:date:ok]",
            "[none:model_name:nk]",
            ("date", "model_name", "Calculation_estimated"),
        ),
        (
            "Accuracy against reference",
            "Bar",
            f"[{DS}].[none:model_name:nk]",
            f"[{DS}].[usr:Calculation_gap:qk]",
            "[none:team:nk]",
            (
                "model_name",
                "team",
                "Calculation_estimated",
                "Calculation_reference",
                "Calculation_gap",
            ),
        ),
        (
            "Predictions by team",
            "Area",
            f"[{DS}].[sum:predictions:qk]",
            f"[{DS}].[tdy:date:ok]",
            "[none:team:nk]",
            ("date", "team", "predictions"),
        ),
    ]
    worksheets = "\n".join(sheet(*s) for s in sheets)
    zones = "\n".join(
        f"            <zone h='{h}' id='{i + 3}' name={quoteattr(name)} w='{w}' x='{x}' y='{y}' />"
        for i, (name, (x, y, w, h)) in enumerate(
            zip(
                [s[0] for s in sheets],
                [(0, 0, 100000, 50000), (0, 50000, 50000, 50000), (50000, 50000, 50000, 50000)],
                strict=True,
            )
        )
    )
    windows = "\n".join(
        f"    <window class='worksheet' name={quoteattr(s[0])}>\n      <simple-id uuid='{{{guid('window', s[0]).upper()}}}' />\n    </window>"
        for s in sheets
    )
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<!-- Generated by bi/build_bi.py from the Sentinel BI tables. Open in Tableau Desktop 2023.1 or later. -->
<workbook original-version='18.1' source-build='2023.1.0 (20231.23.0310.1045)' source-platform='win' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>
  <datasources>
    <datasource caption='Sentinel' inline='true' name='{DS}' version='18.1'>
      <connection class='federated'>
        <named-connections>
{named}
        </named-connections>
        <relation join='inner' type='join'>
          <clause type='join'>
            <expression op='='>
              <expression op='[fact_model_day.csv].[model_id]' />
              <expression op='[dim_model.csv].[model_id]' />
            </expression>
          </clause>
{relation("fact_model_day", fact)}
{relation("dim_model", dim)}
        </relation>
        <cols>
{chr(10).join(maps)}
        </cols>
      </connection>
{calc_xml}
      <layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />
    </datasource>
  </datasources>
  <worksheets>
{worksheets}
  </worksheets>
  <dashboards>
    <dashboard name='Fleet'>
      <style />
      <size maxheight='800' maxwidth='1200' minheight='800' minwidth='1200' />
      <zones>
        <zone h='100000' id='2' type-v2='layout-basic' w='100000' x='0' y='0'>
{zones}
        </zone>
      </zones>
      <simple-id uuid='{{{guid("tableau", "dashboard").upper()}}}' />
    </dashboard>
  </dashboards>
  <windows source-height='30'>
{windows}
    <window class='dashboard' maximized='true' name='Fleet'>
      <simple-id uuid='{{{guid("window", "Fleet").upper()}}}' />
    </window>
  </windows>
</workbook>
"""


def tableau() -> None:
    shutil.rmtree(TABLEAU, ignore_errors=True)
    TABLEAU.mkdir(parents=True)
    (TABLEAU / "sentinel.twb").write_text(tableau_workbook())


# --------------------------------------------------------------------------- packaging


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def package() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    pbip = [
        (f"Sentinel/{p.relative_to(POWERBI).as_posix()}", p.read_bytes())
        for p in POWERBI.rglob("*")
        if p.is_file()
    ]
    (PUBLIC / "sentinel-powerbi.zip").write_bytes(deterministic_zip(pbip))
    twbx = [("sentinel.twb", (TABLEAU / "sentinel.twb").read_bytes())]
    twbx += [
        (f"Data/bi/{t}.csv", (CSV_DIR / f"{t}.csv").read_bytes())
        for t in ("fact_model_day", "dim_model")
    ]
    (PUBLIC / "sentinel.twbx").write_bytes(deterministic_zip(twbx))


def main() -> None:
    check_csv_headers()
    powerbi()
    tableau()
    package()
    print(
        f"wrote {POWERBI.relative_to(ROOT)}, {TABLEAU.relative_to(ROOT)} and {PUBLIC.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
