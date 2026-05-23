"""Build the initial Scout config workbook from AI source docs.

Output: ``rh-docs/scout-initial-config.xlsx`` (gitignored).

Run from the repo root::

  podman exec scout-api /app/.venv/bin/python /app/scripts/build_initial_workbook.py

The output file is then uploaded via Scout's UI:

  /settings → "Workbook import / export" → Upload & preview → Apply.

The script is a pure data-to-XLSX converter — no DB writes, no LLM calls.
All content tables live in this file so the user can edit them and re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Tables — edit these to retune the workbook content.
# ---------------------------------------------------------------------------

PILLARS = [
    # Sourced from the Q4 2026 AI messaging guide. These are the
    # four official "Why AI" pillars.
    {
        "name": "Efficient inferencing",
        "description": (
            "Fast, flexible, and cost-effective model deployments across a "
            "diverse footprint. vLLM for maximum throughput + minimum "
            "latency, llm-d for distributed inference, LLM compressor for "
            "reduced compute utilization, and the AI repository on "
            "Hugging Face for pre-optimized models. chat-model models, "
            "Apache-2.0-licensed and indemnified, are the canonical example."
        ),
        "display_order": 1,
    },
    {
        "name": "Connecting models to data",
        "description": (
            "Simplified, consistent experience to customize models with the "
            "organization's own data. Built-in data ingestion + "
            "pre-processing for unstructured sources (PDFs, docs), synthetic "
            "data generation when private data is thin, training-toolkit for "
            "fine-tuning, RAG and RAFT patterns for grounded responses, and "
            "self-service IDEs (JupyterLab) for data scientists + AI "
            "engineers."
        ),
        "display_order": 2,
    },
    {
        "name": "Agentic AI innovation",
        "description": (
            "Flexible, scalable platform for delivering agentic AI: core "
            "services for managing, deploying, and running agent workflows; "
            "a unified Llama Stack API layer for RAG / safety / evaluation / "
            "telemetry; the AI hub + gen AI studio dashboards for platform "
            "and AI engineers respectively; and Model Context Protocol (MCP) "
            "as the standardized translator to external tools and data."
        ),
        "display_order": 3,
    },
    {
        "name": "Hybrid cloud AI at scale",
        "description": (
            "Build, deploy, and run AI models across any hardware platform "
            "and hybrid cloud environment at scale. Intelligent GPU "
            "utilization with workload scheduling + quotas, distributed "
            "workloads, MLOps + GenAIOps, LLM API gateway, model observability "
            "and bias / drift detection, on-prem + air-gapped deployment "
            "support. Counter-positions against single-cloud lock-in."
        ),
        "display_order": 4,
    },
]

INDUSTRIES = [
    "Financial services",
    "Healthcare",
    "Government / Public sector",
    "Telecommunications",
    "Retail",
    "Manufacturing",
    "Energy",
    "Automotive",
    "Technology",
    "Education",
    "Media & entertainment",
]

AUDIENCES = [
    {
        "name": "Platform engineer",
        "industry": "Technology",
        "role_seniority": "ic",
        "description": (
            "Owns the Kubernetes / OpenShift platform that AI workloads "
            "run on. Cares about GPU scheduling, multi-tenancy, "
            "observability, day-2 operations, and avoiding bespoke "
            "tooling for each ML team."
        ),
        "primary_pain_points": [
            "Fragmented runtimes per accelerator",
            "GPU utilization and cost",
            "Unified monitoring across model serving",
            "Compliance and access controls for sensitive data",
        ],
        "key_messages": [
            "vLLM unifies inference across NVIDIA/AMD/Intel accelerators",
            "chat-model-on-OpenShift gives you a tested, supported stack",
            "Built-in observability + role-based access controls",
        ],
    },
    {
        "name": "MLOps / GenAIOps engineer",
        "industry": "Technology",
        "role_seniority": "ic",
        "description": (
            "Bridges model development and production. Owns model "
            "evaluation, deployment automation, monitoring, drift "
            "detection, and rollout governance."
        ),
        "primary_pain_points": [
            "Manual deployment and rollback workflows",
            "Lack of model evaluation tooling",
            "Drift detection and re-training triggers",
            "Pipeline portability across clouds",
        ],
        "key_messages": [
            "AI platform ships managed pipelines for fine-tune + serve",
            "Integrated evaluation framework with built-in guardrails",
            "Same pipeline runs on AWS, Azure, GCP, on-prem",
        ],
    },
    {
        "name": "Application developer",
        "industry": "Technology",
        "role_seniority": "ic",
        "description": (
            "Building AI-powered features into customer-facing apps. "
            "Wants a stable OpenAI-compatible endpoint, predictable "
            "latency, and RAG building blocks that don't lock them into "
            "one vendor's SDK."
        ),
        "primary_pain_points": [
            "Vendor lock-in via proprietary SDKs",
            "Cold-start latency under load",
            "Embedding model + vector DB integration burden",
            "Cost of high-volume inference calls",
        ],
        "key_messages": [
            "OpenAI-compatible API on top of any model",
            "Bring-your-own retrieval / vector store",
            "vLLM continuous batching for sub-second p95",
        ],
    },
    {
        "name": "Data scientist / AI engineer",
        "industry": "Technology",
        "role_seniority": "ic",
        "description": (
            "Designs, fine-tunes, and evaluates models. Cares about "
            "experiment tracking, distributed training, fine-tune "
            "throughput on available GPUs, and accuracy benchmarks."
        ),
        "primary_pain_points": [
            "Slow fine-tune throughput on limited hardware",
            "Reproducibility across runs and environments",
            "Eval / benchmark framework fragmentation",
            "Data residency rules constrain training location",
        ],
        "key_messages": [
            "training-toolkit + LAB tuning runs on your own GPUs",
            "Eval harness ships with the platform",
            "Train where the data is — on-prem, in-region, anywhere",
        ],
    },
    {
        "name": "AI / ML platform lead",
        "industry": "Technology",
        "role_seniority": "manager",
        "description": (
            "Manages the team that builds and operates internal AI "
            "platforms. Reports to a director or VP. Owns roadmap, "
            "vendor selection, build-vs-buy decisions, and headcount."
        ),
        "primary_pain_points": [
            "Roadmap pressure to ship gen-AI features fast",
            "Skill gap on the team for distributed training",
            "Build-vs-buy on model-serving infra",
            "Justifying spend on enterprise model platforms",
        ],
        "key_messages": [
            "Buy the platform, build the differentiation on top",
            "chat-model + <vendor> support beats DIY total cost",
            "Onboard your team to a single stack across products",
        ],
    },
    {
        "name": "ITOps decision-maker",
        "industry": "Technology",
        "role_seniority": "director",
        "description": (
            "Director or senior manager owning IT operations for "
            "enterprise AI workloads. Cares about uptime SLOs, security "
            "posture, vendor support, and integration with existing IT "
            "service management."
        ),
        "primary_pain_points": [
            "Indemnification and IP-safety on third-party models",
            "Audit trail for regulated environments",
            "Integrating AI ops with existing ITSM tooling",
            "Vendor consolidation across the AI stack",
        ],
        "key_messages": [
            "<vendor> indemnifies chat-model + supports open-source models",
            "RBAC + audit log built in; pairs with your SIEM",
            "One vendor, one support contract across the AI lifecycle",
        ],
    },
    {
        "name": "VP Engineering / CTO",
        "industry": "Technology",
        "role_seniority": "executive",
        "description": (
            "Owns the engineering org's AI strategy. Cares about time-"
            "to-production for AI initiatives, total cost, talent, and "
            "competitive differentiation."
        ),
        "primary_pain_points": [
            "Translating GenAI hype into production wins",
            "Avoiding vendor lock-in at strategic scale",
            "Cost-per-inference at enterprise volume",
            "Hiring + retaining ML platform expertise",
        ],
        "key_messages": [
            "Hybrid-cloud AI without re-platforming",
            "Open models + <vendor> support de-risks the bet",
            "Plug into the OpenShift install you already run",
        ],
    },
    {
        "name": "Cloud / infrastructure architect",
        "industry": "Technology",
        "role_seniority": "director",
        "description": (
            "Owns the cloud reference architecture. Decides where "
            "workloads run, how they connect, how they're secured. "
            "Brought in as an architect when AI scales out of pilot."
        ),
        "primary_pain_points": [
            "Data residency and sovereignty rules",
            "GPU capacity planning across regions",
            "Network and security posture for model serving",
            "Multi-cluster, multi-cloud consistency",
        ],
        "key_messages": [
            "Same operator model on every cloud",
            "Bring AI to the data, not data to the AI",
            "Air-gapped install path supported end-to-end",
        ],
    },
]

# Topic vocabulary — controlled. Aliases help extraction normalize variants.
TOPICS = [
    ("LLMs", ["large language models", "language models", "foundation models"]),
    ("RAG", ["retrieval augmented generation", "retrieval-augmented generation"]),
    ("Agents", ["AI agents", "agentic AI", "agentic workflows"]),
    ("Fine-tuning", ["LoRA", "PEFT", "instruction tuning", "training-toolkit"]),
    ("MLOps", ["ML ops", "ML operations", "model ops"]),
    ("Inference", ["model inference", "model serving", "serving"]),
    ("vLLM", ["vllm"]),
    ("KServe", ["kserve", "kubeflow serving"]),
    ("GPU", ["GPUs", "accelerators", "NVIDIA", "AMD GPU"]),
    ("OpenShift", ["openshift", "OpenShift Container Platform", "OCP"]),
    ("Kubernetes", ["k8s", "k8"]),
    ("AI platform", ["ai-platform", "RHOAI", "ai-platform"]),
    ("AI platform", ["ai-platform", "<vendor> Enterprise Linux AI"]),
    ("AI Inference Server", ["ais", "<vendor> ai inference server"]),
    ("AI platform", ["RHAIE", "AI Enterprise"]),
    ("chat-model", ["chat-model models", "ibm chat-model"]),
    ("Llama", ["meta llama", "llama 3", "llama 4"]),
    ("Mistral", ["mistral ai"]),
    ("Embeddings", ["text embeddings", "vector embeddings"]),
    ("Vector databases", ["vector db", "vector store", "pgvector", "milvus", "chroma"]),
    ("OpenAI API", ["openai compatible", "openai-compatible API"]),
    ("Prompt engineering", ["prompting", "system prompts"]),
    ("Evaluations", ["evals", "eval harness", "benchmarks"]),
    ("Guardrails", ["safety classifier", "content filtering", "AI safety"]),
    ("Observability", ["monitoring", "prometheus", "grafana", "OpenTelemetry"]),
    ("Hybrid cloud", ["multi-cloud", "edge"]),
    ("Edge AI", ["edge inference", "device AI"]),
    ("Confidential computing", ["confidential AI", "enclave"]),
    ("Model quantization", ["compression", "GPTQ", "AWQ", "INT8"]),
    ("PyTorch", ["pytorch", "torch"]),
    ("Hugging Face", ["huggingface", "hf"]),
    ("Distributed training", ["multi-GPU training", "FSDP", "DeepSpeed"]),
    ("Data pipelines", ["ETL", "feature engineering", "data ingestion"]),
    ("Cost optimization", ["TCO", "GPU utilization"]),
    ("Open source AI", ["open models", "open weights"]),
    ("training-toolkit", ["lab tuning"]),
    ("Llama Stack", ["llama-stack"]),
    ("Docling", ["docling pdf"]),
]

# SMEs — first names only, from the metrics file. Bio is placeholder; user
# fills full name + email + bio + topic/audience assignments in the XLSX
# before uploading (or re-imports after editing in the SPA).
SMES = [
    {"full_name": "Cedric", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Sasa", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Addie", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Legare", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Sawyer", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Grace", "team": "team", "expertise_areas": ["AI advocacy"]},
    {"full_name": "Taylor", "team": "TMM", "expertise_areas": ["Technical marketing"]},
]


# ---------------------------------------------------------------------------
# Workbook plumbing
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="DDDDDD")
HEADER_FONT = Font(bold=True)


def _set_headers(ws, headers: list[str]) -> None:
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def _autosize(ws, headers: list[str]) -> None:
    for col_idx, h in enumerate(headers, start=1):
        max_w = max(len(h), 12)
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, values_only=True):
            v = row[0]
            if v is None:
                continue
            max_w = max(max_w, min(len(str(v).split("\n")[0]), 80))
        ws.column_dimensions[get_column_letter(col_idx)].width = max_w + 2


def _semicolon_list(items: list[str]) -> str:
    return ";".join(items)


def write_pillars(ws) -> None:
    headers = ["_scout_id", "_action", "name", "description", "display_order"]
    _set_headers(ws, headers)
    for i, p in enumerate(PILLARS, start=2):
        ws.cell(row=i, column=1, value="")  # _scout_id blank = insert
        ws.cell(row=i, column=2, value="upsert")
        ws.cell(row=i, column=3, value=p["name"])
        ws.cell(row=i, column=4, value=p["description"])
        ws.cell(row=i, column=5, value=p["display_order"])
    _autosize(ws, headers)


def write_industries(ws) -> None:
    headers = ["_scout_id", "_action", "name"]
    _set_headers(ws, headers)
    for i, name in enumerate(INDUSTRIES, start=2):
        ws.cell(row=i, column=1, value="")
        ws.cell(row=i, column=2, value="upsert")
        ws.cell(row=i, column=3, value=name)
    _autosize(ws, headers)


def write_audiences(ws) -> None:
    headers = [
        "_scout_id",
        "_action",
        "name",
        "industry",
        "role_seniority",
        "description",
        "primary_pain_points",
        "key_messages",
        "exclusion_criteria",
        "is_active",
    ]
    _set_headers(ws, headers)
    for i, a in enumerate(AUDIENCES, start=2):
        ws.cell(row=i, column=1, value="")
        ws.cell(row=i, column=2, value="upsert")
        ws.cell(row=i, column=3, value=a["name"])
        ws.cell(row=i, column=4, value=a["industry"])
        ws.cell(row=i, column=5, value=a["role_seniority"])
        ws.cell(row=i, column=6, value=a["description"])
        ws.cell(row=i, column=7, value=_semicolon_list(a["primary_pain_points"]))
        ws.cell(row=i, column=8, value=_semicolon_list(a["key_messages"]))
        ws.cell(row=i, column=9, value="")
        ws.cell(row=i, column=10, value="TRUE")
    _autosize(ws, headers)


def write_smes(ws) -> None:
    headers = [
        "_scout_id",
        "_action",
        "full_name",
        "email",
        "team",
        "expertise_areas",
        "primary_topics",
        "audience_focus",
        "location_country",
        "location_city",
        "bio",
        "linkedin_url",
        "github_url",
        "website_url",
        "is_active",
    ]
    _set_headers(ws, headers)
    for i, s in enumerate(SMES, start=2):
        ws.cell(row=i, column=1, value="")
        ws.cell(row=i, column=2, value="upsert")
        ws.cell(row=i, column=3, value=s["full_name"])
        ws.cell(row=i, column=4, value="")  # email TBD
        ws.cell(row=i, column=5, value=s["team"])
        ws.cell(row=i, column=6, value=_semicolon_list(s["expertise_areas"]))
        ws.cell(row=i, column=7, value="")  # primary_topics TBD
        ws.cell(row=i, column=8, value="")  # audience_focus TBD
        ws.cell(row=i, column=9, value="US")  # placeholder country
        ws.cell(row=i, column=10, value="")  # city TBD
        ws.cell(
            row=i,
            column=11,
            value=(
                f"{s['full_name']} is a <vendor> {s['team']} subject-matter "
                f"expert in AI advocacy and developer engagement. Bio to be "
                f"completed by the team — minimum 200 characters required."
            ),
        )
        ws.cell(row=i, column=12, value="")
        ws.cell(row=i, column=13, value="")
        ws.cell(row=i, column=14, value="")
        ws.cell(row=i, column=15, value="TRUE")
    _autosize(ws, headers)


def write_topics(ws) -> None:
    headers = [
        "_scout_id",
        "_action",
        "name",
        "slug",
        "aliases",
        "is_active",
        "pending_review",
    ]
    _set_headers(ws, headers)
    for i, (name, aliases) in enumerate(TOPICS, start=2):
        ws.cell(row=i, column=1, value="")
        ws.cell(row=i, column=2, value="upsert")
        ws.cell(row=i, column=3, value=name)
        ws.cell(row=i, column=4, value="")  # let the apply layer derive slug
        ws.cell(row=i, column=5, value=_semicolon_list(aliases))
        ws.cell(row=i, column=6, value="TRUE")
        ws.cell(row=i, column=7, value="FALSE")
    _autosize(ws, headers)


def write_series(ws) -> None:
    # Empty series sheet — 35 are already seeded by the baseline migration.
    headers = [
        "_scout_id",
        "_action",
        "canonical_name",
        "aliases",
        "description",
        "typical_month",
        "typical_topics",
        "homepage",
        "is_active",
    ]
    _set_headers(ws, headers)
    _autosize(ws, headers)


def write_reference(ws) -> None:
    """Quick reference / instructions sheet."""
    ws["A1"] = "Scout initial-config workbook"
    ws["A1"].font = Font(bold=True, size=14)
    rows = [
        "",
        "Generated by scripts/build_initial_workbook.py from rh-docs/.",
        "",
        "How to upload:",
        "  1. Open Scout → /settings → Workbook import / export.",
        "  2. Click 'Upload & preview…' and pick this file.",
        "  3. Review the per-sheet diff table.",
        "  4. Click 'Apply' to commit.",
        "",
        "Per-sheet notes:",
        "  • Pillars — 4 rows. Edit names + descriptions as needed.",
        "  • Industries — 11 rows. Standard set.",
        "  • Audiences — 8 personas with pain points + key messages.",
        "  • SMEs — 7 rows. First names only; complete bio + topics + audience_focus.",
        "  • Topics — ~37 controlled-vocab terms with aliases.",
        "  • Series — empty (35 already seeded by the baseline migration).",
        "",
        "Editing convention:",
        "  • _action=upsert (default) inserts new + updates existing by _scout_id.",
        "  • Leave _scout_id blank on new rows; the apply layer fills it.",
        "  • Semicolon-separated lists for arrays (e.g. 'a;b;c').",
        "  • Booleans: TRUE / FALSE (case-insensitive).",
    ]
    for i, line in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=line)
    ws.column_dimensions["A"].width = 100


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(out_path: Path) -> None:
    wb = Workbook()
    # Default sheet → rename to Reference
    ref = wb.active
    ref.title = "Reference"
    write_reference(ref)

    write_pillars(wb.create_sheet("Pillars"))
    write_industries(wb.create_sheet("Industries"))
    write_audiences(wb.create_sheet("Audiences"))
    write_smes(wb.create_sheet("SMEs"))
    write_topics(wb.create_sheet("Topics"))
    write_series(wb.create_sheet("Series"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"OK → {out_path} ({out_path.stat().st_size:,} bytes)")
    print(
        "Counts:  "
        f"pillars={len(PILLARS)}  industries={len(INDUSTRIES)}  "
        f"audiences={len(AUDIENCES)}  smes={len(SMES)}  topics={len(TOPICS)}"
    )


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("rh-docs/scout-initial-config.xlsx")
    main(out)
