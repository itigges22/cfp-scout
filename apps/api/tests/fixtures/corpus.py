"""A labelled corpus for evaluating ranking changes. Test data, not seed data.

WHAT THIS DOES
    Holds a hand-built set of pillars, messaging documents, SMEs, talks and
    conferences that stands in for real operator data on a local machine.

    Every conference carries an ``expect`` label — what a human would say the
    ranking should do with it. That is the point of the corpus: it is ground
    truth we control, so a ranking change can be measured instead of admired.
    Real production data cannot do this job, because nobody wrote down what
    the right answer was.

    Plain dicts, never written to a database. Real data arrives through the
    UI or the scraper; this exists only so a ranking change can be evaluated
    in memory, against answers we know.

HOW IT CONNECTS
    Called by   tests/unit/test_ranking_quality.py
    Writes      nothing — it is data, and it stays out of Postgres

WORTH KNOWING
    ``expect`` values:
      strong   should rank near the top; we would go
      mid      plausible, genuinely arguable either way
      weak     should rank low; wrong audience or off-topic
      veto     the judge should reject it outright, whatever the numbers say

    The KubeCon rows exist to exercise series identity: EU 2025 and EU 2026
    are the same series AND the same event in different years; EU 2026 and
    NA 2026 are the same series but NOT the same event. Any series algorithm
    has to get both right.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Strategic pillars — the themes the org organises around
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Who this fictional operator is
# ---------------------------------------------------------------------------
# The judge reads this and nothing else to decide who its audience is, so it
# has to agree with the rest of the corpus. It names research as an audience
# because there is a Data Science & AutoML pillar and two AI Research SMEs
# below — if it did not, vetoing NeurIPS would be the CORRECT answer and the
# expectation labels would be the thing that is wrong.
#
# That is the whole point of holding it here rather than reading the real
# ``settings.operator_profile``: the fixture must be self-consistent, so a
# failing judge test means the judge is wrong rather than that the operator's
# real documentation is out of date.
OPERATOR_PROFILE = """\
A commercial open-source software vendor selling enterprise subscriptions to \
open-source AI and container platforms.

We go to events to speak, to sponsor where our buyers gather, and to recruit.

Who we are trying to reach:
  - platform engineers and SREs who run the infrastructure AI workloads sit on
  - enterprise developers building on those platforms
  - IT decision-makers evaluating platforms and support contracts
  - open-source contributors in our project communities
  - applied AI and data-science researchers — we have our own research team
    working on AutoML and inference efficiency, and we present that work at
    research venues

