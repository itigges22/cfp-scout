"""POST hand-extracted AI product messaging docs to Scout.

Reads from in-script constants (sourced from the parsed Docling output of
each guide in rh-docs/) and POSTs to ``/api/v1/messaging-documents``.

Idempotent-ish: posts always create new rows. If you re-run, delete the
prior rows in the UI or via DELETE /messaging-documents/{id}, otherwise
you'll get duplicates with the same title.

Run from the host (curl-style script using requests-style stdlib)::

  python3 scripts/post_messaging_docs.py http://localhost:8000

Or from inside the api container::

  podman exec scout-api /app/.venv/bin/python /app/scripts/post_messaging_docs.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Content — extracted manually from the parsed messaging PDFs in rh-docs/.
# ---------------------------------------------------------------------------

DOCS: list[dict[str, Any]] = [
    {
        "title": "AI (umbrella)",
        "source_type": "structured",
        "elevator_pitch": (
            "AI accelerates the development and deployment of "
            "enterprise AI solutions across hybrid cloud environments. It is "
            "a platform that meets customers where they are — whether just "
            "starting out or scaling to full enterprise architecture — while "
            "supporting the deployment of any model on any hardware "
            "accelerator. The four pillars: efficient inferencing, connecting "
            "models to data, agentic AI innovation, and hybrid cloud AI at scale."
        ),
        "target_personas": [
            "AI / ML platform lead",
            "ITOps decision-maker",
            "VP Engineering / CTO",
            "AI engineer / data scientist",
            "Platform engineer",
        ],
        "key_themes": [
            "Efficient inferencing (vLLM, llm-d, LLM compressor, chat-model)",
            "Connecting models to data (training-toolkit, RAG, RAFT, synthetic data)",
            "Agentic AI innovation (Llama Stack API, MCP, AI hub, gen AI studio)",
            "Hybrid cloud AI at scale (MLOps, GenAIOps, LLM API, air-gapped)",
            "Any model, any hardware, anywhere",
            "Open-source model lifecycle with enterprise support",
        ],
        "talking_points": [
            "Optimized inference runtime: vLLM + llm-d + LLM compressor reduce cost while preserving accuracy",
            "chat-model model family: smaller, Apache-2.0-licensed, fully indemnified by <vendor>",
            "Pre-optimized model repository on the AI Hugging Face page",
            "training-toolkit + RAFT pattern for cost-effective domain alignment",
            "Llama Stack API as enterprise-grade unified entry point",
            "MCP for standardized tool / data integration",
            "Distributed workloads scale training + tuning across cluster nodes",
            "Managed API gateway enables internal Models-as-a-Service",
            "On-premise + air-gapped deployments for regulated environments",
            "DenizBank, Turkish Airlines, and other customer references prove enterprise impact",
        ],
        "differentiators": [
            "Meets customers at any AI maturity stage",
            "Single platform across the AI lifecycle (develop → deploy → operate)",
            "Cross-hardware support: NVIDIA, AMD, Intel, plus partner OEMs",
            "Apache-2.0 chat-model models with IP indemnification",
            "Open-source-first stack with enterprise support contract",
        ],
        "competitive_position": (
            "AI counter-positions against hyperscaler AI services by "
            "giving organizations the same lifecycle capabilities without "
            "lock-in to a single cloud or hardware vendor. Against proprietary "
            "model SaaS, it provides a 'become your own token provider' "
            "narrative. Against DIY open-source assemblies, it provides "
            "tested integration, support, IP indemnification, and validated "
            "model collections under a single <vendor> contract."
        ),
        "is_active": True,
    },
    {
        "title": "AI platform",
        "source_type": "structured",
        "elevator_pitch": (
            "AI platform is an integrated AI platform for deploying "
            "and managing efficient and cost-effective AI models, agents, and "
            "AI-powered applications across hybrid cloud environments. It "
            "unifies AI model and application lifecycles to increase efficiency, "
            "accelerate delivery, and mitigate risk by providing a ready-to-use "
            "development environment with enterprise-grade capabilities."
        ),
        "target_personas": [
            "Platform engineer",
            "MLOps / GenAIOps engineer",
            "AI engineer / data scientist",
            "Application developer",
        ],
        "key_themes": [
            "Hybrid cloud AI platform",
            "Unified model + application lifecycle",
            "Enterprise-grade security and governance",
            "Any model, any hardware, anywhere",
            "Agentic AI workflows",
        ],
        "talking_points": [
            "Accelerate time-to-value with a ready-to-use AI stack on your infrastructure of choice",
            "Increase operational efficiency through automated workflows from commit to deploy",
            "Mitigate risk via an integrated, tested, indemnified AI stack",
            "Single Kubernetes platform powered by OpenShift",
            "Layered security across the entire AI lifecycle",
            "Intelligent resource allocation for training and inference",
        ],
        "differentiators": [
            "Unified platform covering both model and app lifecycles",
            "Tested, supported AI stack with <vendor> enterprise commitments",
            "Data residency + regulatory needs addressable on customer infrastructure",
            "Interoperability across any model, any hardware, hybrid cloud",
        ],
        "competitive_position": (
            "AI platform differentiates by unifying model and "
            "application lifecycles on a single Kubernetes-powered platform "
            "(OpenShift), eliminating the fragmentation of point solutions. "
            "Where SaaS-only AI platforms force data exfiltration and lock-in, "
            "AI Enterprise lets organizations run AI where their data already "
            "lives — on-premise, edge, or public cloud — with <vendor> support "
            "and indemnification covering the full stack."
        ),
        "is_active": True,
    },
    {
        "title": "<vendor> Enterprise Linux AI",
        "source_type": "structured",
        "elevator_pitch": (
            "<vendor> Enterprise Linux AI (AI platform) is a foundation model "
            "platform for running large language models in individual server "
            "environments. The solution includes the AI Inference "
            "Server, delivering fast, cost-effective hybrid cloud inference "
            "by maximizing throughput, minimizing latency, and reducing "
            "compute costs."
        ),
        "target_personas": [
            "ITOps decision-maker",
            "Data scientist",
            "Application developer",
            "Platform engineer",
        ],
        "key_themes": [
            "Open-source chat-model family LLMs",
            "Cost-effective inference",
            "Reduced operational complexity",
            "Deployment flexibility and consistency",
            "Image Mode for RHEL",
        ],
        "talking_points": [
            "Empower innovation with enterprise-grade open-source chat-model models, fully indemnified",
            "inference server boosts efficiency by optimizing GPU usage with vLLM",
            "LLM Compressor reduces compute costs while maintaining model accuracy",
            "Pre-optimized model repository accelerates time to production",
            "Run models in datacenters, clouds, or at the edge with consistent operations",
            "Integrates with Prometheus and Grafana for observability and governance",
        ],
        "differentiators": [
            "Immutable bootable appliance via Image Mode for RHEL",
            "chat-model models packaged + supported by <vendor> with IP indemnification",
            "vLLM-based inference avoids per-accelerator runtime fragmentation",
            "24×7 enterprise support + extended model lifecycle",
        ],
        "competitive_position": (
            "AI platform counter-positions against proprietary cloud-only LLM "
            "stacks by packaging chat-model + vLLM as a bootable appliance you "
            "can run wherever your data is. Versus DIY open-source assemblies, "
            "it provides a supported, indemnified path with single-vendor "
            "accountability for the whole stack — the OS, the inference "
            "runtime, the model, and the lifecycle."
        ),
        "is_active": True,
    },
    {
        "title": "<vendor> AI platform",
        "source_type": "structured",
        "elevator_pitch": (
            "<vendor> AI platform is an AI platform for building, training, "
            "deploying, and governing predictive and generative AI models at "
            "scale across hybrid cloud environments. Building on <vendor> "
            "OpenShift, it accelerates AI innovation, resolves shadow IT with "
            "Models-as-a-Service, and drives operational consistency for "
            "autonomous workloads."
        ),
        "target_personas": [
            "ITOps / infrastructure",
            "AI platform team",
            "AI engineer / data scientist",
            "Application developer",
            "AI / ML platform lead",
        ],
        "key_themes": [
            "Increased efficiency at scale",
            "Reduced operational complexity for predictive + generative + agentic AI",
            "Hybrid cloud flexibility",
            "Models-as-a-Service (LLM API)",
            "AI safety and governance",
            "Agentic AI workflows (MCP, AgentOps)",
        ],
        "talking_points": [
            "Models-as-a-Service: self-service approved-model API access with usage tracking",
            "Optimized model serving: vLLM, llm-d, LLM compressor for production-scale inference",
            "Agentic AI: MCP, Open Responses API, AI hub + gen AI studio, MLflow traceability",
            "JupyterLab + RAG + training-toolkit training for model alignment",
            "GPU and hardware resource management with quota and priority",
            "AI safety: Garak adversarial scanning, Nemo Guardrails, synthetic data generation",
            "Versioned AI pipelines for reproducible, auditable workflows",
            "Model observability: drift detection, bias monitoring, MLflow audit trails",
            "EvalHub for benchmarking models, RAG pipelines, and AI agents",
            "Catalog + registry for predictive + gen AI models and MCP servers",
            "Disconnected + edge + air-gapped deployment support",
        ],
        "differentiators": [
            "Move customers from 'token consumers' to 'token providers' via enterprise AI token factory",
            "Comprehensive MLOps + GenAIOps + AgentOps in one platform",
            "Centralized self-service that eliminates shadow AI",
            "Cross-accelerator support: NVIDIA, AMD, Intel, others",
            "OpenShift foundation gives a single platform across the AI lifecycle",
        ],
        "competitive_position": (
            "AI platform competes with hyperscaler AI platforms by giving "
            "enterprises the same lifecycle capabilities without lock-in to "
            "a single cloud or hardware vendor. Against fragmented open-source "
            "stacks, it bundles MLOps, GenAIOps, and AgentOps with security "
            "and governance baked in. Against SaaS chatbot APIs, it lets "
            "organizations become token providers themselves, controlling "
            "cost, data, and compliance."
        ),
        "is_active": True,
    },
    {
        "title": "inference server",
        "source_type": "structured",
        "elevator_pitch": (
            "inference server provides consistent, fast, and "
            "cost-effective inference at scale. It runs any generative AI "
            "model on any hardware accelerator (NVIDIA, Intel, AMD) and in "
            "any environment (datacenter, cloud, edge) — providing the "
            "flexibility and choice to meet business requirements."
        ),
        "target_personas": [
            "Platform engineer",
            "AI engineer / data scientist",
            "Application developer",
            "ITOps decision-maker",
        ],
        "key_themes": [
            "Increased efficiency through vLLM and LLM compression",
            "Reduced operational complexity",
            "Hybrid cloud flexibility",
            "Cross-accelerator support",
            "OpenAI-compatible APIs",
        ],
        "talking_points": [
            "vLLM at its core provides a unified, high-performance inference runtime",
            "LLM Compressor reduces compute costs while maintaining accuracy",
            "Optimized model repository on the AI Hugging Face page (2-4x efficiency)",
            "Certified for all <vendor> products: AI platform, AI platform, OpenShift, RHEL",
            "Third-party platform support: non-<vendor> Linux + Kubernetes covered",
            "Integration with Prometheus and Grafana observability",
            "OpenAI-compatible API for drop-in application integration",
        ],
        "differentiators": [
            "vLLM-based runtime unifies across hardware accelerators",
            "Decouples inference from a specific hardware or cloud provider",
            "Available across the <vendor> portfolio + third-party platforms",
            "Pre-optimized model collection accelerates time to production",
        ],
        "competitive_position": (
            "AI Inference Server competes with proprietary inference SaaS "
            "(OpenAI, Anthropic API) by giving organizations a self-hosted "
            "OpenAI-compatible endpoint. Against single-accelerator runtimes "
            "(Nvidia Triton, vendor-specific stacks), it provides cross-"
            "vendor portability via vLLM. Against DIY vLLM deployments, it "
            "adds <vendor> support, IP indemnification, and validated, "
            "pre-optimized model collections."
        ),
        "is_active": True,
    },
]


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------
def post_one(base_url: str, doc: dict[str, Any]) -> None:
    body = json.dumps(doc).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/messaging-documents",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            print(f"  OK  {doc['title']:35s} → id={data.get('id')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"  FAIL {doc['title']:35s} → HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        print(f"  FAIL {doc['title']:35s} → {exc}")


def main(base_url: str) -> None:
    print(f"Posting {len(DOCS)} messaging documents to {base_url}...")
    for d in DOCS:
        post_one(base_url, d)
    print("Done.")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    main(url)