What we talk about: inference serving and model runtimes, Kubernetes and
platform engineering, developer tooling, AutoML and applied data science, and
model governance for regulated industries.
"""


PILLARS: list[dict[str, Any]] = [
    {
        "key": "inference",
        "name": "AI Inference & Model Serving",
        "description": (
            "Running trained models in production at scale: serving runtimes, "
            "GPU utilisation, batching, quantisation, latency and throughput "
            "for enterprise inference workloads."
        ),
        "display_order": 1,
    },
    {
        "key": "platform",
        "name": "Platform Engineering & Kubernetes",
        "description": (
            "The container platform underneath AI workloads: Kubernetes "
            "operators, GPU scheduling, multi-tenancy, hybrid cloud, and the "
            "day-2 operations of running AI infrastructure."
        ),
        "display_order": 2,
    },
    {
        "key": "devex",
        "name": "Developer Experience & Tooling",
        "description": (
            "How application developers actually build with models: SDKs, "
            "local development loops, CI for ML, agent frameworks, and the "
            "tooling that removes friction between a laptop and production."
        ),
        "display_order": 3,
    },
    {
        "key": "data",
        "name": "Data Science & AutoML",
        "description": (
            "Automating the model development lifecycle: AutoML, feature "
            "engineering, experiment tracking, distributed training and "
            "notebook-to-pipeline workflows for data science teams — "
            "including our own AI research work."
        ),
        "display_order": 4,
    },
    {
        "key": "trust",
        "name": "Trusted AI & Model Governance",
        "description": (
            "Making AI defensible in a regulated enterprise: model lineage, "
            "evaluation, guardrails, bias and safety testing, audit trails, "
            "and open models as a transparency story."
        ),
        "display_order": 4,
    },
]

# ---------------------------------------------------------------------------
# Messaging & positioning — the corpus the matcher compares conferences to
# ---------------------------------------------------------------------------
MESSAGING: list[dict[str, Any]] = [
    {
        "pillar": "inference",
        "title": "Inference Server — positioning",
        "elevator_pitch": (
            "Serve any open model on any accelerator, in any cloud, with "
            "production-grade throughput and a supported runtime."
        ),
        "target_personas": ["Platform engineer", "ML engineer", "Infrastructure architect"],
        "key_themes": [
            "vLLM as the serving runtime",
            "GPU utilisation and cost per token",
            "continuous batching and paged attention",
            "quantisation for cheaper inference",
            "model-agnostic serving APIs",
        ],
        "talking_points": [
            "Teams stall moving from a notebook to a served endpoint.",
            "GPU spend is the single largest line item in an AI programme.",
            "Open runtimes avoid lock-in to a single model vendor.",
        ],
        "differentiators": ["Supported vLLM", "runs on-prem and in cloud", "no model lock-in"],
    },
    {
        "pillar": "platform",
        "title": "AI Platform on Kubernetes — positioning",
        "elevator_pitch": (
            "Run AI workloads on the same Kubernetes platform your "
            "applications already use, with GPU scheduling and multi-tenancy "
            "built in."
        ),
        "target_personas": ["Platform engineer", "SRE", "IT decision maker"],
        "key_themes": [
            "Kubernetes operators for AI workloads",
            "GPU scheduling and sharing",
            "multi-tenant model serving",
            "hybrid and disconnected environments",
            "day-2 operations for AI infrastructure",
        ],
        "talking_points": [
            "AI infrastructure should not be a separate silo from the platform.",
            "GPU capacity is scarce; scheduling and sharing decide utilisation.",
            "Regulated industries need disconnected and on-prem options.",
        ],
        "differentiators": ["one platform for apps and AI", "hybrid by default"],
    },
    {
        "pillar": "devex",
        "title": "Developer Experience for AI — positioning",
        "elevator_pitch": (
            "Give application developers a fast local loop and a clean path "
            "to production for model-backed features."
        ),
        "target_personas": ["Application developer", "Developer advocate", "Tech lead"],
        "key_themes": [
            "local development against real models",
            "agent and RAG frameworks",
            "CI and evaluation for model-backed features",
            "SDKs and OpenAI-compatible APIs",
            "prompt and context engineering in practice",
        ],
        "talking_points": [
            "Most developers meet AI through an API, not a training run.",
            "The inner loop matters more than the model benchmark.",
        ],
        "differentiators": ["open standards", "works with existing toolchains"],
    },
    {
        "pillar": "data",
        "title": "Data Science & AutoML — positioning",
        "elevator_pitch": (
            "Streamline the data science workflow: AutoML, distributed "
            "training and reproducible pipelines, from notebook to "
            "production, on the platform the rest of the org already runs."
        ),
        "target_personas": ["Data scientist", "ML researcher", "ML engineer"],
        "key_themes": [
            "AutoML and automated model selection",
            "hyperparameter optimisation at scale",
            "distributed training on Kubernetes",
            "experiment tracking and reproducibility",
            "notebook-to-pipeline workflows",
            "applied AI research",
        ],
        "talking_points": [
            "Research teams lose weeks to infrastructure rather than modelling.",
            "AutoML shortens the path from a dataset to a candidate model.",
            "We publish research and run it on the same platform we sell.",
        ],
        "differentiators": ["AutoML in the platform", "research team publishes openly"],
    },
    {
        "pillar": "trust",
        "title": "Trusted AI — positioning",
        "elevator_pitch": (
            "Open models, transparent lineage and repeatable evaluation, so "
            "AI decisions survive an audit."
        ),
        "target_personas": ["Risk and compliance lead", "ML engineer", "IT decision maker"],
        "key_themes": [
            "model lineage and provenance",
            "evaluation harnesses and regression testing",
            "guardrails and safety classifiers",
            "bias testing",
            "open weights as an auditability story",
        ],
        "talking_points": [
            "Regulated buyers need to explain model behaviour, not just measure it.",
            "Open weights are an audit advantage, not just a licensing one.",
        ],
        "differentiators": ["open weights", "auditable pipeline"],
    },
]

# ---------------------------------------------------------------------------
# Subject-matter experts — bio-led, per D12
# ---------------------------------------------------------------------------
SMES: list[dict[str, Any]] = [
    {
        "key": "priya",
        "full_name": "Priya Raman",
        "team": "AI Platform Engineering",
        "location_country": "US",
        "location_city": "Boston",
        "pillar": "inference",
        "bio": (
            "Principal engineer working on model serving at scale. Maintains "
            "internal vLLM deployments across GPU fleets, focused on "
            "continuous batching, paged attention and cost per token. Speaks "
            "regularly on inference throughput and quantisation tradeoffs."
        ),
    },
    {
        "key": "marcus",
        "full_name": "Marcus Feld",
        "team": "AI Platform Engineering",
        "location_country": "DE",
        "location_city": "Berlin",
        "pillar": "platform",
        "bio": (
            "Kubernetes SRE turned platform architect. Builds operators for "
            "GPU scheduling and multi-tenant model serving, with a focus on "
            "hybrid and disconnected clusters in regulated industries. Long "
            "history in the CNCF community."
        ),
    },
    {
        "key": "aisha",
        "full_name": "Aisha Nwosu",
        "team": "Developer Advocacy",
        "location_country": "GB",
        "location_city": "London",
        "pillar": "devex",
        "bio": (
            "Developer advocate for AI tooling. Works on the local "
            "development loop for model-backed applications: agent "
            "frameworks, retrieval-augmented generation, and evaluation in "
            "CI. Writes and speaks for application developers rather than "
            "researchers."
        ),
    },
    {
        "key": "tomas",
        "full_name": "Tomas Lindqvist",
        "team": "Trusted AI",
        "location_country": "SE",
        "location_city": "Stockholm",
        "pillar": "trust",
        "bio": (
            "Works on model governance for regulated deployments: lineage, "
            "evaluation harnesses, guardrails and bias testing. Background in "
            "financial services compliance before moving into ML platforms."
        ),
    },
    {
        "key": "ravi",
        "full_name": "Ravi Chandrasekaran",
        "team": "AI Research",
        "location_country": "US",
        "location_city": "Raleigh",
        "pillar": "data",
        "bio": (
            "Research scientist working on automated machine learning. "
            "Publishes on neural architecture search and hyperparameter "
            "optimisation, and works on bringing AutoML capabilities into the "
            "product platform. Presents at academic venues as well as "
            "industry conferences."
        ),
    },
    {
        "key": "elena",
        "full_name": "Elena Petrova",
        "team": "AI Research",
        "location_country": "CZ",
        "location_city": "Brno",
        "pillar": "data",
        "bio": (
            "Applied researcher on distributed training and efficient "
            "fine-tuning. Bridges the research group and the platform team, "
            "translating published work into product features for data "
            "science workloads."
        ),
    },
    {
        "key": "dana",
        "full_name": "Dana Whitfield",
        "team": "Developer Advocacy",
        "location_country": "US",
        "location_city": "Austin",
        "pillar": "devex",
        "bio": (
            "Generalist advocate covering the whole AI platform story. "
            "Comfortable on a keynote stage or a booth. Less depth than the "
            "specialists on any single topic, broader range across them."
        ),
    },
]

# ---------------------------------------------------------------------------
# Talks — the material we submit to CFPs
# ---------------------------------------------------------------------------
TALKS: list[dict[str, Any]] = [
    {
        "key": "vllm-prod",
        "title": "Scaling vLLM in Production: Batching, Paging and Cost per Token",
        "abstract": (
            "A walk through running vLLM across a shared GPU fleet: how "
            "continuous batching and paged attention change throughput, where "
            "quantisation actually pays off, and how to reason about cost per "
            "token rather than cost per GPU hour."
        ),
        "sme": "priya",
        "pillar": "inference",
    },
    {
        "key": "gpu-sched",
        "title": "GPU Scheduling on Kubernetes Without Tears",
        "abstract": (
            "Multi-tenant GPU scheduling: fractional allocation, priority and "
            "preemption, and what breaks when AI workloads land on a platform "
            "designed for stateless services."
        ),
        "sme": "marcus",
        "pillar": "platform",
    },
    {
        "key": "agent-loop",
        "title": "The Inner Loop for Agent Development",
        "abstract": (
            "Building model-backed features without a 40-second feedback "
            "cycle: local model endpoints, deterministic replay of agent "
            "traces, and evaluation that runs in CI like a test suite."
        ),
        "sme": "aisha",
        "pillar": "devex",
    },
    {
        "key": "rag-eval",
        "title": "Evaluating RAG Systems You Actually Have to Support",
        "abstract": (
            "Retrieval quality decides RAG quality. Measuring retrieval "
            "separately from generation, building a regression suite, and "
            "catching silent degradation after a model swap."
        ),
        "sme": "aisha",
        "pillar": "devex",
    },
    {
        "key": "automl",
        "title": "AutoML for Research Teams: Architecture Search Without a Cluster Babysitter",
        "abstract": (
            "How automated model selection and hyperparameter optimisation "
            "shorten the path from dataset to candidate model, and what it "
            "takes to run neural architecture search on shared Kubernetes "
            "infrastructure without monopolising it."
        ),
        "sme": "ravi",
        "pillar": "data",
    },
    {
        "key": "lineage",
        "title": "Model Lineage for Auditors, Not Dashboards",
        "abstract": (
            "What a regulator asks for when a model makes a decision, and how "
            "to record lineage, evaluation results and guardrail behaviour so "
            "the answer takes minutes rather than weeks."
        ),
        "sme": "tomas",
        "pillar": "trust",
    },
    {
        "key": "open-weights",
        "title": "Open Weights as a Compliance Strategy",
        "abstract": (
            "Why open models are easier to defend in a regulated environment: "
            "inspectable weights, reproducible evaluation, and no dependency "
            "on a vendor's undisclosed training data."
        ),
        "sme": "tomas",
        "pillar": "trust",
    },
]

# ---------------------------------------------------------------------------
# Conferences — every row labelled with what the ranking SHOULD do
# ---------------------------------------------------------------------------
CONFERENCES: list[dict[str, Any]] = [
    # --- strong fits -------------------------------------------------------
    {
        "name": "vLLM Summit 2026",
        "expect": "strong",
        "why": "squarely on the inference pillar; Priya has a matching talk",
        "series": "vLLM Summit",
        "event_kind": "corporate",
        "location_city": "San Francisco", "location_country": "US",
        "start": "2026-11-10", "cfp_close": "2026-07-15",
        "description": (
            "A conference for practitioners running open model inference in "
            "production. Sessions on serving runtimes, continuous batching, "
            "GPU utilisation, quantisation and cost per token."
        ),
        "cfp_topics": ["inference", "vLLM", "model serving", "GPU", "quantisation"],
    },
    {
        "name": "KubeCon + CloudNativeCon Europe 2026",
        "expect": "strong",
        "why": "platform pillar; Marcus fits; series we attended in 2025",
        "series": "KubeCon + CloudNativeCon Europe",
        "event_kind": "corporate",
        "location_city": "Amsterdam", "location_country": "NL",
        "start": "2026-03-17", "cfp_close": "2026-09-20",
        "description": (
            "The CNCF flagship European event. Kubernetes operators, "
            "platform engineering, GPU scheduling, multi-tenancy and day-2 "
            "operations for cloud-native infrastructure including AI "
            "workloads."
        ),
        "cfp_topics": ["kubernetes", "platform engineering", "operators", "GPU scheduling"],
    },
    {
        "name": "AI Engineer World's Fair 2026",
        "expect": "strong",
        "why": "developer-experience pillar; Aisha has two matching talks",
        "series": "AI Engineer World's Fair",
        "event_kind": "corporate",
        "location_city": "San Francisco", "location_country": "US",
        "start": "2026-06-03", "cfp_close": "2026-02-28",
        "description": (
            "For engineers building applications on top of models. Agent "
            "frameworks, retrieval-augmented generation, evaluation in CI, "
            "SDKs and the practical inner loop of shipping AI features."
        ),
        "cfp_topics": ["agents", "RAG", "evaluation", "developer tooling", "LLM applications"],
    },
    # --- the series test ---------------------------------------------------
    {
        "name": "KubeCon + CloudNativeCon Europe 2025",
        "expect": "attended",
        "why": "same series AND same event as EU 2026, one year earlier",
        "series": "KubeCon + CloudNativeCon Europe",
        "event_kind": "corporate",
        "location_city": "London", "location_country": "GB",
        "start": "2025-04-01", "cfp_close": "2024-11-24",
        "description": "The CNCF flagship European event, 2025 edition.",
        "cfp_topics": ["kubernetes", "platform engineering"],
        "attended": {
            "estimated_attendees": 12000,
            "total_spend_usd": 48000,
            "leads": 210,
            "worth_it": "would_attend",
            "participation": [
                {"sme": "marcus", "activity": "talk", "outcome": "went well; room full"},
                {"sme": "dana", "activity": "booth", "outcome": "steady traffic, good leads"},
            ],
        },
    },
    {
        "name": "KubeCon + CloudNativeCon North America 2026",
        "expect": "strong",
        "why": "SAME SERIES as EU but a DIFFERENT event — series logic must not conflate them",
        "series": "KubeCon + CloudNativeCon North America",
        "event_kind": "corporate",
        "location_city": "Chicago", "location_country": "US",
        "start": "2026-11-09", "cfp_close": "2026-06-01",
        "description": "The CNCF flagship North American event.",
        "cfp_topics": ["kubernetes", "platform engineering", "operators"],
    },
    # --- the ambiguous middle ---------------------------------------------
    {
        "name": "MLOps World 2026",
        "expect": "mid",
        "why": "adjacent to inference and trust, but broad and vendor-heavy",
        "series": "MLOps World", "event_kind": "corporate",
        "location_city": "Toronto", "location_country": "CA",
        "start": "2026-10-05", "cfp_close": "2026-05-30",
        "description": (
            "Operationalising machine learning: pipelines, monitoring, "
            "deployment and the organisational side of ML delivery."
        ),
        "cfp_topics": ["MLOps", "deployment", "monitoring", "pipelines"],
    },
    {
        "name": "Generic AI Summit 2026",
        "expect": "mid",
        "why": "AI-adjacent but no concrete technical angle; the smear case",
        "series": "Generic AI Summit", "event_kind": "corporate",
        "location_city": "Dubai", "location_country": "AE",
        "start": "2026-09-14", "cfp_close": "2026-05-01",
        "description": (
            "Executives and practitioners discuss the future of artificial "
            "intelligence across industries, with keynotes on strategy, "
            "transformation and innovation."
        ),
        "cfp_topics": ["AI", "innovation", "digital transformation"],
    },
    {
        "name": "Nordic Developer Days 2026",
        "expect": "mid",
        "why": "regional dev event; Tomas is local; some devex overlap",
        "series": "Nordic Developer Days", "event_kind": "developer_day",
        "location_city": "Stockholm", "location_country": "SE",
        "start": "2026-05-20", "cfp_close": "2026-02-15",
        "description": (
            "A regional conference for software developers, covering backend "
            "engineering, cloud, and a growing track on building with AI APIs."
        ),
        "cfp_topics": ["software engineering", "cloud", "AI APIs"],
    },
    # --- should be vetoed by the judge ------------------------------------
    {
        "name": "NeurIPS 2026",
        "expect": "strong",
        "why": (
            "Data/AutoML pillar. The research team publishes here and can "
            "speak to applied AI research and how AutoML streamlines data "
            "science workloads on the platform. Academic venue does NOT mean "
            "wrong audience — that assumption was wrong."
        ),
        "series": "NeurIPS", "event_kind": "research",
        "location_city": "Vancouver", "location_country": "CA",
        "start": "2026-12-06", "cfp_close": "2026-05-15",
        "description": (
            "The Conference on Neural Information Processing Systems. Novel "
            "research contributions in machine learning theory, optimisation, "
            "and statistical learning. Peer-reviewed proceedings."
        ),
        "cfp_topics": ["machine learning theory", "optimisation", "novel architectures"],
    },
    {
        "name": "International Workshop on Statistical Learning Theory",
        "expect": "weak",
        "why": (
            "UNCONFIRMED LABEL. Pure theory, small, no applied or platform "
            "angle, so it reads low-value even for the research team — but "
            "the NeurIPS mislabel showed I should not assume academic means "
            "irrelevant. Confirm with the operator before trusting this row."
        ),
        "series": "IWSLT", "event_kind": "research",
        "location_city": "Kyoto", "location_country": "JP",
        "start": "2026-08-11", "cfp_close": "2026-03-01",
        "description": (
            "A small academic workshop on the theoretical foundations of "
            "statistical learning, generalisation bounds and PAC learning."
        ),
        "cfp_topics": ["learning theory", "generalisation bounds"],
    },
    {
        "name": "AI in Marketing Automation Summit 2026",
        "expect": "veto",
        "why": (
            "The real veto shape: heavy AI vocabulary so it embeds close to "
            "our messaging, but the audience is marketing operations. "
            "Similarity cannot reject it; only reading intent can."
        ),
        "series": "AI in Marketing Automation Summit", "event_kind": "corporate",
        "location_city": "Barcelona", "location_country": "ES",
        "start": "2026-09-30", "cfp_close": "2026-06-15",
        "description": (
            "How generative AI, large language models, agents and machine "
            "learning are transforming marketing automation, personalisation "
            "and customer engagement at enterprise scale."
        ),
        "cfp_topics": ["generative AI", "LLM", "agents", "machine learning", "personalisation"],
    },
    # --- weak ---------------------------------------------------------------
    {
        "name": "WordPress Community Summit 2026",
        "expect": "weak",
        "why": "wrong technology, wrong audience entirely",
        "series": "WordPress Community Summit", "event_kind": "corporate",
        "location_city": "Porto", "location_country": "PT",
        "start": "2026-07-08", "cfp_close": "2026-03-20",
        "description": (
            "For the WordPress community: themes, plugins, publishing "
            "workflows and running WordPress at scale."
        ),
        "cfp_topics": ["wordpress", "PHP", "publishing", "themes"],
    },
    {
        "name": "Blockchain & Web3 Expo 2026",
        "expect": "weak",
        "why": "unrelated domain; occasional 'AI' keyword only",
        "series": "Blockchain & Web3 Expo", "event_kind": "corporate",
        "location_city": "Singapore", "location_country": "SG",
        "start": "2026-04-22", "cfp_close": "2026-01-10",
        "description": (
            "Decentralised finance, smart contracts, tokenomics and the "
            "occasional AI-on-chain panel."
        ),
        "cfp_topics": ["blockchain", "web3", "smart contracts"],
    },
    {
        "name": "Enterprise Marketing Leaders Forum 2026",
        "expect": "weak",
        "why": "business audience, no technical content",
        "series": "Enterprise Marketing Leaders Forum", "event_kind": "corporate",
        "location_city": "New York", "location_country": "US",
        "start": "2026-06-15", "cfp_close": None,
        "description": (
            "For CMOs and marketing leaders: brand strategy, demand "
            "generation, and using AI tools in marketing operations."
        ),
        "cfp_topics": ["marketing", "brand", "demand generation"],
    },
    # --- CFP already closed (filter test) ----------------------------------
    {
        "name": "PyTorch Conference 2026",
        "expect": "strong",
        "why": "strong fit but the CFP has closed — a filter case, not a rank case",
        "series": "PyTorch Conference", "event_kind": "corporate",
        "location_city": "San Jose", "location_country": "US",
        "start": "2026-10-22", "cfp_close": "2025-06-01",
        "description": (
            "The PyTorch ecosystem conference: training, inference, "
            "compilers, quantisation and deployment of open models."
        ),
        "cfp_topics": ["pytorch", "inference", "quantisation", "compilers"],
    },
    # --- grassroot (excluded from the finder by default) -------------------
    {
        "name": "Internal AI Platform Day 2026",
        "expect": "weak",
        "why": "our own event; auto-approved and excluded from the finder",
        "series": "Internal AI Platform Day", "event_kind": "grassroot",
        "location_city": "Raleigh", "location_country": "US",
        "start": "2026-05-05", "cfp_close": None,
        "description": "An internal day for our own platform teams.",
        "cfp_topics": ["internal"],
    },
]


def summary() -> dict[str, int]:
    """Counts by expectation label — used by the seeder's output."""
    out: dict[str, int] = {}
    for c in CONFERENCES:
        out[c["expect"]] = out.get(c["expect"], 0) + 1
    return out
